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


def _make_cue(has_video_sink=False, video_sink=None):
    """Return a mock cue. `video_sink`, if given, is the specific
    VideoSink mock `cue.media.element("VideoSink")` will return —
    used to simulate "this cue owns that sink"."""
    cue = MagicMock()
    cue.state = CueState.Stop
    if has_video_sink:
        sink = video_sink if video_sink is not None else MagicMock()
        cue.media.element.return_value = sink
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

    def test_other_video_cue_blocked_when_previous_paused(self):
        """A DIFFERENT video cue is still blocked while another is
        paused — prevents overlap with a temporarily-halted video."""
        app = _make_app()
        mgr = VideoExclusiveManager(app)
        cue = _make_cue(has_video_sink=True)  # fresh sink, not the paused one

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

    def test_cue_resuming_its_own_paused_sink_not_blocked(self):
        """A video cue asking to start while its OWN sink is the paused
        previous_sink must NOT be blocked — this is the self-resume
        case hit by CueAction.Resume (or Fade & Resume) on a previously
        paused video. Before this fix, the cue was blocked by its own
        stuck sink, making a paused video impossible to resume."""
        app = _make_app()
        mgr = VideoExclusiveManager(app)

        from lisp.plugins.gst_backend.elements.video_sink \
            import VideoSink

        # The paused sink — simulate the leftover from Fade & Stop.
        own_sink = MagicMock()
        own_sink.pipeline.get_state.return_value = (
            Gst.StateChangeReturn.SUCCESS,
            Gst.State.PAUSED,
            Gst.State.VOID_PENDING,
        )
        VideoSink._previous_sink = own_sink

        # The cue's media.element("VideoSink") IS the paused sink.
        cue = _make_cue(has_video_sink=True, video_sink=own_sink)

        try:
            assert mgr.is_start_blocked(cue) is False
            app.notify.emit.assert_not_called()
        finally:
            VideoSink._previous_sink = None

    def test_cue_resuming_its_own_playing_sink_not_blocked(self):
        """Edge case: if somehow a video cue's own sink is reported as
        PLAYING (the block check is called during a spurious
        re-start attempt), don't block it either. Same principle:
        a cue never blocks itself."""
        app = _make_app()
        mgr = VideoExclusiveManager(app)

        from lisp.plugins.gst_backend.elements.video_sink \
            import VideoSink

        own_sink = MagicMock()
        own_sink.pipeline.get_state.return_value = (
            Gst.StateChangeReturn.SUCCESS,
            Gst.State.PLAYING,
            Gst.State.VOID_PENDING,
        )
        VideoSink._previous_sink = own_sink

        cue = _make_cue(has_video_sink=True, video_sink=own_sink)

        try:
            assert mgr.is_start_blocked(cue) is False
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
