"""GstBackend's VideoCompositor wiring and teardown.

Runs the real GstBackend.__init__ and finalize(); only the outward
dependencies are faked (windows, the compositor class, settings
registries, menus, the global backend). The fake window and compositor
carry real LiSP Signals, so the real connections are exercised.

finalize() must shut the compositor down before the session and the Qt
windows are torn down: left PLAYING, the GL sinks render into dying X
windows during exit (MESA BadDrawable, intermittent segfault).
"""

from unittest.mock import MagicMock, patch

import pytest

from lisp.core.signal import Signal
from lisp.plugins.gst_backend import gst_backend as gb
from lisp.plugins.gst_backend.elements.video_sink import VideoSink
from lisp.plugins.gst_backend.gi_repository import Gst
from lisp.plugins.gst_backend.gst_backend import GstBackend
from lisp.plugins.gst_backend.video_exclusive import (
    VideoExclusiveManager,
)
from lisp.ui.widgets.notification import NotificationLevel


class _FakeCompositor:
    def __init__(self, available=True, unavailable_reason=None):
        self.available = available
        self.unavailable_reason = unavailable_reason
        self.failed = Signal()
        self.restored = Signal()
        self.gave_up = Signal()
        self.set_canvas_size = MagicMock()
        self.shutdown = MagicMock()
        self.register = MagicMock(return_value=None)
        self.unregister = MagicMock()
        self.is_quarantined = MagicMock(return_value=False)
        self.sink_scales = MagicMock(return_value=True)


def _window():
    window = MagicMock()
    window.canvas_size_changed = Signal()
    window.canvas_size.return_value = (1920, 1080)
    return window


@pytest.fixture
def build():
    """build(compositor) -> (backend, app, compositor, ctor) with the
    real __init__ run against fakes. Class-level singletons, plugin
    state and the global backend are restored afterwards."""
    stack = []

    def _build(compositor=None, ctor=None):
        compositor = compositor or _FakeCompositor()
        ctor = ctor or MagicMock(return_value=compositor)
        patches = [
            patch.object(GstBackend, "_video_window", None),
            patch.object(GstBackend, "_monitor_window", None),
            patch.object(GstBackend, "_video_compositor", None),
            patch.object(GstBackend, "State", GstBackend.State),
            patch("lisp.plugins.gst_backend.gst_video_window."
                  "VideoOutputWindow", side_effect=lambda _p: _window()),
            patch("lisp.plugins.gst_backend.gst_video_window."
                  "VideoMonitorWindow", side_effect=lambda _p: _window()),
            patch.object(GstBackend,
                         "_GstBackend__apply_video_config"),
            patch("lisp.plugins.gst_backend.video_compositor."
                  "VideoCompositor", ctor),
            patch.object(gb.AppConfigurationDialog,
                         "registerSettingsPage"),
            patch.object(gb.config, "load", return_value=[]),
            patch.object(gb, "CueSettingsRegistry"),
            patch.object(gb, "QAction"),
            patch.object(gb.elements, "load"),
            patch.object(gb.settings, "load"),
            patch.object(gb.backend, "set_backend"),
        ]
        for p in patches:
            p.start()
            stack.append(p)
        app = MagicMock()
        backend = GstBackend(app)
        return backend, app, compositor, ctor

    yield _build
    for p in reversed(stack):
        p.stop()


def _warnings(app):
    return [
        c for c in app.notify.emit.call_args_list
        if c.args[1] == NotificationLevel.Warning
    ]


class TestCompositorWiring:
    def test_compositor_built_with_windows_and_canvas_size(self, build):
        backend, app, comp, ctor = build()
        assert GstBackend.video_compositor() is comp
        ctor.assert_called_once_with(
            GstBackend.video_window(),
            GstBackend.monitor_window(),
            canvas_size=(1920, 1080),
        )

    def test_canvas_size_change_resizes_canvas(self, build):
        backend, app, comp, _ = build()
        GstBackend.video_window().canvas_size_changed.emit(1280, 720)
        comp.set_canvas_size.assert_called_once_with(1280, 720)

    def test_scaling_sink_keeps_the_screen_canvas(self, build):
        backend, app, comp, _ = build()
        window = GstBackend.video_window()
        window.set_canvas_follows_window.assert_not_called()
        comp.set_canvas_size.assert_not_called()

    def test_non_scaling_sink_makes_the_canvas_follow_the_window(
            self, build):
        comp = _FakeCompositor()
        comp.sink_scales.return_value = False
        build(comp)
        window = GstBackend.video_window()
        window.set_canvas_follows_window.assert_called_once_with(True)
        comp.set_canvas_size.assert_called_once_with(
            *window.canvas_size())

    def test_available_compositor_does_not_warn(self, build):
        backend, app, comp, _ = build()
        assert _warnings(app) == []

    def test_unavailable_compositor_warns(self, build):
        backend, app, comp, _ = build(_FakeCompositor(available=False))
        assert len(_warnings(app)) == 1

    def test_unavailable_warning_gives_the_reason(self, build):
        reason = "needs GStreamer 1.20 or newer (found 1.18.4)"
        backend, app, comp, _ = build(
            _FakeCompositor(available=False, unavailable_reason=reason))
        (call,) = _warnings(app)
        assert reason in call.args[0]

    def test_runtime_failure_warns(self, build):
        backend, app, comp, _ = build()
        comp.failed.emit()
        assert len(_warnings(app)) == 1

    def test_compositor_constructor_raising_degrades(self, build):
        # Audio cues must survive: the backend still loads, without a
        # compositor, and the operator is told video is unavailable.
        ctor = MagicMock(side_effect=RuntimeError("no GL"))
        backend, app, _, _ = build(ctor=ctor)
        assert GstBackend.video_compositor() is None
        assert len(_warnings(app)) == 1
        gb.backend.set_backend.assert_called_once_with(backend)
        assert isinstance(app.video_exclusive_manager,
                          VideoExclusiveManager)
        backend.finalize()  # must not raise either

    def test_exclusive_manager_installed(self, build):
        backend, app, comp, _ = build()
        assert isinstance(app.video_exclusive_manager,
                          VideoExclusiveManager)


