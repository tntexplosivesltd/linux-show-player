"""Tests for VideoExclusiveManager (backed by VideoCompositor)."""

from unittest.mock import MagicMock, patch

from lisp.plugins.gst_backend.video_exclusive import (
    VideoExclusiveManager,
)

_CM = "lisp.plugins.gst_backend.gst_backend.GstBackend.video_compositor"


def _make_app():
    app = MagicMock()
    app.notify = MagicMock()
    return app


def _make_cue(video_sink="__none__"):
    cue = MagicMock()
    if video_sink == "__none__":
        cue.media.element.return_value = None
    else:
        cue.media.element.return_value = video_sink
    return cue


def _patch_compositor(active_others=False):
    comp = MagicMock()
    comp.active_others.return_value = active_others
    # Patch the classmethod on the class; the lazy import inside
    # is_start_blocked resolves to this same class object.
    return patch(_CM, return_value=comp), comp


class TestVideoExclusiveManager:
    def test_non_video_cue_never_blocked(self):
        mgr = VideoExclusiveManager(_make_app())
        assert mgr.is_start_blocked(_make_cue(video_sink="__none__")) is False

    def test_blocked_when_another_registered(self):
        app = _make_app()
        mgr = VideoExclusiveManager(app)
        sink = object()
        ctx, comp = _patch_compositor(active_others=True)
        with ctx:
            assert mgr.is_start_blocked(_make_cue(video_sink=sink)) is True
            comp.active_others.assert_called_once_with(sink)
            app.notify.emit.assert_called_once()

    def test_not_blocked_when_none_registered(self):
        mgr = VideoExclusiveManager(_make_app())
        ctx, _ = _patch_compositor(active_others=False)
        with ctx:
            cue = _make_cue(video_sink=object())
            assert mgr.is_start_blocked(cue) is False

    def test_self_resume_not_blocked(self):
        # The cue owns the only registered sink → active_others False.
        mgr = VideoExclusiveManager(_make_app())
        sink = object()
        ctx, comp = _patch_compositor(active_others=False)
        with ctx:
            assert mgr.is_start_blocked(_make_cue(video_sink=sink)) is False
            comp.active_others.assert_called_once_with(sink)

    def test_no_compositor_not_blocked(self):
        mgr = VideoExclusiveManager(_make_app())
        with patch(_CM, return_value=None):
            cue = _make_cue(video_sink=object())
            assert mgr.is_start_blocked(cue) is False

    def test_cue_without_media_not_blocked(self):
        mgr = VideoExclusiveManager(_make_app())
        assert mgr.is_start_blocked(MagicMock(spec=[])) is False
