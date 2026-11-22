"""M78: a Fade & Stop (any action, Hibernate included) fading a
playlist group must not let the group start a new child mid-fade.

The StopCue fades the faders of the cues playing when it fires. A
crossfade (or a natural advance) during that fade brought in a child
outside that set: it faded in to full and was cut hard by the pause,
and the outgoing child's own crossfade fade took its volume back from
the StopCue's (measured in Docker: both audible at the pause).

While held, the group starts nothing: no crossfade, and a natural end
records the next child instead of starting it. The group's own
pause/stop/interrupt ends the hold; an aborted fade releases it (and
runs what was held); a resume starts the held next child.
"""

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


class _Ends:
    def __init__(self, group):
        self.count = 0
        group.end.connect(self.on_end)

    def on_end(self, *_):
        self.count += 1


class TestCrossfadeHeld:
    def test_no_crossfade_while_held(self, mock_app):
        group, (c1, c2, _c3) = _playlist(mock_app)
        _playing(group, [c1, c2, _c3], 0, near_end=True)

        group.hold_transitions()
        # A crossfade arm still queued from the child's start lands
        # after the hold.
        group._crossfade_armed = True
        group._check_crossfade()

        c1.execute.assert_not_called()
        c2.execute.assert_not_called()

    def test_release_rearms_the_crossfade(self, mock_app):
        group, (c1, c2, c3) = _playlist(mock_app)
        _playing(group, [c1, c2, c3], 0, near_end=True)

        group.hold_transitions()
        group.release_transitions()
        group._check_crossfade()

        c2.execute.assert_called_once_with(CueAction.FadeInStart)
        c1.execute.assert_called_once_with(CueAction.FadeOutStop)

    def test_holds_nest(self, mock_app):
        group, (c1, c2, c3) = _playlist(mock_app)
        _playing(group, [c1, c2, c3], 0, near_end=True)

        group.hold_transitions()
        group.hold_transitions()
        group.release_transitions()
        group._check_crossfade()
        c2.execute.assert_not_called()

        group.release_transitions()
        group._check_crossfade()
        c2.execute.assert_called_once_with(CueAction.FadeInStart)


class TestNaturalEndHeld:
    def test_next_child_not_started(self, mock_app):
        group, kids = _playlist(mock_app, crossfade=0.0)
        c1, c2, _ = kids
        _playing(group, kids, 0)
        ends = _Ends(group)

        group.hold_transitions()
        c1.state = CueState.Stop
        group._on_playlist_child_ended(c1)

        c2.execute.assert_not_called()
        assert ends.count == 0
        assert group.state & CueState.Running

    def test_release_starts_the_held_next(self, mock_app):
        group, kids = _playlist(mock_app, crossfade=0.0)
        c1, c2, _ = kids
        _playing(group, kids, 0)

        group.hold_transitions()
        c1.state = CueState.Stop
        group._on_playlist_child_ended(c1)
        group.release_transitions()

        c2.execute.assert_called_once_with(CueAction.Start)
        assert group._playlist_index == 1

    def test_resume_after_the_pause_starts_the_held_next(self, mock_app):
        group, kids = _playlist(mock_app, crossfade=0.0)
        c1, c2, c3 = kids
        _playing(group, kids, 0)

        group.hold_transitions()
        c1.state = CueState.Stop
        group._on_playlist_child_ended(c1)
        group.__pause__()
        group._state = CueState.Pause
        group.__start__()

        c2.execute.assert_called_once_with(CueAction.Start)
        c1.execute.assert_not_called()
        assert group._playlist_index == 1

    def test_resume_after_the_pause_wraps_when_looping(self, mock_app):
        group, kids = _playlist(mock_app, crossfade=0.0, loop=True)
        c1, c2, c3 = kids
        _playing(group, kids, 2)

        group.hold_transitions()
        c3.state = CueState.Stop
        group._on_playlist_child_ended(c3)
        group.__pause__()
        group._state = CueState.Pause
        group.__start__()

        c1.execute.assert_called_once_with(CueAction.Start)
        assert group._playlist_index == 0

    def test_last_child_still_ends_the_group(self, mock_app):
        # Nothing to start, so nothing to hold: the group ends.
        group, kids = _playlist(mock_app, crossfade=0.0)
        c3 = kids[2]
        _playing(group, kids, 2)
        ends = _Ends(group)

        group.hold_transitions()
        c3.state = CueState.Stop
        group._on_playlist_child_ended(c3)

        assert ends.count == 1
        assert group.state & CueState.Stop