class TestRecovery:
    """failed → a rebuild is coming; restored → active cues re-attach
    (and the operator is told); gave_up → audio only for good."""

    @pytest.fixture(autouse=True)
    def _stop_played(self):
        # A played sink left active leaks into later tests: when it is
        # finally stopped or collected it unregisters from whatever
        # compositor that test has patched in.
        self._sinks = []
        yield
        with patch.object(GstBackend, "_video_compositor", None):
            for sink in self._sinks:
                sink.stop()

    def _played(self):
        sink = VideoSink(Gst.Pipeline())  # never started: no audio
        with patch.object(GstBackend, "_video_compositor", None):
            sink.play()  # active, no branch (compositor down)
        self._sinks.append(sink)
        return sink

    def test_failure_warns_that_a_restart_is_coming(self, build):
        backend, app, comp, _ = build()
        comp.failed.emit()
        (call,) = _warnings(app)
        assert "restart" in call.args[0].lower()

    def test_restored_reattaches_active_sinks_only(self, build):
        backend, app, comp, _ = build()
        playing, stopped = self._played(), self._played()
        stopped.stop()
        with patch.object(VideoSink, "reattach", autospec=True) as reattach:
            comp.restored.emit()
        # autospec passes the sink as the first argument.
        assert [c.args for c in reattach.call_args_list] == [
            (playing, comp)]

    def test_restored_gives_playing_cue_a_branch(self, build):
        backend, app, comp, _ = build()
        sink = self._played()
        assert sink._registration is None
        reg = object()
        comp.register.return_value = reg
        comp.restored.emit()
        assert sink._registration is reg

    def test_restored_notifies(self, build):
        backend, app, comp, _ = build()
        comp.restored.emit()
        levels = [c.args[1] for c in app.notify.emit.call_args_list]
        assert NotificationLevel.Info in levels

    @staticmethod
    def _cue(name, sink):
        cue = MagicMock()
        cue.name = name
        cue.media.element.side_effect = (
            lambda kind: sink if kind == "VideoSink" else None)
        return cue

    def test_restored_names_cues_left_audio_only(self, build):
        # A quarantined cue gets no branch back: the operator must not
        # be told "restored" while it stays black on stage.
        backend, app, comp, _ = build()
        bad, good = self._played(), self._played()
        app.cue_model = [self._cue("Storm clip", bad),
                         self._cue("Sunrise", good)]
        comp.is_quarantined.side_effect = lambda sink: sink is bad
        comp.restored.emit()
        (call,) = _warnings(app)
        assert "Storm clip" in call.args[0]
        assert "Sunrise" not in call.args[0]
        assert "audio only" in call.args[0]
        levels = [c.args[1] for c in app.notify.emit.call_args_list]
        assert NotificationLevel.Info not in levels

    def test_gave_up_warns_audio_only(self, build):
        backend, app, comp, _ = build()
        comp.gave_up.emit()
        (call,) = _warnings(app)
        assert "audio only" in call.args[0]


class TestFinalize:
    def test_finalize_shuts_down_and_clears_singleton(self, build):
        backend, app, comp, _ = build()
        backend.finalize()
        comp.shutdown.assert_called_once_with()
        assert GstBackend.video_compositor() is None

    def test_finalize_twice_is_safe(self, build):
        backend, app, comp, _ = build()
        backend.finalize()
        backend.finalize()
        comp.shutdown.assert_called_once_with()

    def test_video_sink_after_finalize_is_a_no_op(self, build):
        # A cue started or stopped during teardown must neither reach
        # the shut-down compositor nor raise.
        backend, app, comp, _ = build()
        backend.finalize()
        sink = VideoSink(Gst.Pipeline())  # never started: no audio
        sink.play()
        assert sink._registration is None
        sink.stop()
        comp.register.assert_not_called()
        comp.unregister.assert_not_called()
