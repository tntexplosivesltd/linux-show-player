"""Tests for VideoExclusiveManager.

Exclusivity follows the VideoSink lifecycle (play → stop/eos/dispose),
not the compositor's render branches: a cue whose video cannot be
projected (compositor unavailable, attach failed, compositor shut down
by an error) still plays its audio, and a second video cue must still
be blocked from playing over it.

Real VideoSinks (never started, so no audio device is opened); only
the compositor is faked.
"""

from unittest.mock import MagicMock, patch

from lisp.plugins.gst_backend import video_compositor as vc
from lisp.plugins.gst_backend.elements.video_sink import VideoSink
from lisp.plugins.gst_backend.gi_repository import Gst
from lisp.plugins.gst_backend.video_exclusive import (
    VideoExclusiveManager,
)

_CM = "lisp.plugins.gst_backend.gst_backend.GstBackend.video_compositor"


def _make_app():
    app = MagicMock()
    app.notify = MagicMock()
    return app


def _sink():
    return VideoSink(Gst.Pipeline())


def _cue(sink):
    cue = MagicMock()
    cue.media.element.return_value = sink
    return cue


def _real_compositor():
    """A real VideoCompositor around a fake pipeline."""
    out, mon = MagicMock(), MagicMock()
    out.window_handle.return_value = 1
    mon.window_handle.return_value = 2

    def fake_build(self):
        self.pipeline = MagicMock()
        self.mixer = MagicMock()
        return True

    with patch.object(vc.VideoCompositor, "_build", fake_build):
        comp = vc.VideoCompositor(out, mon)
    comp._schedule = MagicMock(return_value=1)
    comp._unschedule = MagicMock()
    # A successful attach, without building real branch elements.
    comp._attach = lambda _sink: vc.Registration()
    return comp


class TestExclusiveWithoutBranch:
    def test_no_compositor_two_sinks_stay_exclusive(self):
        mgr = VideoExclusiveManager(_make_app())
        a, b = _sink(), _sink()
        with patch(_CM, return_value=None):
            a.play()
            assert mgr.is_start_blocked(_cue(b)) is True
            a.stop()
            assert mgr.is_start_blocked(_cue(b)) is False

    def test_failed_attach_two_sinks_stay_exclusive(self):
        mgr = VideoExclusiveManager(_make_app())
        comp = _real_compositor()
        comp._attach = lambda _sink: None
        a, b = _sink(), _sink()
        with patch(_CM, return_value=comp):
            a.play()
            assert a._registration is None  # no render branch
            assert mgr.is_start_blocked(_cue(b)) is True
            a.eos()
            assert mgr.is_start_blocked(_cue(b)) is False

    def test_unavailable_compositor_two_sinks_stay_exclusive(self):
        mgr = VideoExclusiveManager(_make_app())
        comp = _real_compositor()
        comp.available = False
        a, b = _sink(), _sink()
        with patch(_CM, return_value=comp):
            a.play()
            assert a._registration is None
            assert mgr.is_start_blocked(_cue(b)) is True

    def test_compositor_shutdown_mid_playback_keeps_exclusive(self):
        mgr = VideoExclusiveManager(_make_app())
        comp = _real_compositor()
        a, b = _sink(), _sink()
        with patch(_CM, return_value=comp):
            a.play()
            assert comp.is_registered(a)
            comp.shutdown()  # e.g. a projection error
            assert mgr.is_start_blocked(_cue(b)) is True


class TestVideoExclusiveManager:
    def test_non_video_cue_never_blocked(self):
        mgr = VideoExclusiveManager(_make_app())
        assert mgr.is_start_blocked(_cue(None)) is False

    def test_cue_without_media_not_blocked(self):
        mgr = VideoExclusiveManager(_make_app())
        assert mgr.is_start_blocked(MagicMock(spec=[])) is False

    def test_blocked_notifies(self):
        app = _make_app()
        mgr = VideoExclusiveManager(app)
        a, b = _sink(), _sink()
        with patch(_CM, return_value=_real_compositor()):
            a.play()
            assert mgr.is_start_blocked(_cue(b)) is True
        app.notify.emit.assert_called_once()

    def test_not_blocked_when_nothing_plays(self):
        mgr = VideoExclusiveManager(_make_app())
        assert mgr.is_start_blocked(_cue(_sink())) is False

    def test_self_resume_not_blocked(self):
        mgr = VideoExclusiveManager(_make_app())
        a = _sink()
        with patch(_CM, return_value=_real_compositor()):
            a.play()
            assert mgr.is_start_blocked(_cue(a)) is False

    def test_dispose_releases_exclusivity(self):
        mgr = VideoExclusiveManager(_make_app())
        a, b = _sink(), _sink()
        with patch(_CM, return_value=None):
            a.play()
            a.dispose()
            assert mgr.is_start_blocked(_cue(b)) is False
