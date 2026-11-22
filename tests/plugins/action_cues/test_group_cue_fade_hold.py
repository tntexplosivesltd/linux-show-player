"""M78: a Fade & Stop (any action, Hibernate included) fading a
playlist group must not let the group start a new child mid-fade.

The StopCue fades the faders of the cues playing when it fires. A
crossfade (or a natural advance) during that fade brought in a child
outside that set: it faded in to full and was cut hard by the pause,
and the outgoing child's own crossfade fade took its volume back from
the StopCue's (measured in Docker: both audible at the pause).

While held (one token per StopCue), the group starts nothing: no
crossfade, and a natural end is recorded instead of advancing. The
StopCue releases its token once its action has landed, or at once on
an abort; the catch-up then runs on the main thread, if the group is
still playing. A resume after the pause runs the held advance, faded
in by Fade & Resume.
"""

import threading
from unittest.mock import MagicMock

import pytest

from lisp.cues.cue import CueAction, CueState
from lisp.plugins.action_cues.group_cue import GroupCue
from tests.cues.test_group_cue import _make_child

_FADE_CAPABLE = (
    CueAction.Start,
    CueAction.FadeInStart,
    CueAction.Resume,
    CueAction.FadeInResume,
)


@pytest.fixture
def mock_app():
    app = MagicMock()
    app.conf.get = MagicMock(return_value=0)
    return app


@pytest.fixture
def settle(qapp):
    """Deliver queued (main-thread) slots: the release catch-up."""
    return qapp.processEvents


def _playlist(mock_app, n=3, crossfade=1.0, loop=False):
    group = GroupCue(mock_app)
    kids = [_make_child(f"c{i}") for i in range(1, n + 1)]
    for kid in kids:
        kid.CueActions = _FADE_CAPABLE
    by_id = {k.id: k for k in kids}
    mock_app.cue_model.get = by_id.get
    group.children = list(by_id)
    group.group_mode = "playlist"
    group.crossfade = crossfade
    group.loop = loop
    return group, kids


def _playing(group, kids, index, near_end=False):
    """The group Running with ``kids[index]`` its current child."""
    kid = kids[index]
    kid.state = CueState.Running
    if near_end:
        kid.current_time = MagicMock(return_value=kid.duration - 500)
    group._state = CueState.Running
    group._playlist_index = index
    group._connected_children = {kid.id}
    group._crossfade_armed = True


def _end(group, kid):
    kid.state = CueState.Stop
    group._on_playlist_child_ended(kid)


class _Ends:
    def __init__(self, group):
        self.count = 0
        group.end.connect(self.on_end)

    def on_end(self, *_):
        self.count += 1


class TestCrossfadeHeld:
    def test_no_crossfade_while_held(self, mock_app):
        group, kids = _playlist(mock_app)
        _playing(group, kids, 0, near_end=True)

        group.hold_transitions("s1")
        # A crossfade arm still queued from the child's start lands
        # after the hold.
        group._crossfade_armed = True
        group._check_crossfade()

        kids[0].execute.assert_not_called()
        kids[1].execute.assert_not_called()

    def test_release_rearms_the_crossfade(self, mock_app, settle):
        group, (c1, c2, c3) = _playlist(mock_app)
        _playing(group, [c1, c2, c3], 0, near_end=True)

        group.hold_transitions("s1")
        group.release_transitions("s1")
        settle()
        group._check_crossfade()

        c2.execute.assert_called_once_with(CueAction.FadeInStart)
        c1.execute.assert_called_once_with(CueAction.FadeOutStop)

    def test_held_until_every_owner_releases(self, mock_app, settle):
        group, (c1, c2, c3) = _playlist(mock_app)
        _playing(group, [c1, c2, c3], 0, near_end=True)

        group.hold_transitions("s1")
        group.hold_transitions("s2")
        group.release_transitions("s1")
        group.release_transitions("s1")  # twice: still one owner left
        settle()
        group._crossfade_armed = True
        group._check_crossfade()
        c2.execute.assert_not_called()

        group.release_transitions("s2")
        settle()
        group._check_crossfade()
        c2.execute.assert_called_once_with(CueAction.FadeInStart)

    def test_stale_release_after_a_restart_keeps_the_new_hold(
        self, mock_app, settle
    ):
        group, kids = _playlist(mock_app)
        c1, c2, _ = kids
        group.hold_transitions("s1")

        # The group is stopped and started again: s1's hold is gone.
        group.__start__()
        _playing(group, kids, 0, near_end=True)
        c1.execute.reset_mock()
        group.hold_transitions("s2")

        group.release_transitions("s1")  # s1's fade aborted late
        settle()
        group._crossfade_armed = True
        group._check_crossfade()

        c2.execute.assert_not_called()

    def test_parallel_group_is_never_held_or_crossfaded(
        self, mock_app, settle
    ):
        group, kids = _playlist(mock_app)
        group.group_mode = "parallel"  # crossfade 1.0 left over
        group._state = CueState.Running
        kids[0].state = CueState.Running

        group.hold_transitions("s1")
        assert group._fade_holders == set()
        group.release_transitions("s1")
        settle()
        group._arm_crossfade_if_needed(0, kids)

        assert group._crossfade_armed is False


