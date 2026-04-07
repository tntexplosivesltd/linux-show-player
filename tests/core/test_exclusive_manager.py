from unittest.mock import MagicMock

from lisp.core.exclusive_manager import ExclusiveManager
from lisp.cues.cue import CueState


def _make_model(cues=None):
    """Create a mock CueModel that iterates over the given cues."""
    model = MagicMock()
    cue_list = cues or []
    model.__iter__ = MagicMock(return_value=iter(cue_list))
    return model


def _make_cue(exclusive=False, state=CueState.Stop, name="Test"):
    cue = MagicMock()
    cue.exclusive = exclusive
    cue.state = state
    cue.name = name
    return cue


class TestIsStartBlocked:
    def test_no_running_cues_not_blocked(self):
        cue = _make_cue()
        model = _make_model([cue])
        mgr = ExclusiveManager(model)
        assert mgr.is_start_blocked(cue) is False

    def test_blocked_when_exclusive_cue_running(self):
        running = _make_cue(
            exclusive=True, state=CueState.Running, name="Running"
        )
        new = _make_cue(name="New")
        model = _make_model([running, new])
        mgr = ExclusiveManager(model)
        assert mgr.is_start_blocked(new) is True

    def test_not_blocked_when_non_exclusive_running(self):
        running = _make_cue(
            exclusive=False, state=CueState.Running
        )
        new = _make_cue()
        model = _make_model([running, new])
        mgr = ExclusiveManager(model)
        assert mgr.is_start_blocked(new) is False

    def test_exclusive_blocks_other_exclusive(self):
        running = _make_cue(
            exclusive=True, state=CueState.Running
        )
        new = _make_cue(exclusive=True)
        model = _make_model([running, new])
        mgr = ExclusiveManager(model)
        assert mgr.is_start_blocked(new) is True

    def test_not_blocked_by_self(self):
        cue = _make_cue(
            exclusive=True, state=CueState.Running
        )
        model = _make_model([cue])
        mgr = ExclusiveManager(model)
        assert mgr.is_start_blocked(cue) is False

    def test_blocked_by_prewait_state(self):
        running = _make_cue(
            exclusive=True, state=CueState.PreWait
        )
        new = _make_cue()
        model = _make_model([running, new])
        mgr = ExclusiveManager(model)
        assert mgr.is_start_blocked(new) is True

    def test_blocked_by_postwait_state(self):
        running = _make_cue(
            exclusive=True, state=CueState.PostWait
        )
        new = _make_cue()
        model = _make_model([running, new])
        mgr = ExclusiveManager(model)
        assert mgr.is_start_blocked(new) is True

    def test_not_blocked_by_stopped_exclusive(self):
        stopped = _make_cue(
            exclusive=True, state=CueState.Stop
        )
        new = _make_cue()
        model = _make_model([stopped, new])
        mgr = ExclusiveManager(model)
        assert mgr.is_start_blocked(new) is False

    def test_not_blocked_by_paused_exclusive(self):
        paused = _make_cue(
            exclusive=True, state=CueState.Pause
        )
        new = _make_cue()
        model = _make_model([paused, new])
        mgr = ExclusiveManager(model)
        assert mgr.is_start_blocked(new) is False
