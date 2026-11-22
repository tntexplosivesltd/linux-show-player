"""H36: an exception in a cue's ``__start__`` (or another ``__*__``
hook) must not be silent.

`Cue.start`/`stop`/`pause`/`interrupt` run on a worker thread. Before
the fix an exception unwound out of it to stderr: the cue stayed in
its old state, emitted nothing, and on stage GO simply did nothing.
Now the exception is logged and the cue goes to Error, emitting
`error`, so the layout and the notifications show it.

The decorated methods are called through ``__wrapped__`` so they run
synchronously on the test thread.
"""

import logging
import threading

import pytest

from lisp.cues.cue import Cue, CueState
from tests.cues.test_media_cue_fadein_rebuild import _cue as _media_cue


class Boom(Exception):
    pass


class _FailingCue(Cue):
    """A cue whose hooks raise while ``fail`` names them."""

    def __init__(self, app):
        super().__init__(app=app)
        self.fail = set()

    def _hook(self, name, result=True):
        if name in self.fail:
            raise Boom(name)
        return result

    def __start__(self, fade=False):
        return self._hook("start")

    def __stop__(self, fade=False):
        return self._hook("stop")

    def __pause__(self, fade=False):
        return self._hook("pause")

    def __interrupt__(self, fade=False):
        self._hook("interrupt")


def _run(method, cue, fade=False):
    method.__wrapped__(cue, fade)


class _Recorder:
    """Named handlers: LiSP signals hold weak references."""

    def __init__(self, cue):
        self.events = []
        for name in (
            "started", "stopped", "paused", "interrupted",
            "error", "end", "awoken",
        ):
            handler = self._make(name)
            setattr(self, f"_on_{name}", handler)
            getattr(cue, name).connect(handler)

    def _make(self, name):
        def handler(*_):
            self.events.append(name)
        return handler


def _lock_free(cue):
    if cue._st_lock.acquire(blocking=False):
        cue._st_lock.release()
        return True
    return False


@pytest.fixture
def cue(mock_app):
    return _FailingCue(mock_app)


class TestStartException:
    def test_goes_to_error_and_emits_error(self, cue):
        cue.fail = {"start"}
        rec = _Recorder(cue)

        _run(Cue.start, cue)

        assert cue.state == CueState.Error
        assert rec.events == ["error"]
        assert _lock_free(cue)

    def test_is_logged_with_the_traceback(self, cue, caplog):
        cue.fail = {"start"}
        cue.name = "Song 1"

        with caplog.at_level(logging.ERROR, logger="lisp.cues.cue"):
            _run(Cue.start, cue)

        records = [r for r in caplog.records if r.exc_info]
        assert records, caplog.text
        assert "Song 1" in records[0].getMessage()
        assert records[0].exc_info[0] is Boom

    def test_resume_of_a_hibernated_cue_clears_the_bit(self, cue):
        cue._state = CueState.Pause | CueState.Hibernating
        cue.fail = {"start"}
        rec = _Recorder(cue)

        _run(Cue.start, cue)

        assert cue.state == CueState.Error
        assert rec.events == ["error", "awoken"]

    def test_can_start_again_once_the_fault_is_gone(self, cue):
        cue.fail = {"start"}
        _run(Cue.start, cue)

        cue.fail = set()
        rec = _Recorder(cue)
        _run(Cue.start, cue)

        assert cue.state == CueState.Running
        assert rec.events == ["started"]

    def test_from_the_real_worker_thread(self, cue):
        # The path GO takes: the async start on its own thread.
        cue.fail = {"start"}
        done = threading.Event()

        def on_error(_):
            done.set()

        cue.error.connect(on_error)
        cue.start()

        assert done.wait(2)
        assert cue.state == CueState.Error


class TestOtherHookExceptions:
    @pytest.mark.parametrize(
        "method, hook",
        [(Cue.stop, "stop"), (Cue.pause, "pause"),
         (Cue.interrupt, "interrupt")],
    )
    def test_goes_to_error(self, cue, caplog, method, hook):
        cue._state = CueState.Running
        cue.fail = {hook}
        rec = _Recorder(cue)

        with caplog.at_level(logging.ERROR, logger="lisp.cues.cue"):
            _run(method, cue)

        assert cue.state == CueState.Error
        assert rec.events == ["error"]
        assert _lock_free(cue)
        assert any(r.exc_info for r in caplog.records)

    def test_stop_of_a_paused_cue(self, cue):
        cue._state = CueState.Pause
        cue.fail = {"stop"}

        _run(Cue.stop, cue)

        assert cue.state == CueState.Error
        assert _lock_free(cue)


class TestMediaCueFadeException:
    """MediaCue.__stop__/__pause__ release `_st_lock` for the fade and
    take it back afterwards. If the fade raises, the lock must still be
    taken back: Cue.stop's ``finally`` releases it, and releasing a
    lock this thread doesn't hold raises (or frees another thread's).
    """

    @pytest.mark.parametrize("method", [Cue.stop, Cue.pause])
    def test_fade_raising_goes_to_error_and_frees_the_lock(
        self, mock_app, method, monkeypatch
    ):
        cue, _media = _media_cue(mock_app, rebuild_on_play=False)
        cue.fadeout_duration = 1.0
        cue._state = CueState.Running

        def fadeout(*_args, **_kwargs):
            raise Boom("fade")

        monkeypatch.setattr(cue, "_MediaCue__fadeout", fadeout)
        rec = _Recorder(cue)

        method.__wrapped__(cue, True)

        assert cue.state == CueState.Error
        assert rec.events == ["error"]
        assert _lock_free(cue)