class TestGroupTransitionsEndTheHold:
    def test_stop_then_go_crossfades_again(self, mock_app):
        group, kids = _playlist(mock_app)
        c1, c2, c3 = kids
        _playing(group, kids, 0)

        group.hold_transitions()
        c1.state = CueState.Stop
        group._on_playlist_child_ended(c1)
        group.__stop__()

        # A fresh GO starts from the top, not the held child, and the
        # hold is gone.
        group._state = CueState.Stop
        group._playlist_index = 0
        group.__start__()
        c1.execute.assert_called_once_with(CueAction.Start)
        c2.execute.assert_not_called()

        _playing(group, kids, 0, near_end=True)
        group._check_crossfade()
        c2.execute.assert_called_once_with(CueAction.FadeInStart)

    def test_interrupt_ends_the_hold(self, mock_app):
        group, kids = _playlist(mock_app)
        c1, c2, c3 = kids
        _playing(group, kids, 0)

        group.hold_transitions()
        group.__interrupt__()

        _playing(group, kids, 0, near_end=True)
        group._check_crossfade()
        c2.execute.assert_called_once_with(CueAction.FadeInStart)

    def test_pause_without_a_held_end_resumes_the_paused_child(
        self, mock_app
    ):
        group, kids = _playlist(mock_app)
        c1, c2, c3 = kids
        _playing(group, kids, 1)

        group.hold_transitions()
        group.__pause__()
        c2.execute.assert_called_once_with(CueAction.Pause)
        c2.state = CueState.Pause
        group._state = CueState.Pause
        c2.execute.reset_mock()

        group.__start__()

        c2.execute.assert_called_once_with(CueAction.Resume)
        _playing(group, kids, 1, near_end=True)
        group._check_crossfade()
        c3.execute.assert_called_once_with(CueAction.FadeInStart)

    def test_release_after_the_group_stopped_does_nothing(self, mock_app):
        group, kids = _playlist(mock_app, crossfade=0.0)
        c1, c2, _ = kids
        _playing(group, kids, 0)

        group.hold_transitions()
        c1.state = CueState.Stop
        group._on_playlist_child_ended(c1)
        group._state = CueState.Stop
        group.release_transitions()

        c2.execute.assert_not_called()


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
            lambda g=g: calls.append(("hold", g.id)))
        monkeypatch.setattr(
            g, "release_transitions",
            lambda g=g: calls.append(("release", g.id)))

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


class TestStopCueHoldsTheGroups:
    def test_holds_every_group_before_collecting_faders(
        self, stop_cue_env
    ):
        cue, outer, _runner, calls = stop_cue_env

        cue.__start__()

        assert calls[:3] == [("hold", "g"), ("hold", "n"), ("collect",)]
        outer.execute.assert_called_once_with(CueAction.Pause)

    def test_completion_leaves_the_release_to_the_group(
        self, stop_cue_env
    ):
        # The dispatched Pause is async: releasing here would let a
        # held advance start a child just before the pause cuts it.
        cue, _outer, _runner, calls = stop_cue_env

        cue.__start__()

        assert not [c for c in calls if c[0] == "release"]

    def test_abort_releases_every_group(self, stop_cue_env):
        cue, outer, runner, calls = stop_cue_env
        runner.run_until_complete.return_value = False

        cue.__start__()

        released = [c for c in calls if c[0] == "release"]
        assert sorted(released) == [("release", "g"), ("release", "n")]
        outer.execute.assert_not_called()

    def test_runner_error_releases_every_group(self, stop_cue_env):
        cue, _outer, runner, calls = stop_cue_env
        runner.run_until_complete.side_effect = RuntimeError("boom")

        cue.__start__()

        released = [c for c in calls if c[0] == "release"]
        assert sorted(released) == [("release", "g"), ("release", "n")]

    def test_no_faders_releases_at_once(self, stop_cue_env, monkeypatch):
        from lisp.plugins.action_cues import stop_cue as sc

        cue, outer, _runner, calls = stop_cue_env

        def collect(cues, *a, **kw):
            calls.append(("collect",))
            return []

        monkeypatch.setattr(sc, "collect_live_faders", collect)

        cue.__start__()

        released = [c for c in calls if c[0] == "release"]
        assert sorted(released) == [("release", "g"), ("release", "n")]
        outer.execute.assert_called_once_with(CueAction.Pause)

    def test_instant_path_holds_nothing(self, stop_cue_env):
        cue, outer, _runner, calls = stop_cue_env
        cue.duration = 0

        cue.__start__()

        assert not [c for c in calls if c[0] in ("hold", "release")]
        outer.execute.assert_called_once_with(CueAction.Pause)