class TestNaturalEndHeld:
    def test_next_child_not_started(self, mock_app):
        group, kids = _playlist(mock_app, crossfade=0.0)
        _playing(group, kids, 0)
        ends = _Ends(group)

        group.hold_transitions("s1")
        _end(group, kids[0])

        kids[1].execute.assert_not_called()
        assert ends.count == 0
        assert group.state & CueState.Running

    def test_release_starts_the_held_next(self, mock_app, settle):
        group, kids = _playlist(mock_app, crossfade=0.0)
        _playing(group, kids, 0)

        group.hold_transitions("s1")
        _end(group, kids[0])
        group.release_transitions("s1")
        kids[1].execute.assert_not_called()  # queued to the main thread
        settle()

        kids[1].execute.assert_called_once_with(CueAction.Start)
        assert group._playlist_index == 1

    def test_release_wraps_when_looping(self, mock_app, settle):
        group, kids = _playlist(mock_app, crossfade=0.0, loop=True)
        _playing(group, kids, 2)

        group.hold_transitions("s1")
        _end(group, kids[2])
        group.release_transitions("s1")
        settle()

        kids[0].execute.assert_called_once_with(CueAction.Start)
        assert group._playlist_index == 0

    def test_release_walks_past_a_child_removed_meanwhile(
        self, mock_app, settle
    ):
        group, kids = _playlist(mock_app, crossfade=0.0)
        _playing(group, kids, 0)

        group.hold_transitions("s1")
        _end(group, kids[0])
        group.children = ["c1", "c3"]  # c2 removed from the group
        group.release_transitions("s1")
        settle()

        kids[2].execute.assert_called_once_with(CueAction.Start)

    def test_release_walks_past_a_child_disabled_meanwhile(
        self, mock_app, settle
    ):
        group, kids = _playlist(mock_app, crossfade=0.0)
        _playing(group, kids, 0)

        group.hold_transitions("s1")
        _end(group, kids[0])
        kids[1].effective_disabled = True
        group.release_transitions("s1")
        settle()

        kids[1].execute.assert_not_called()
        kids[2].execute.assert_called_once_with(CueAction.Start)

    def test_release_ends_the_group_when_nothing_can_start(
        self, mock_app, settle
    ):
        group, kids = _playlist(mock_app, crossfade=0.0)
        _playing(group, kids, 0)
        ends = _Ends(group)
        kids[1].execute.return_value = False  # refused
        kids[2].execute.return_value = False

        group.hold_transitions("s1")
        _end(group, kids[0])
        group.release_transitions("s1")
        settle()

        assert ends.count == 1

    def test_last_child_still_ends_the_group(self, mock_app):
        # Nothing to start, so nothing to hold: the group ends.
        group, kids = _playlist(mock_app, crossfade=0.0)
        _playing(group, kids, 2)
        ends = _Ends(group)

        group.hold_transitions("s1")
        _end(group, kids[2])

        assert ends.count == 1
        assert group.state & CueState.Stop


