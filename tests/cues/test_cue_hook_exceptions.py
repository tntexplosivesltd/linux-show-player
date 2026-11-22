"""H36: an exception in a cue's ``__start__`` (or another ``__*__``
hook) must not be silent.

`Cue.start`/`stop`/`pause`/`interrupt` run on a worker thread. Before
the fix an exception unwound out of it to stderr: the cue stayed in
its old state, emitted nothing, and on stage GO simply did nothing.
Now the exception is logged, whatever the hook left playing is
silenced (a failed stop must still stop: an Error cue is not Running
or Paused, so nothing could stop it later), and the cue goes to Error,
emitting `error`, so the layout and the notifications show it.

The decorated methods are called through ``__wrapped__`` so they run
synchronously on the test thread, except where the worker thread is
the point.
"""

import logging
import threading
import time
from unittest.mock import MagicMock

import pytest

from lisp.cues.cue import Cue, CueAction, CueNextAction, CueState
from lisp.plugins.action_cues.group_cue import GroupCue
from tests.cues.media_fakes import make_media_cue
from tests.cues.test_group_cue import _make_child

TIMEOUT_MS = 3000


class Boom(Exception):
    pass


class _FailingCue(Cue):
    """A cue whose hooks raise while ``fail`` names them, and that
    records every hook call as ``(name, fade)``."""

    CueActions = (
        CueAction.Start,
        CueAction.Stop,
        CueAction.Pause,
        CueAction.Resume,
        CueAction.Interrupt,
    )

    def __init__(self, app):
        super().__init__(app=app)
        self.fail = set()
        self.calls = []

    def _hook(self, name, fade, result=True):
        self.calls.append((name, fade))
        if name in self.fail:
            raise Boom(name)
        return result

    def __start__(self, fade=False):
        return self._hook("start", fade)

    def __stop__(self, fade=False):
        return self._hook("stop", fade)

    def __pause__(self, fade=False):
        return self._hook("pause", fade)

    def __interrupt__(self, fade=False):
        self._hook("interrupt", fade)


def _run(method, cue, fade=False):
    method.__wrapped__(cue, fade)


class _Recorder:
    """Named handlers: LiSP signals hold weak references."""

    NAMES = (
        "started", "stopped", "paused", "interrupted",
        "error", "end", "awoken", "next",
    )

    def __init__(self, cue):
        self.events = []
        for name in self.NAMES:
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


def _wait(predicate, timeout=2.0):
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() > deadline:
            return False
        time.sleep(0.005)
    return True


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

    def test_silences_what_the_hook_started(self, cue):
        cue.fail = {"start"}

        _run(Cue.start, cue)

        assert cue.calls == [("start", False), ("interrupt", False)]

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

    def test_after_a_pre_wait_skips_the_post_wait(self, cue):
        cue.pre_wait = 0.01
        cue.post_wait = 0
        cue.next_action = CueNextAction.TriggerAfterWait.value
        cue.fail = {"start"}
        rec = _Recorder(cue)

        _run(Cue.start, cue)

        assert cue.state == CueState.Error
        assert rec.events == ["error"]  # no `next`
        assert _lock_free(cue)

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
        # The worker releases the lock after emitting.
        assert _wait(lambda: _lock_free(cue))


_OTHER_HOOKS = [
    (Cue.stop, "stop"),
    (Cue.pause, "pause"),
    (Cue.interrupt, "interrupt"),
]


class TestOtherHookExceptions:
    @pytest.mark.parametrize("method, hook", _OTHER_HOOKS)
    def test_goes_to_error_and_silences(self, cue, caplog, method, hook):
        cue._state = CueState.Running
        cue.fail = {hook}
        rec = _Recorder(cue)

        with caplog.at_level(logging.ERROR, logger="lisp.cues.cue"):
            _run(method, cue)

        assert cue.state == CueState.Error
        assert rec.events == ["error"]
        assert _lock_free(cue)
        assert any(r.exc_info for r in caplog.records)
        # The clean-up interrupt ran (for a failing interrupt it
        # raises again: logged, the cue still goes to Error).
        assert cue.calls[-1] == ("interrupt", False)

    @pytest.mark.parametrize(
        "method, hook", [(Cue.stop, "stop"), (Cue.interrupt, "interrupt")]
    )
    def test_hibernated_cue_clears_the_bit(self, cue, method, hook):
        cue._state = CueState.Pause | CueState.Hibernating
        cue.fail = {hook}
        rec = _Recorder(cue)

        _run(method, cue)

        assert cue.state == CueState.Error
        assert rec.events == ["error", "awoken"]

    def test_stop_during_post_wait(self, cue):
        cue._state = CueState.Running | CueState.PostWait
        cue._postwait = MagicMock()
        cue.fail = {"stop"}

        _run(Cue.stop, cue)

        cue._postwait.stop.assert_called_once()
        assert cue.state == CueState.Error

    def test_can_start_again_after_a_failed_stop(self, cue):
        cue._state = CueState.Running
        cue.fail = {"stop"}
        _run(Cue.stop, cue)

        cue.fail = set()
        _run(Cue.start, cue)

        assert cue.state == CueState.Running

    def test_settled_by_another_thread_in_the_fade_window(self, cue):
        # A stop hook releases the lock for its fade; an interrupt (or
        # a media error) settles the cue meanwhile and emits its own
        # signal. The failing stop must not overwrite that.
        def stop_hook(fade=False):
            cue._state = CueState.Stop  # what the interrupt left
            raise Boom("stop")

        cue._state = CueState.Running
        cue.__stop__ = stop_hook
        rec = _Recorder(cue)

        _run(Cue.stop, cue)

        assert cue.state == CueState.Stop
        assert rec.events == []
        assert ("interrupt", False) not in cue.calls
        assert _lock_free(cue)


