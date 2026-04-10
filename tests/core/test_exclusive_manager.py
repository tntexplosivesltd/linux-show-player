from unittest.mock import MagicMock

from lisp.core.exclusive_manager import ExclusiveManager
from lisp.cues.cue import CueState


def _make_app(cues=None):
    """Create a mock Application with a CueModel."""
    app = MagicMock()
    cue_list = cues or []
    app.cue_model.__iter__ = MagicMock(
        return_value=iter(cue_list)
    )
    return app


def _make_cue(exclusive=False, state=CueState.Stop, name="Test"):
    cue = MagicMock()
    cue.exclusive = exclusive
    cue.state = state
    cue.name = name
    return cue


class TestIsStartBlocked:
    def test_no_running_cues_not_blocked(self):
        cue = _make_cue()
        app = _make_app([cue])
        mgr = ExclusiveManager(app)
        assert mgr.is_start_blocked(cue) is False

    def test_blocked_when_exclusive_cue_running(self):
        running = _make_cue(
            exclusive=True, state=CueState.Running, name="Running"
        )
        new = _make_cue(name="New")
        app = _make_app([running, new])
        mgr = ExclusiveManager(app)
        assert mgr.is_start_blocked(new) is True

    def test_not_blocked_when_non_exclusive_running(self):
        running = _make_cue(
            exclusive=False, state=CueState.Running
        )
        new = _make_cue()
        app = _make_app([running, new])
        mgr = ExclusiveManager(app)
        assert mgr.is_start_blocked(new) is False

    def test_exclusive_blocks_other_exclusive(self):
        running = _make_cue(
            exclusive=True, state=CueState.Running
        )
        new = _make_cue(exclusive=True)
        app = _make_app([running, new])
        mgr = ExclusiveManager(app)
        assert mgr.is_start_blocked(new) is True

    def test_not_blocked_by_self(self):
        cue = _make_cue(
            exclusive=True, state=CueState.Running
        )
        app = _make_app([cue])
        mgr = ExclusiveManager(app)
        assert mgr.is_start_blocked(cue) is False

    def test_blocked_by_prewait_state(self):
        running = _make_cue(
            exclusive=True, state=CueState.PreWait
        )
        new = _make_cue()
        app = _make_app([running, new])
        mgr = ExclusiveManager(app)
        assert mgr.is_start_blocked(new) is True

    def test_blocked_by_postwait_state(self):
        running = _make_cue(
            exclusive=True, state=CueState.PostWait
        )
        new = _make_cue()
        app = _make_app([running, new])
        mgr = ExclusiveManager(app)
        assert mgr.is_start_blocked(new) is True

    def test_not_blocked_by_stopped_exclusive(self):
        stopped = _make_cue(
            exclusive=True, state=CueState.Stop
        )
        new = _make_cue()
        app = _make_app([stopped, new])
        mgr = ExclusiveManager(app)
        assert mgr.is_start_blocked(new) is False

    def test_not_blocked_by_paused_exclusive(self):
        paused = _make_cue(
            exclusive=True, state=CueState.Pause
        )
        new = _make_cue()
        app = _make_app([paused, new])
        mgr = ExclusiveManager(app)
        assert mgr.is_start_blocked(new) is False