class TestResumeAfterTheHold:
    def _hibernate(self, group, kids, index):
        """Hold, end the current child, pause: what a Hibernate whose
        fade outlasts the current child leaves."""
        _playing(group, kids, index)
        group.hold_transitions("s1")
        _end(group, kids[index])
        group.__pause__()
        group._state = CueState.Pause

    def test_starts_the_held_next(self, mock_app):
        group, kids = _playlist(mock_app, crossfade=0.0)
        self._hibernate(group, kids, 0)

        group.__start__()

        kids[1].execute.assert_called_once_with(CueAction.Start)
        kids[0].execute.assert_not_called()
        assert group._playlist_index == 1

    def test_wraps_when_looping(self, mock_app):
        group, kids = _playlist(mock_app, crossfade=0.0, loop=True)
        self._hibernate(group, kids, 2)

        group.__start__()

        kids[0].execute.assert_called_once_with(CueAction.Start)
        assert group._playlist_index == 0

    def test_fade_and_resume_fades_the_held_child_in(self, mock_app):
        group, kids = _playlist(mock_app, crossfade=0.0)
        self._hibernate(group, kids, 0)
        seen = []
        kids[1].execute.side_effect = lambda action: seen.append(
            (action, kids[1].fadein_duration))

        group.fade_in_held_next(3.0)
        group.__start__()

        assert seen == [(CueAction.FadeInStart, 3.0)]

    def test_fade_in_ignored_without_a_held_child(self, mock_app):
        group, kids = _playlist(mock_app, crossfade=0.0)
        _playing(group, kids, 0)

        group.fade_in_held_next(3.0)

        assert group._held_fadein is None

    def test_a_paused_child_wins_over_the_held_one(self, mock_app):
        # Only a crossfade overlap leaves a child paused, and then no
        # end is held; if it ever happens, the song in progress wins.
        group, kids = _playlist(mock_app, crossfade=0.0)
        group._playlist_index = 1
        kids[1].state = CueState.Pause
        group._held_after_id = "c2"  # would start c3
        group._state = CueState.Pause

        group.__start__()

        kids[1].execute.assert_called_once_with(CueAction.Resume)
        kids[2].execute.assert_not_called()
        assert group._held_after_id is None

    def test_nothing_playable_forgets_the_held_child(self, mock_app):
        group, kids = _playlist(mock_app, crossfade=0.0)
        self._hibernate(group, kids, 0)
        for kid in kids:
            kid.effective_disabled = True

        assert group.__start__() is False
        assert group._held_after_id is None

    def test_start_drops_every_hold(self, mock_app):
        group, kids = _playlist(mock_app)
        group.hold_transitions("s1")
        group.hold_transitions("s2")

        group.__start__()

        assert group._fade_holders == set()


class TestGroupTransitions:
    def test_stop_forgets_the_held_child(self, mock_app, settle):
        group, kids = _playlist(mock_app, crossfade=0.0)
        _playing(group, kids, 0)
        group.hold_transitions("s1")
        _end(group, kids[0])

        group.__stop__()
        group._state = CueState.Stop
        group.release_transitions("s1")
        settle()

        assert group._held_after_id is None
        kids[1].execute.assert_not_called()

    def test_interrupt_forgets_the_held_child(self, mock_app):
        group, kids = _playlist(mock_app, crossfade=0.0)
        _playing(group, kids, 0)
        group.hold_transitions("s1")
        _end(group, kids[0])

        group.__interrupt__()

        assert group._held_after_id is None

    def test_the_hold_outlives_the_dunders(self, mock_app):
        # Dropping it in __stop__/__pause__, before Running clears,
        # would let a queued natural end start a child in between.
        group, kids = _playlist(mock_app, crossfade=0.0)
        _playing(group, kids, 0)
        group.hold_transitions("s1")

        group.__pause__()
        _end(group, kids[0])  # still Running: the pause hasn't landed

        kids[1].execute.assert_not_called()

    def test_release_after_the_pause_keeps_the_held_child(
        self, mock_app, settle
    ):
        group, kids = _playlist(mock_app, crossfade=0.0)
        _playing(group, kids, 0)
        group.hold_transitions("s1")
        _end(group, kids[0])
        group.__pause__()
        group._state = CueState.Pause

        group.release_transitions("s1")
        settle()

        kids[1].execute.assert_not_called()
        assert group._held_after_id == "c1"
        group.__start__()
        kids[1].execute.assert_called_once_with(CueAction.Start)

    def test_catch_up_rechecks_the_state_on_the_main_thread(
        self, mock_app, settle
    ):
        group, kids = _playlist(mock_app, crossfade=0.0)
        _playing(group, kids, 0)
        group.hold_transitions("s1")
        _end(group, kids[0])

        group.release_transitions("s1")
        group._state = CueState.Stop  # stopped before the slot ran
        settle()

        kids[1].execute.assert_not_called()

    def test_pause_without_a_held_end_resumes_the_paused_child(
        self, mock_app, settle
    ):
        group, kids = _playlist(mock_app)
        c1, c2, c3 = kids
        _playing(group, kids, 1)

        group.hold_transitions("s1")
        group.__pause__()
        c2.execute.assert_called_once_with(CueAction.Pause)
        c2.state = CueState.Pause
        group._state = CueState.Pause
        c2.execute.reset_mock()
        group.release_transitions("s1")
        settle()

        group.__start__()

        c2.execute.assert_called_once_with(CueAction.Resume)
        _playing(group, kids, 1, near_end=True)
        group._check_crossfade()
        c3.execute.assert_called_once_with(CueAction.FadeInStart)