class TestMediaCueFadeException:
    """MediaCue.__stop__/__pause__ release `_st_lock` for the fade and
    take it back afterwards. If the fade raises, the lock must still be
    taken back (Cue.stop's ``finally`` releases it), and the media must
    still stop or pause: the cue goes quiet."""

    @pytest.fixture
    def failing(self, mock_app, monkeypatch):
        cue, media = make_media_cue(mock_app)
        cue.fadeout_duration = 1.0
        cue._state = CueState.Running
        fades = []

        def fadeout(*_args, **_kwargs):
            fades.append(True)
            raise Boom("fade")

        monkeypatch.setattr(cue, "_MediaCue__fadeout", fadeout)
        return cue, media, fades

    @pytest.mark.parametrize(
        "method, media_call", [(Cue.stop, "stop"), (Cue.pause, "pause")]
    )
    def test_still_goes_quiet_and_frees_the_lock(
        self, failing, method, media_call
    ):
        cue, media, fades = failing
        rec = _Recorder(cue)

        method.__wrapped__(cue, True)

        assert fades == [True]  # the fade branch really ran
        getattr(media, media_call).assert_called()
        assert cue.state == CueState.Error
        assert rec.events == ["error"]
        assert _lock_free(cue)

    def test_interrupt_fade_failing_still_stops(
        self, failing, monkeypatch
    ):
        cue, media, fades = failing
        monkeypatch.setattr(cue, "_interrupt_fade_duration", lambda: 1.0)

        Cue.interrupt.__wrapped__(cue, True)

        assert fades == [True]
        media.stop.assert_called()
        assert cue.state == CueState.Error

    def test_restarts_after_the_failure(self, failing):
        cue, media, _fades = failing
        Cue.stop.__wrapped__(cue, True)

        Cue.start.__wrapped__(cue, False)

        assert cue.state == CueState.Running
        assert media.played


class TestGroupStartFailingHalfWay:
    def test_started_children_are_silenced_and_released(
        self, mock_app, monkeypatch
    ):
        a, b = _make_child("a"), _make_child("b")
        mock_app.cue_model.get = {"a": a, "b": b}.get
        group = GroupCue(mock_app)
        group.children = ["a", "b"]
        group.group_mode = "parallel"
        start_parallel = group._start_parallel

        def half_way(children):
            start_parallel(children)
            a.state = b.state = CueState.Running
            raise Boom("half way")

        monkeypatch.setattr(group, "_start_parallel", half_way)

        Cue.start.__wrapped__(group, False)

        assert group.state == CueState.Error
        a.execute.assert_called_with(CueAction.Interrupt)
        b.execute.assert_called_with(CueAction.Interrupt)
        assert group._connected_children == set()


class TestFailingChildInARealGroup:
    """The new `error` reaches the group through its real, queued
    wiring: a parallel group stops waiting for the child (as for a
    media error), a playlist group ends (as for a manual stop)."""

    @pytest.fixture
    def make_group(self, mock_app):
        mock_app.exclusive_manager.is_start_blocked.return_value = False
        mock_app.video_exclusive_manager.is_start_blocked.return_value = (
            False
        )
        made = []

        def make(mode, count):
            group = GroupCue(app=mock_app)
            children = [_FailingCue(mock_app) for _ in range(count)]
            cues = {c.id: c for c in [group, *children]}
            mock_app.cue_model.get.side_effect = cues.get
            for child in children:
                child.group_id = group.id
            group.children = [c.id for c in children]
            group.group_mode = mode
            made.extend([group, *children])
            return group, children

        yield make

        for c in made:
            if c.state & (CueState.IsRunning | CueState.IsPaused):
                c.interrupt()

    def test_parallel_waits_for_the_others(self, make_group, qtbot):
        group, (a, b) = make_group("parallel", 2)
        b.fail = {"start"}

        group.execute(CueAction.Start)
        qtbot.waitUntil(lambda: group.state == CueState.Running,
                        timeout=TIMEOUT_MS)
        qtbot.waitUntil(lambda: a.state == CueState.Running,
                        timeout=TIMEOUT_MS)
        qtbot.waitUntil(lambda: b.state == CueState.Error,
                        timeout=TIMEOUT_MS)
        qtbot.wait(50)
        assert group.state == CueState.Running

        a._ended()

        qtbot.waitUntil(lambda: group.state == CueState.Stop,
                        timeout=TIMEOUT_MS)

    def test_playlist_ends(self, make_group, qtbot):
        group, (a, b) = make_group("playlist", 2)

        group.execute(CueAction.Start)
        qtbot.waitUntil(lambda: group.state == CueState.Running,
                        timeout=TIMEOUT_MS)
        qtbot.waitUntil(lambda: a.state == CueState.Running,
                        timeout=TIMEOUT_MS)
        b.fail = {"start"}

        a._ended()

        qtbot.waitUntil(lambda: b.state == CueState.Error,
                        timeout=TIMEOUT_MS)
        qtbot.waitUntil(lambda: group.state == CueState.Stop,
                        timeout=TIMEOUT_MS)
