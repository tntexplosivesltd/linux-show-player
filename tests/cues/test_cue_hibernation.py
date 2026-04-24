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

    def test_set_true_on_stopped_cue_is_noop(self, mock_app):
        """Guard against setting Hibernating on a non-Paused cue —
        Stop|Hibernating has no auto-clear path and would leak."""
        cue = Cue(app=mock_app)
        cue._state = CueState.Stop

        calls = []

        def on_hib(c):
            calls.append(c)
        cue.hibernated.connect(on_hib)

        cue._set_hibernated(True)

        assert calls == []
        assert cue._state == CueState.Stop

    def test_set_true_on_running_cue_is_noop(self, mock_app):
        cue = Cue(app=mock_app)
        cue._state = CueState.Running

        cue._set_hibernated(True)

        assert not (cue._state & CueState.Hibernating)
        assert cue._state == CueState.Running


class TestAutoClearOnTransitions:
    """Base class must clear the Hibernating bit on any pause-exit
    transition. Any resume path then de-hibernates for free."""

    def _make_cue(self, mock_app):
        cue = Cue(app=mock_app)
        cue._state = CueState.Pause | CueState.Hibernating
        return cue

    def test_start_from_pause_clears_bit_and_emits_awoken(
        self, mock_app,
    ):
        import threading
        cue = self._make_cue(mock_app)

        awoken_calls = []

        def on_awake(c):
            awoken_calls.append(c)
        cue.awoken.connect(on_awake)

        done = threading.Event()

        def on_started(c):
            done.set()
        cue.started.connect(on_started)

        cue.resume()
        done.wait(timeout=2.0)
        # Tiny grace — awoken fires right after started on same thread.
        import time
        time.sleep(0.02)

        assert not (cue._state & CueState.Hibernating)
        assert awoken_calls == [cue]

    def test_stop_from_pause_clears_bit(self, mock_app):
        import threading
        import time
        cue = self._make_cue(mock_app)
        # Base Cue.__stop__ returns False (= interrupted), which
        # would short-circuit stop() before the state mutation.
        # Patch it to return True so the full transition runs.
        cue.__stop__ = lambda *_a, **_k: True

        awoken_calls = []

        def on_awake(c):
            awoken_calls.append(c)
        cue.awoken.connect(on_awake)

        done = threading.Event()

        def on_stopped(c):
            done.set()
        cue.stopped.connect(on_stopped)

        cue.stop()
        done.wait(timeout=2.0)
        time.sleep(0.02)

        assert not (cue._state & CueState.Hibernating)
        assert awoken_calls == [cue]

    def test_interrupt_from_pause_clears_bit(self, mock_app):
        import threading
        import time
        cue = self._make_cue(mock_app)

        awoken_calls = []

        def on_awake(c):
            awoken_calls.append(c)
        cue.awoken.connect(on_awake)

        done = threading.Event()

        def on_interrupted(c):
            done.set()
        cue.interrupted.connect(on_interrupted)

        cue.interrupt()
        done.wait(timeout=2.0)
        time.sleep(0.02)

        assert not (cue._state & CueState.Hibernating)
        assert awoken_calls == [cue]

    def test_error_clears_bit(self, mock_app):
        cue = self._make_cue(mock_app)

        awoken_calls = []

        def on_awake(c):
            awoken_calls.append(c)
        cue.awoken.connect(on_awake)

        error_calls = []

        def on_error(c):
            error_calls.append(c)
        cue.error.connect(on_error)

        cue._error()

        assert not (cue._state & CueState.Hibernating)
        assert awoken_calls == [cue]
        assert error_calls == [cue]

    def test_multiple_transitions_emit_awoken_once(self, mock_app):
        import threading
        import time
        cue = self._make_cue(mock_app)
        cue.__stop__ = lambda *_a, **_k: True

        awoken_calls = []

        def on_awake(c):
            awoken_calls.append(c)
        cue.awoken.connect(on_awake)

        cue._set_hibernated(False)

        done = threading.Event()

        def on_stopped(c):
            done.set()
        cue.stopped.connect(on_stopped)

        cue.stop()
        done.wait(timeout=2.0)
        time.sleep(0.02)

        assert awoken_calls == [cue]