# ── StopCue wiring ──────────────────────────────────────────────


class _SyncThread:
    """Run @async_function bodies inline."""

    def __init__(self, target=None, args=(), kwargs=None, daemon=False,
                 name=None):
        self._target = target
        self._args = args
        self._kwargs = kwargs or {}

    def start(self):
        self._target(*self._args, **self._kwargs)


@pytest.fixture
def stop_cue_env(mock_app, monkeypatch):
    """A StopCue targeting group g, which holds a nested group n.
    Records the order of hold/collect/release calls."""
    from lisp.plugins.action_cues import stop_cue as sc

    monkeypatch.setattr("lisp.core.decorators.Thread", _SyncThread)
    monkeypatch.setattr(sc.StopCue, "SETTLE_TIMEOUT", 0.05)
    calls = []

    outer = GroupCue(mock_app, id="g")
    inner = GroupCue(mock_app, id="n")
    inner.group_id = "g"
    outer.children = ["n"]
    inner.children = []
    by_id = {"g": outer, "n": inner}
    mock_app.cue_model.get = by_id.get
    mock_app.cue_model.__iter__ = lambda self=None: iter(by_id.values())
    outer.execute = MagicMock()

    for g in (outer, inner):
        monkeypatch.setattr(
            g, "hold_transitions",
            lambda owner, g=g: calls.append(("hold", g.id, owner)))
        monkeypatch.setattr(
            g, "release_transitions",
            lambda owner, g=g: calls.append(("release", g.id, owner)))

    runner = MagicMock()
    runner.run_until_complete.return_value = True

    def collect(cues, *a, **kw):
        calls.append(("collect",))
        return [MagicMock()]

    monkeypatch.setattr(sc, "collect_live_faders", collect)
    monkeypatch.setattr(
        sc, "ParallelFadeRunner", MagicMock(return_value=runner))

    cue = sc.StopCue(app=mock_app)
    cue.target_id = "g"
    cue.duration = 1000
    cue.action = "Hibernate"
    return cue, outer, runner, calls


def _released(calls):
    return sorted(c[:2] for c in calls if c[0] == "release")


class TestStopCueHoldsTheGroups:
    def test_holds_every_group_before_collecting_faders(
        self, stop_cue_env
    ):
        cue, outer, _runner, calls = stop_cue_env

        cue.__start__()

        assert calls[:3] == [
            ("hold", "g", cue.id), ("hold", "n", cue.id), ("collect",),
        ]
        outer.execute.assert_called_once_with(CueAction.Pause)

    def test_completion_releases_once_the_groups_left_running(
        self, stop_cue_env
    ):
        cue, outer, _runner, calls = stop_cue_env
        order = []
        outer.execute.side_effect = lambda a: order.append("dispatch")

        def on_end(*_):
            order.append("end")

        cue.end.connect(on_end)

        cue.__start__()

        assert order == ["dispatch", "end"]
        assert _released(calls) == [("release", "g"), ("release", "n")]

    def test_completion_releases_a_group_that_kept_running(
        self, stop_cue_env
    ):
        # The action never reached the group (its state lock was
        # busy, say): after SETTLE_TIMEOUT it is released anyway, so
        # it doesn't stay held, silent, forever.
        cue, outer, _runner, calls = stop_cue_env
        outer._state = CueState.Running

        cue.__start__()

        assert _released(calls) == [("release", "g"), ("release", "n")]

    def test_abort_releases_every_group(self, stop_cue_env):
        cue, outer, runner, calls = stop_cue_env
        runner.run_until_complete.return_value = False

        cue.__start__()

        assert _released(calls) == [("release", "g"), ("release", "n")]
        outer.execute.assert_not_called()

    def test_runner_error_releases_every_group(self, stop_cue_env):
        cue, _outer, runner, calls = stop_cue_env
        runner.run_until_complete.side_effect = RuntimeError("boom")

        cue.__start__()

        assert _released(calls) == [("release", "g"), ("release", "n")]

    def test_error_before_the_fade_starts_releases(
        self, stop_cue_env, monkeypatch
    ):
        from lisp.plugins.action_cues import stop_cue as sc

        cue, outer, _runner, calls = stop_cue_env

        def collect(cues, *a, **kw):
            raise RuntimeError("element gone")

        monkeypatch.setattr(sc, "collect_live_faders", collect)

        assert cue.__start__() is False
        assert _released(calls) == [("release", "g"), ("release", "n")]
        assert cue.state & CueState.Error
        outer.execute.assert_not_called()

    def test_bad_fade_type_holds_nothing(self, stop_cue_env):
        cue, outer, _runner, calls = stop_cue_env
        cue.fade_type = "NoSuchCurve"

        assert cue.__start__() is False
        assert calls == []
        assert cue.state & CueState.Error

    def test_no_faders_releases_at_once(self, stop_cue_env, monkeypatch):
        from lisp.plugins.action_cues import stop_cue as sc

        cue, outer, _runner, calls = stop_cue_env

        def collect(cues, *a, **kw):
            calls.append(("collect",))
            return []

        monkeypatch.setattr(sc, "collect_live_faders", collect)

        cue.__start__()

        assert _released(calls) == [("release", "g"), ("release", "n")]
        outer.execute.assert_called_once_with(CueAction.Pause)

    def test_instant_path_holds_nothing(self, stop_cue_env):
        cue, outer, _runner, calls = stop_cue_env
        cue.duration = 0

        cue.__start__()

        assert calls == [("collect",)]
        outer.execute.assert_called_once_with(CueAction.Pause)


