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
    def __init__(self, available=True):
        self.available = available
        self.failed = Signal()
        self.set_canvas_size = MagicMock()
        self.shutdown = MagicMock()
        self.register = MagicMock(return_value=None)
        self.unregister = MagicMock()


def _window():
    window = MagicMock()
    window.render_size_changed = Signal()
    window.render_size.return_value = (1920, 1080)
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
    def test_compositor_built_with_windows_and_render_size(self, build):
        backend, app, comp, ctor = build()
        assert GstBackend.video_compositor() is comp
        ctor.assert_called_once_with(
            GstBackend.video_window(),
            GstBackend.monitor_window(),
            canvas_size=(1920, 1080),
        )

    def test_render_size_change_resizes_canvas(self, build):
        backend, app, comp, _ = build()
        GstBackend.video_window().render_size_changed.emit(1280, 720)
        comp.set_canvas_size.assert_called_once_with(1280, 720)

    def test_available_compositor_does_not_warn(self, build):
        backend, app, comp, _ = build()
        assert _warnings(app) == []

    def test_unavailable_compositor_warns(self, build):
        backend, app, comp, _ = build(_FakeCompositor(available=False))
        assert len(_warnings(app)) == 1

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
