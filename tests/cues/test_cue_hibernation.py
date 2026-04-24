"""Tests for Cue hibernation primitives (bit + signals + set helper)."""
from lisp.cues.cue import Cue, CueState


class TestSignalsExist:
    def test_hibernated_signal_present(self, mock_app):
        cue = Cue(app=mock_app)
        assert hasattr(cue, "hibernated")

        def _noop(*_):
            pass
        cue.hibernated.connect(_noop)

    def test_awoken_signal_present(self, mock_app):
        cue = Cue(app=mock_app)
        assert hasattr(cue, "awoken")

        def _noop(*_):
            pass
        cue.awoken.connect(_noop)


class TestSetHibernated:
    def test_set_true_from_pause_flips_bit(self, mock_app):
        cue = Cue(app=mock_app)
        cue._state = CueState.Pause

        cue._set_hibernated(True)

        assert cue._state & CueState.Hibernating
        assert cue._state & CueState.Pause

    def test_set_true_emits_hibernated_once(self, mock_app):
        cue = Cue(app=mock_app)
        cue._state = CueState.Pause

        calls = []

        def on_hib(c):
            calls.append(c)

        cue.hibernated.connect(on_hib)

        cue._set_hibernated(True)

        assert calls == [cue]

    def test_set_true_twice_emits_once(self, mock_app):
        cue = Cue(app=mock_app)
        cue._state = CueState.Pause

        calls = []

        def on_hib(c):
            calls.append(c)

        cue.hibernated.connect(on_hib)

        cue._set_hibernated(True)
        cue._set_hibernated(True)

        assert calls == [cue]

    def test_set_false_clears_bit(self, mock_app):
        cue = Cue(app=mock_app)
        cue._state = CueState.Pause | CueState.Hibernating

        cue._set_hibernated(False)

        assert not (cue._state & CueState.Hibernating)
        assert cue._state & CueState.Pause

    def test_set_false_emits_awoken_once(self, mock_app):
        cue = Cue(app=mock_app)
        cue._state = CueState.Pause | CueState.Hibernating

        calls = []

        def on_awake(c):
            calls.append(c)

        cue.awoken.connect(on_awake)

        cue._set_hibernated(False)

        assert calls == [cue]

    def test_set_false_when_not_hibernating_is_noop(self, mock_app):
        cue = Cue(app=mock_app)
        cue._state = CueState.Pause

        calls = []

        def on_awake(c):
            calls.append(c)

        cue.awoken.connect(on_awake)

        cue._set_hibernated(False)

        assert calls == []
        assert cue._state == CueState.Pause
