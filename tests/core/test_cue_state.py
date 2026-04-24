"""Regression tests for CueState bitflag composition."""
from lisp.cues.cue import CueState


class TestHibernatingBit:
    def test_hibernating_bit_value(self):
        assert CueState.Hibernating == 256

    def test_hibernating_does_not_overlap_existing_bits(self):
        existing = (
            CueState.Error | CueState.Stop | CueState.Running
            | CueState.Pause | CueState.PreWait | CueState.PostWait
            | CueState.PreWait_Pause | CueState.PostWait_Pause
        )
        assert (CueState.Hibernating & existing) == 0

    def test_pause_composite_still_matches_pause(self):
        """Existing state & CueState.Pause callsites must keep working
        when a cue is Pause|Hibernating."""
        composite = CueState.Pause | CueState.Hibernating
        assert composite & CueState.Pause
        assert composite & CueState.Hibernating

    def test_is_paused_composite_still_matches(self):
        composite = CueState.Pause | CueState.Hibernating
        assert composite & CueState.IsPaused


class TestHarnessSerializer:
    def test_hibernating_in_state_names(self):
        from lisp.plugins.test_harness.serializers import (
            _STATE_NAMES,
        )
        assert _STATE_NAMES[CueState.Hibernating] == "Hibernating"

    def test_state_name_composite(self):
        from lisp.plugins.test_harness.serializers import state_name
        composite = CueState.Pause | CueState.Hibernating
        parts = state_name(composite).split("|")
        assert set(parts) == {"Pause", "Hibernating"}