class TestResumeCueFadesTheHeldChildIn:
    def test_tells_the_groups_before_resuming(self, mock_app):
        from lisp.plugins.action_cues.resume_cue import ResumeCue

        group, kids = _playlist(mock_app, crossfade=0.0)
        mock_app.cue_model.get = {
            group.id: group, **{k.id: k for k in kids}}.get
        group._state = CueState.Pause
        group._held_after_id = "c1"
        order = []
        group.execute = lambda action: order.append(
            (action, group._held_fadein))

        cue = ResumeCue(app=mock_app)
        cue.target_id = group.id
        cue.duration = 3000
        cue.__start__()

        assert order == [(CueAction.Resume, 3.0)]


# ── A real StopCue on a real playlist group ─────────────────────


class _GatedRunner:
    """A fade that runs until the test completes or aborts it."""

    def __init__(self, *args, **kwargs):
        self.done = threading.Event()
        self.completed = True

    def run_until_complete(self):
        self.done.wait(5)
        return self.completed

    def abort(self):
        self.completed = False
        self.done.set()

    def current_time(self):
        return 0


@pytest.fixture
def real_env(mock_app, monkeypatch):
    from lisp.plugins.action_cues import stop_cue as sc

    runners = []

    def make_runner(*args, **kwargs):
        runner = _GatedRunner()
        runners.append(runner)
        return runner

    monkeypatch.setattr(sc, "ParallelFadeRunner", make_runner)
    monkeypatch.setattr(
        sc, "collect_live_faders", lambda *a, **kw: [MagicMock()])
    mock_app.exclusive_manager.is_start_blocked.return_value = False
    mock_app.video_exclusive_manager.is_start_blocked.return_value = False

    group, kids = _playlist(mock_app, crossfade=0.0)
    by_id = {group.id: group, **{k.id: k for k in kids}}
    mock_app.cue_model.get = by_id.get
    mock_app.cue_model.__iter__ = lambda self=None: iter(by_id.values())
    _playing(group, kids, 0)

    cue = sc.StopCue(app=mock_app)
    cue.target_id = group.id
    cue.duration = 2000
    cue.action = CueAction.Pause.value
    return cue, group, kids, runners


class TestRealStopCueOnARealGroup:
    def test_natural_end_mid_fade_waits_and_abort_catches_up(
        self, real_env, qtbot
    ):
        cue, group, kids, runners = real_env

        assert cue.__start__() is True
        _end(group, kids[0])  # A ends while the fade runs
        qtbot.wait(50)
        kids[1].execute.assert_not_called()

        runners[0].abort()  # the operator stops the Fade & Stop

        qtbot.waitUntil(
            lambda: kids[1].execute.call_args_list
            == [((CueAction.Start,),)],
            timeout=3000,
        )
        assert group.state & CueState.Running

    def test_completed_fade_pauses_and_resume_starts_the_held(
        self, real_env, qtbot
    ):
        cue, group, kids, runners = real_env

        cue.__start__()
        _end(group, kids[0])
        runners[0].done.set()  # the fade completes: Pause dispatched

        qtbot.waitUntil(lambda: group.state == CueState.Pause,
                        timeout=3000)
        qtbot.waitUntil(lambda: group._fade_holders == set(),
                        timeout=3000)
        qtbot.wait(50)
        kids[1].execute.assert_not_called()

        group.execute(CueAction.Resume)

        qtbot.waitUntil(
            lambda: kids[1].execute.call_args_list
            == [((CueAction.Start,),)],
            timeout=3000,
        )
