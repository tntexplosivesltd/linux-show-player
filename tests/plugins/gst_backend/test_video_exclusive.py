"""Tests for VideoExclusiveManager."""

from unittest.mock import MagicMock

from lisp.cues.cue import CueState
from lisp.plugins.gst_backend.gi_repository import Gst
from lisp.plugins.gst_backend.video_exclusive import (
    VideoExclusiveManager,
)


def _make_app():
    app = MagicMock()
    app.notify = MagicMock()
    return app


def _make_cue(has_video_sink=False):
    cue = MagicMock()
    cue.state = CueState.Stop
    if has_video_sink:
        cue.media.element.return_value = MagicMock()
    else:
        cue.media.element.return_value = None
    return cue


class TestVideoExclusiveManager:
    def test_non_video_cue_never_blocked(self):
        app = _make_app()
        mgr = VideoExclusiveManager(app)
        cue = _make_cue(has_video_sink=False)
        assert mgr.is_start_blocked(cue) is False

    def test_video_cue_not_blocked_when_nothing_playing(self):
        app = _make_app()
        mgr = VideoExclusiveManager(app)
        cue = _make_cue(has_video_sink=True)

        from lisp.plugins.gst_backend.elements.video_sink \
            import VideoSink
        VideoSink._previous_sink = None

        assert mgr.is_start_blocked(cue) is False

    def test_video_cue_blocked_when_another_playing(self):
        app = _make_app()
        mgr = VideoExclusiveManager(app)
        cue = _make_cue(has_video_sink=True)

        # Simulate a previous sink with PLAYING pipeline
        from lisp.plugins.gst_backend.elements.video_sink \
            import VideoSink

        mock_prev = MagicMock()
        mock_prev.pipeline.get_state.return_value = (
            Gst.StateChangeReturn.SUCCESS,
            Gst.State.PLAYING,
            Gst.State.VOID_PENDING,
        )
        VideoSink._previous_sink = mock_prev

        try:
            assert mgr.is_start_blocked(cue) is True
            app.notify.emit.assert_called_once()
        finally:
            VideoSink._previous_sink = None

    def test_video_cue_blocked_when_another_paused(self):
        app = _make_app()
        mgr = VideoExclusiveManager(app)
        cue = _make_cue(has_video_sink=True)

        from lisp.plugins.gst_backend.elements.video_sink \
            import VideoSink

        mock_prev = MagicMock()
        mock_prev.pipeline.get_state.return_value = (
            Gst.StateChangeReturn.SUCCESS,
            Gst.State.PAUSED,
            Gst.State.VOID_PENDING,
        )
        VideoSink._previous_sink = mock_prev

        try:
            assert mgr.is_start_blocked(cue) is True
        finally:
            VideoSink._previous_sink = None

    def test_video_cue_not_blocked_when_previous_stopped(self):
        app = _make_app()
        mgr = VideoExclusiveManager(app)
        cue = _make_cue(has_video_sink=True)

        from lisp.plugins.gst_backend.elements.video_sink \
            import VideoSink

        mock_prev = MagicMock()
        mock_prev.pipeline.get_state.return_value = (
            Gst.StateChangeReturn.SUCCESS,
            Gst.State.READY,
            Gst.State.VOID_PENDING,
        )
        VideoSink._previous_sink = mock_prev

        try:
            assert mgr.is_start_blocked(cue) is False
        finally:
            VideoSink._previous_sink = None

    def test_cue_without_media_not_blocked(self):
        """Non-media cues (e.g. GroupCue) should never be
        blocked."""
        app = _make_app()
        mgr = VideoExclusiveManager(app)
        cue = MagicMock(spec=[])  # no media attribute
        assert mgr.is_start_blocked(cue) is False
