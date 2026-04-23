"""Tests for the state-precondition guard around the exclusive /
video-exclusive block checks in `Cue.execute`.

Context: the block managers shouldn't be consulted when the action
is a no-op anyway — e.g. pressing "Resume All" should not emit a
"blocked" notification for every stopped video cue in the session,
since `Cue.resume()` is a no-op outside `CueState.IsPaused`.
"""

from unittest.mock import MagicMock

from lisp.cues.cue import Cue, CueAction, CueState


def _cue_with_managers(mock_app, state):
    """Return a (cue, exc, vid) triple where exc/vid are the mocked
    managers on mock_app. Both return False by default."""
    exc_mgr = MagicMock()
    exc_mgr.is_start_blocked.return_value = False
    vid_mgr = MagicMock()
    vid_mgr.is_start_blocked.return_value = False
    mock_app.exclusive_manager = exc_mgr
    mock_app.video_exclusive_manager = vid_mgr

    cue = Cue(app=mock_app)
    # Bypass the WriteOnce lock on _state via direct attribute set.
    cue._state = state
    return cue, exc_mgr, vid_mgr


class TestResumeGuard:
    """`CueAction.Resume` should only consult the block managers when
    the cue is actually paused — otherwise resume is a no-op."""

    def test_resume_on_stopped_cue_skips_block_check(self, mock_app):
        cue, exc, vid = _cue_with_managers(mock_app, CueState.Stop)
        cue.execute(CueAction.Resume)
        exc.is_start_blocked.assert_not_called()
        vid.is_start_blocked.assert_not_called()

    def test_resume_on_running_cue_skips_block_check(self, mock_app):
        cue, exc, vid = _cue_with_managers(mock_app, CueState.Running)
        cue.execute(CueAction.Resume)
        exc.is_start_blocked.assert_not_called()
        vid.is_start_blocked.assert_not_called()

    def test_resume_on_paused_cue_runs_block_check(self, mock_app):
        cue, exc, vid = _cue_with_managers(mock_app, CueState.Pause)
        cue.execute(CueAction.Resume)
        exc.is_start_blocked.assert_called_once()
        vid.is_start_blocked.assert_called_once()

    def test_fade_in_resume_on_stopped_cue_skips_block_check(
        self, mock_app,
    ):
        cue, exc, vid = _cue_with_managers(mock_app, CueState.Stop)
        cue.execute(CueAction.FadeInResume)
        exc.is_start_blocked.assert_not_called()
        vid.is_start_blocked.assert_not_called()


class TestStartGuard:
    """`CueAction.Start` on a cue that's already running is a no-op,
    so the block check shouldn't fire there either."""

    def test_start_on_stopped_cue_runs_block_check(self, mock_app):
        cue, exc, vid = _cue_with_managers(mock_app, CueState.Stop)
        cue.execute(CueAction.Start)
        exc.is_start_blocked.assert_called_once()
        vid.is_start_blocked.assert_called_once()

    def test_start_on_running_cue_skips_block_check(self, mock_app):
        cue, exc, vid = _cue_with_managers(mock_app, CueState.Running)
        cue.execute(CueAction.Start)
        exc.is_start_blocked.assert_not_called()
        vid.is_start_blocked.assert_not_called()

    def test_start_on_paused_cue_runs_block_check(self, mock_app):
        """Starting a paused cue is treated as a restart — it does
        transition state (via __start__), so the block check is
        meaningful."""
        cue, exc, vid = _cue_with_managers(mock_app, CueState.Pause)
        cue.execute(CueAction.Start)
        exc.is_start_blocked.assert_called_once()
        vid.is_start_blocked.assert_called_once()


class TestNonStartActionsUnchanged:
    """Stop/Pause/Interrupt never ran the block check in the first
    place; make sure the guard didn't accidentally broaden that."""

    def test_stop_never_runs_block_check(self, mock_app):
        cue, exc, vid = _cue_with_managers(mock_app, CueState.Running)
        cue.execute(CueAction.Stop)
        exc.is_start_blocked.assert_not_called()
        vid.is_start_blocked.assert_not_called()

    def test_pause_never_runs_block_check(self, mock_app):
        cue, exc, vid = _cue_with_managers(mock_app, CueState.Running)
        cue.execute(CueAction.Pause)
        exc.is_start_blocked.assert_not_called()
        vid.is_start_blocked.assert_not_called()
