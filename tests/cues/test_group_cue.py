from unittest.mock import MagicMock, call, patch
import threading

import pytest

from lisp.cues.cue import CueAction, CueState
from lisp.plugins.action_cues.group_cue import GroupCue


@pytest.fixture
def mock_app():
    app = MagicMock()
    app.conf = MagicMock()
    app.conf.get = MagicMock(return_value=0)
    return app


@pytest.fixture
def group(mock_app):
    g = GroupCue(mock_app)
    return g


def _make_child(cue_id, state=CueState.Stop, duration=10000):
    child = MagicMock()
    child.id = cue_id
    child.state = state
    child.duration = duration
    child.current_time = MagicMock(return_value=0)
    child.fadein_duration = 0
    child.fadeout_duration = 0
    # Explicit: a mock child supports no fade actions unless a
    # test says so (MagicMock's `in` would also say False, but
    # silently).
    child.CueActions = ()
    child.group_id = ""
    child.exclusive = False
    # Disable state — must be explicit False, otherwise MagicMock
    # auto-creates a truthy value and the playable-children filter
    # in GroupCue excludes it.
    child.disabled = False
    child.effective_disabled = False
    # Signals
    child.end = MagicMock()
    child.stopped = MagicMock()
    child.interrupted = MagicMock()
    child.error = MagicMock()
    return child


class TestGroupCueDefaults:
    def test_default_mode_is_parallel(self, group):
        assert group.group_mode == "parallel"

    def test_default_children_empty(self, group):
        assert group.children == []

    def test_default_crossfade_zero(self, group):
        assert group.crossfade == 0.0

    def test_default_loop_false(self, group):
        assert group.loop is False

    def test_default_icon(self, group):
        assert group.icon == "cue-group"

    def test_cue_actions(self, group):
        assert CueAction.Start in group.CueActions
        assert CueAction.Stop in group.CueActions
        assert CueAction.Pause in group.CueActions

    def test_default_collapsed_false(self, group):
        assert group.collapsed is False

    def test_default_shuffle_false(self, group):
        assert group.shuffle is False


class TestResolveChildren:
    def test_resolves_existing_children(self, group, mock_app):
        c1 = _make_child("c1")
        c2 = _make_child("c2")
        mock_app.cue_model.get = lambda cid: {
            "c1": c1, "c2": c2
        }.get(cid)
        group.children = ["c1", "c2"]

        result = group._resolve_children()
        assert result == [c1, c2]

    def test_skips_missing_children(self, group, mock_app):
        c1 = _make_child("c1")
        mock_app.cue_model.get = lambda cid: {
            "c1": c1
        }.get(cid)
        group.children = ["c1", "deleted-id", "also-gone"]

        result = group._resolve_children()
        assert result == [c1]

    def test_empty_children(self, group, mock_app):
        group.children = []
        assert group._resolve_children() == []


class TestParallelStart:
    def test_start_executes_all_children(self, group, mock_app):
        c1 = _make_child("c1")
        c2 = _make_child("c2")
        c3 = _make_child("c3")
        mock_app.cue_model.get = lambda cid: {
            "c1": c1, "c2": c2, "c3": c3
        }.get(cid)
        group.children = ["c1", "c2", "c3"]
        group.group_mode = "parallel"

        result = group.__start__(fade=False)

        assert result is True
        c1.execute.assert_called_once_with(CueAction.Start)
        c2.execute.assert_called_once_with(CueAction.Start)
        c3.execute.assert_called_once_with(CueAction.Start)

    def test_start_with_no_children_returns_false(
        self, group, mock_app
    ):
        group.children = []
        mock_app.cue_model.get = MagicMock(return_value=None)

        result = group.__start__(fade=False)
        assert result is False

    def test_connects_signals_for_all_children(
        self, group, mock_app
    ):
        c1 = _make_child("c1")
        c2 = _make_child("c2")
        mock_app.cue_model.get = lambda cid: {
            "c1": c1, "c2": c2
        }.get(cid)
        group.children = ["c1", "c2"]
        group.group_mode = "parallel"

        group.__start__(fade=False)

        assert c1.end.connect.called
        assert c1.stopped.connect.called
        assert c2.end.connect.called
        assert c2.stopped.connect.called


class TestPlaylistStart:
    def test_starts_only_first_child(self, group, mock_app):
        c1 = _make_child("c1")
        c2 = _make_child("c2")
        mock_app.cue_model.get = lambda cid: {
            "c1": c1, "c2": c2
        }.get(cid)
        group.children = ["c1", "c2"]
        group.group_mode = "playlist"

        result = group.__start__(fade=False)

        assert result is True
        c1.execute.assert_called_once_with(CueAction.Start)
        c2.execute.assert_not_called()

    def test_playlist_index_starts_at_zero(self, group, mock_app):
        c1 = _make_child("c1")
        mock_app.cue_model.get = lambda cid: {
            "c1": c1
        }.get(cid)
        group.children = ["c1"]
        group.group_mode = "playlist"

        group.__start__(fade=False)
        assert group._playlist_index == 0


class TestStopDisconnectsChildren:
    def test_stop_disconnects_all(self, group, mock_app):
        c1 = _make_child("c1", state=CueState.Running)
        c2 = _make_child("c2", state=CueState.Running)
        mock_app.cue_model.get = lambda cid: {
            "c1": c1, "c2": c2
        }.get(cid)
        group.children = ["c1", "c2"]
        group.group_mode = "parallel"

        group.__start__(fade=False)

        # Now stop
        result = group.__stop__(fade=False)
        assert result is True
        c1.execute.assert_any_call(CueAction.Stop)
        c2.execute.assert_any_call(CueAction.Stop)

    def test_stop_clears_connected_children(self, group, mock_app):
        c1 = _make_child("c1", state=CueState.Running)
        mock_app.cue_model.get = lambda cid: {
            "c1": c1
        }.get(cid)
        group.children = ["c1"]
        group.group_mode = "parallel"

        group.__start__(fade=False)
        group.__stop__(fade=False)

        assert len(group._connected_children) == 0


class TestGroupInterrupt:
    def test_interrupt_returns_true(self, group, mock_app):
        """__interrupt__ should return True like __stop__/__pause__."""
        c1 = _make_child("c1", state=CueState.Running)
        mock_app.cue_model.get = lambda cid: {
            "c1": c1
        }.get(cid)
        group.children = ["c1"]
        group.group_mode = "parallel"
        group.__start__(fade=False)

        result = group.__interrupt__(fade=False)
        assert result is True


class TestResumeFromPause:
    def test_parallel_resumes_paused_children(
        self, group, mock_app
    ):
        """After pause, start should resume paused children,
        not restart them from scratch."""
        c1 = _make_child("c1", state=CueState.Pause)
        c2 = _make_child("c2", state=CueState.Pause)
        mock_app.cue_model.get = lambda cid: {
            "c1": c1, "c2": c2
        }.get(cid)
        group.children = ["c1", "c2"]
        group.group_mode = "parallel"

        group.__start__(fade=False)

        c1.execute.assert_called_once_with(CueAction.Resume)
        c2.execute.assert_called_once_with(CueAction.Resume)

    def test_playlist_resumes_from_current_index(
        self, group, mock_app
    ):
        """After pause at index 1, start should resume the
        paused child at that index, not reset to index 0."""
        c1 = _make_child("c1", state=CueState.Stop)
        c2 = _make_child("c2", state=CueState.Pause)
        mock_app.cue_model.get = lambda cid: {
            "c1": c1, "c2": c2
        }.get(cid)
        group.children = ["c1", "c2"]
        group.group_mode = "playlist"
        group._playlist_index = 1

        group.__start__(fade=False)

        assert group._playlist_index == 1
        c2.execute.assert_called_once_with(CueAction.Resume)
        c1.execute.assert_not_called()


_FADE_CAPABLE = (
    CueAction.Start,
    CueAction.FadeInStart,
    CueAction.Resume,
    CueAction.FadeInResume,
)


class TestParallelChildFadeIn:
    """H34: GO on a parallel group must honour each child's own
    fade-in. The group's `fade` flag is the GROUP's fade-in
    (always 0 — GroupCue has no fade settings), so gating child
    fades on it meant no child ever faded in."""

    def _group_with(self, group, mock_app, *children):
        mock_app.cue_model.get = {c.id: c for c in children}.get
        group.children = [c.id for c in children]
        group.group_mode = "parallel"

    def test_child_with_fadein_gets_fadein_start(
        self, group, mock_app
    ):
        image = _make_child("image")
        image.fadein_duration = 1.0
        image.CueActions = _FADE_CAPABLE
        music = _make_child("music")
        music.CueActions = _FADE_CAPABLE
        self._group_with(group, mock_app, image, music)

        group.__start__(fade=False)

        image.execute.assert_called_once_with(CueAction.FadeInStart)
        # No fade-in → plain Start, so it stays in sync.
        music.execute.assert_called_once_with(CueAction.Start)

    def test_paused_child_with_fadein_gets_fadein_resume(
        self, group, mock_app
    ):
        image = _make_child("image", state=CueState.Pause)
        image.fadein_duration = 1.0
        image.CueActions = _FADE_CAPABLE
        music = _make_child("music", state=CueState.Pause)
        music.CueActions = _FADE_CAPABLE
        self._group_with(group, mock_app, image, music)

        group.__start__(fade=False)

        image.execute.assert_called_once_with(CueAction.FadeInResume)
        music.execute.assert_called_once_with(CueAction.Resume)

    def test_child_without_fade_actions_falls_back_to_start(
        self, group, mock_app
    ):
        """A child type that doesn't support FadeInStart (e.g. a
        nested GroupCue or an action cue) would silently ignore it
        in Cue.execute — it must still get a plain Start."""
        nested = _make_child("nested")
        nested.fadein_duration = 2.0
        nested.CueActions = (CueAction.Start, CueAction.Resume)
        paused = _make_child("paused", state=CueState.Pause)
        paused.fadein_duration = 2.0
        paused.CueActions = (CueAction.Start, CueAction.Resume)
        self._group_with(group, mock_app, nested, paused)

        group.__start__(fade=False)

        nested.execute.assert_called_once_with(CueAction.Start)
        paused.execute.assert_called_once_with(CueAction.Resume)

    def test_real_group_cue_child_gets_plain_start(
        self, group, mock_app
    ):
        """Pin the fallback against the real GroupCue.CueActions,
        not a hand-written tuple."""
        inner = GroupCue(mock_app)
        inner.fadein_duration = 2.0
        inner.execute = MagicMock()
        self._group_with(group, mock_app, inner)

        group.__start__(fade=False)

        inner.execute.assert_called_once_with(CueAction.Start)


class TestPlaylistChildFadeIn:
    """H34, playlist side: a child's own fade-in applies however
    it is started — GO, natural advance or loop — matching the
    crossfade path, which already sends FadeInStart."""

    def _playlist(self, group, mock_app, *children):
        mock_app.cue_model.get = {c.id: c for c in children}.get
        group.children = [c.id for c in children]
        group.group_mode = "playlist"

    def test_go_fades_in_first_child(self, group, mock_app):
        c1 = _make_child("c1")
        c1.fadein_duration = 1.0
        c1.CueActions = _FADE_CAPABLE
        c2 = _make_child("c2")
        self._playlist(group, mock_app, c1, c2)

        group.__start__(fade=False)

        c1.execute.assert_called_once_with(CueAction.FadeInStart)
        c2.execute.assert_not_called()

    def test_go_resumes_paused_child_with_fadein(
        self, group, mock_app
    ):
        c1 = _make_child("c1")
        c2 = _make_child("c2", state=CueState.Pause)
        c2.fadein_duration = 1.0
        c2.CueActions = _FADE_CAPABLE
        self._playlist(group, mock_app, c1, c2)
        group._playlist_index = 1

        group.__start__(fade=False)

        c2.execute.assert_called_once_with(CueAction.FadeInResume)

    def test_natural_advance_fades_in_next_child(
        self, group, mock_app
    ):
        c1 = _make_child("c1")
        c1.CueActions = _FADE_CAPABLE
        c2 = _make_child("c2")
        c2.fadein_duration = 1.0
        c2.CueActions = _FADE_CAPABLE
        self._playlist(group, mock_app, c1, c2)
        group.__start__(fade=False)
        c1.execute.assert_called_once_with(CueAction.Start)

        group._state = CueState.Running
        group._on_playlist_child_ended(c1)

        c2.execute.assert_called_once_with(CueAction.FadeInStart)

    def test_child_without_fade_actions_gets_plain_start(
        self, group, mock_app
    ):
        c1 = _make_child("c1")
        c1.fadein_duration = 1.0
        c1.CueActions = (CueAction.Start,)
        self._playlist(group, mock_app, c1)

        group.__start__(fade=False)

        c1.execute.assert_called_once_with(CueAction.Start)

    def test_loop_wrap_fades_in_first_child(self, group, mock_app):
        c1 = _make_child("c1")
        c1.fadein_duration = 1.0
        c1.CueActions = _FADE_CAPABLE
        c2 = _make_child("c2")
        c2.CueActions = _FADE_CAPABLE
        self._playlist(group, mock_app, c1, c2)
        group.loop = True
        group.__start__(fade=False)
        group._state = CueState.Running
        group._on_playlist_child_ended(c1)
        c2.execute.assert_called_once_with(CueAction.Start)

        # Last child ends -> wraps to c1, which fades in again.
        group._on_playlist_child_ended(c2)

        assert c1.execute.call_args_list == [
            call(CueAction.FadeInStart),
            call(CueAction.FadeInStart),
        ]

    def test_go_ignores_crossfade_hold_awaiting_restore(
        self, group, mock_app, qtbot
    ):
        """A crossfade hold whose restore has been released but not
        yet applied (it is queued to the main thread) must not make
        the next GO fade the child in over the crossfade time."""
        c1 = _make_child("c1")
        c1.CueActions = _FADE_CAPABLE
        self._playlist(group, mock_app, c1)

        # Hold c1's fade-in at the crossfade value, as _check_crossfade
        # does, then release it the way a group stop does. The
        # restore write is QtQueued: no events processed yet, so the
        # held value is still there when GO runs.
        group._hold_fade(c1, "fadein_duration", 2.0, (c1.started,))
        group._flush_pending_restores()
        assert c1.fadein_duration == 2.0

        group.__start__(fade=False)

        c1.execute.assert_called_once_with(CueAction.Start)

        # Once the main thread runs the queued restore, it's 0 again
        # and the bookkeeping is gone.
        qtbot.waitUntil(lambda: c1.fadein_duration == 0, timeout=1000)
        assert not group._restoring

    def test_go_still_fades_child_whose_own_fadein_is_unheld(
        self, group, mock_app, qtbot
    ):
        """The guard only masks the held value: a child whose value
        was changed after the hold keeps its own fade-in."""
        c1 = _make_child("c1")
        c1.CueActions = _FADE_CAPABLE
        self._playlist(group, mock_app, c1)
        group._hold_fade(c1, "fadein_duration", 2.0, (c1.started,))
        group._flush_pending_restores()
        c1.fadein_duration = 1.5  # user edit before the restore ran

        group.__start__(fade=False)

        c1.execute.assert_called_once_with(CueAction.FadeInStart)


class TestCrossfadePreservation:
    def test_crossfade_sets_fadeout_for_execute(
        self, group, mock_app
    ):
        """Crossfade should set fadeout_duration before executing
        FadeOutStop so the worker thread reads the correct value.
        The property is restored from a one-shot stopped handler
        (see
        tests/plugins/action_cues/test_group_cue_crossfade_restore.py)."""
        c1 = _make_child(
            "c1", state=CueState.Running, duration=10000
        )
        c1.current_time = MagicMock(return_value=9500)
        c1.fadeout_duration = 0
        c2 = _make_child("c2")
        mock_app.cue_model.get = lambda cid: {
            "c1": c1, "c2": c2
        }.get(cid)
        group.children = ["c1", "c2"]
        group.group_mode = "playlist"
        group.crossfade = 1.0

        group._playlist_index = 0
        group._crossfade_armed = True
        group._connected_children = {"c1"}

        group._check_crossfade()

        # fadeout_duration is set to crossfade value for the
        # execute call; restore happens via stopped signal
        c1.execute.assert_called_once_with(CueAction.FadeOutStop)
        c1.stopped.connect.assert_called()

    def test_crossfade_sets_fadein_for_execute(
        self, group, mock_app
    ):
        """Crossfade should set fadein_duration before executing
        FadeInStart so the worker thread reads the correct value.
        The property is restored from a one-shot fadein_start
        handler, once the fade has read it (see
        tests/plugins/action_cues/test_group_cue_crossfade_restore.py)."""
        c1 = _make_child(
            "c1", state=CueState.Running, duration=10000
        )
        c1.current_time = MagicMock(return_value=9500)
        c2 = _make_child("c2")
        c2.fadein_duration = 0
        c2.CueActions = (CueAction.Start, CueAction.FadeInStart)
        mock_app.cue_model.get = lambda cid: {
            "c1": c1, "c2": c2
        }.get(cid)
        group.children = ["c1", "c2"]
        group.group_mode = "playlist"
        group.crossfade = 1.0

        group._playlist_index = 0
        group._crossfade_armed = True
        group._connected_children = {"c1"}

        group._check_crossfade()

        # fadein_duration is set to crossfade value for the
        # execute call; restore happens once the fade has read it
        c2.execute.assert_called_once_with(CueAction.FadeInStart)
        c2.fadein_start.connect.assert_called()


class TestGroupIdProperty:
    def test_group_id_default(self, mock_app):
        from lisp.cues.cue import Cue

        c = Cue(mock_app)
        assert c.group_id == ""

    def test_group_id_serialized(self, mock_app):
        from lisp.cues.cue import Cue

        c = Cue(mock_app)
        c.group_id = "some-group-id"
        props = c.properties()
        assert props["group_id"] == "some-group-id"


class TestCollapsedProperty:
    def test_collapsed_default(self, mock_app):
        g = GroupCue(mock_app)
        assert g.collapsed is False

    def test_collapsed_serialized(self, mock_app):
        g = GroupCue(mock_app)
        g.collapsed = True
        props = g.properties()
        assert props["collapsed"] is True

    def test_collapsed_not_in_defaults_when_false(self, mock_app):
        g = GroupCue(mock_app)
        props = g.properties(defaults=False)
        assert "collapsed" not in props


class TestPlaylistShuffle:
    def test_start_does_not_shuffle_even_with_flag_on(
        self, group, mock_app
    ):
        """Fresh playlist start must NOT shuffle — order stays
        consistent during the show, even with shuffle=True."""
        ids = [f"c{i}" for i in range(10)]
        children = {cid: _make_child(cid) for cid in ids}
        mock_app.cue_model.get = lambda cid: children.get(cid)
        group.children = list(ids)
        group.group_mode = "playlist"
        group.shuffle = True
        # Toggle-True shuffled the list; capture that as baseline
        # and verify starting does NOT reshuffle.
        baseline = list(group.children)

        group.__start__(fade=False)

        assert group.children == baseline

    def test_resume_does_not_shuffle(self, group, mock_app):
        """Resuming a paused shuffle playlist must NOT shuffle."""
        c1 = _make_child("c1", state=CueState.Stop)
        c2 = _make_child("c2", state=CueState.Pause)
        mock_app.cue_model.get = lambda cid: {
            "c1": c1, "c2": c2
        }.get(cid)
        group.children = ["c1", "c2"]
        group.group_mode = "playlist"
        group.shuffle = True
        # Reset children after the toggle handler ran
        group.children = ["c1", "c2"]
        group._playlist_index = 1

        group.__start__(fade=False)

        assert group.children == ["c1", "c2"]
        assert group._playlist_index == 1

    def test_no_shuffle_when_flag_false(self, group, mock_app):
        """With shuffle=False, starting preserves children order."""
        ids = ["c1", "c2", "c3"]
        children = {cid: _make_child(cid) for cid in ids}
        mock_app.cue_model.get = lambda cid: children.get(cid)
        group.children = list(ids)
        group.group_mode = "playlist"
        group.shuffle = False

        group.__start__(fade=False)

        assert group.children == ["c1", "c2", "c3"]

    def test_shuffle_on_property_toggle_true(
        self, group, mock_app
    ):
        """Setting shuffle True on a playlist group triggers a
        shuffle — the 'option enabled' trigger."""
        ids = [f"c{i}" for i in range(10)]
        children = {cid: _make_child(cid) for cid in ids}
        mock_app.cue_model.get = lambda cid: children.get(cid)
        group.children = list(ids)
        group.group_mode = "playlist"
        assert group.shuffle is False

        group.shuffle = True

        assert group.children != ids

    def test_no_shuffle_on_property_toggle_false(
        self, group, mock_app
    ):
        """Setting shuffle False is a no-op for ordering."""
        ids = ["c1", "c2", "c3"]
        children = {cid: _make_child(cid) for cid in ids}
        mock_app.cue_model.get = lambda cid: children.get(cid)
        group.children = list(ids)
        group.group_mode = "playlist"
        group.shuffle = True
        group.children = list(ids)  # reset after toggle shuffle

        group.shuffle = False

        assert group.children == ids

    def test_no_shuffle_on_toggle_when_parallel(
        self, group, mock_app
    ):
        """Parallel groups ignore the shuffle option even when
        toggled True."""
        ids = ["c1", "c2", "c3"]
        group.children = list(ids)
        group.group_mode = "parallel"

        group.shuffle = True

        assert group.children == ids

    def test_shuffle_on_session_load(self, group, mock_app):
        """_shuffle_on_load should shuffle children of playlist
        groups with shuffle=True."""
        from lisp.plugins.action_cues import ActionCues

        ids = [f"c{i}" for i in range(10)]
        children = {cid: _make_child(cid) for cid in ids}
        mock_app.cue_model.get = lambda cid: children.get(cid)

        group.children = list(ids)
        group.group_mode = "playlist"
        group.shuffle = True

        # Put the group in the cue model
        mock_app.cue_model.__iter__ = lambda self: iter([group])

        ActionCues._shuffle_on_load(mock_app)

        assert group.children != ids

    def test_no_shuffle_on_load_when_parallel(
        self, group, mock_app
    ):
        """Parallel groups should not be shuffled on load."""
        from lisp.plugins.action_cues import ActionCues

        group.children = ["c1", "c2", "c3"]
        group.group_mode = "parallel"
        group.shuffle = True

        mock_app.cue_model.__iter__ = lambda self: iter([group])

        ActionCues._shuffle_on_load(mock_app)

        assert group.children == ["c1", "c2", "c3"]

    def test_no_shuffle_on_load_when_shuffle_false(
        self, group, mock_app
    ):
        """Playlist groups with shuffle=False should not be
        shuffled on load."""
        from lisp.plugins.action_cues import ActionCues

        group.children = ["c1", "c2", "c3"]
        group.group_mode = "playlist"
        group.shuffle = False

        mock_app.cue_model.__iter__ = lambda self: iter([group])

        ActionCues._shuffle_on_load(mock_app)

        assert group.children == ["c1", "c2", "c3"]

    def test_shuffle_on_load_mixed_groups(self, mock_app):
        """Only playlist+shuffle groups are shuffled; parallel
        and shuffle=False groups in the same session are left
        alone."""
        from lisp.plugins.action_cues import ActionCues

        ids = [f"c{i}" for i in range(10)]

        shuffled_group = GroupCue(mock_app)
        shuffled_group.children = list(ids)
        shuffled_group.group_mode = "playlist"
        shuffled_group.shuffle = True

        parallel_group = GroupCue(mock_app)
        parallel_group.children = list(ids)
        parallel_group.group_mode = "parallel"
        parallel_group.shuffle = True  # flag ignored in parallel

        no_shuffle_group = GroupCue(mock_app)
        no_shuffle_group.children = list(ids)
        no_shuffle_group.group_mode = "playlist"
        no_shuffle_group.shuffle = False

        groups = [shuffled_group, parallel_group, no_shuffle_group]
        mock_app.cue_model.__iter__ = lambda self: iter(groups)

        ActionCues._shuffle_on_load(mock_app)

        assert shuffled_group.children != ids
        assert parallel_group.children == ids
        assert no_shuffle_group.children == ids

    def test_shuffle_on_load_single_child(self, group, mock_app):
        """Single-child group should be skipped (len > 1 guard)
        — no crash, no spurious mutation."""
        from lisp.plugins.action_cues import ActionCues

        group.children = ["c1"]
        group.group_mode = "playlist"
        group.shuffle = True

        mock_app.cue_model.__iter__ = lambda self: iter([group])

        ActionCues._shuffle_on_load(mock_app)

        assert group.children == ["c1"]

    def test_shuffle_on_load_empty_children(
        self, group, mock_app
    ):
        """Empty-children group should be skipped, no crash."""
        from lisp.plugins.action_cues import ActionCues

        group.children = []
        group.group_mode = "playlist"
        group.shuffle = True

        mock_app.cue_model.__iter__ = lambda self: iter([group])

        ActionCues._shuffle_on_load(mock_app)

        assert group.children == []

    def test_shuffle_on_load_ignores_non_group_cues(
        self, group, mock_app
    ):
        """Non-GroupCue entries in cue_model must be skipped
        without AttributeError on missing .group_mode etc."""
        from lisp.plugins.action_cues import ActionCues

        ids = [f"c{i}" for i in range(10)]
        group.children = list(ids)
        group.group_mode = "playlist"
        group.shuffle = True

        # Plain Mock with no group_mode/shuffle attrs — would
        # crash if _shuffle_on_load did not isinstance-check.
        non_group = MagicMock(spec=[])
        mock_app.cue_model.__iter__ = lambda self: iter(
            [non_group, group, non_group]
        )

        ActionCues._shuffle_on_load(mock_app)

        assert group.children != ids


class TestNestedGroupRuntime:
    """The engine doesn't care if a child is itself a GroupCue;
    these tests pin that behavior so future refactors notice if
    nesting regresses."""

    def test_outer_parallel_starts_inner_group(self, mock_app):
        import time
        from lisp.plugins.action_cues.group_cue import GroupCue

        # Unblock execute() — MagicMock auto-creates these attrs
        # with truthy return values, which would trip the exclusive-
        # manager gate and silently swallow inner.execute().
        mock_app.exclusive_manager.is_start_blocked.return_value = (
            False
        )
        mock_app.video_exclusive_manager.is_start_blocked.return_value = (
            False
        )

        outer = GroupCue(app=mock_app)
        inner = GroupCue(app=mock_app)
        inner.group_id = outer.id

        leaf = MagicMock()
        leaf.id = "leaf"
        leaf.group_id = inner.id
        leaf.effective_disabled = False
        leaf.state = 0  # CueState.Stop
        leaf.fadein_duration = 0
        # Capture executes
        leaf.execute = MagicMock()

        mock_app.cue_model.get.side_effect = lambda i: {
            outer.id: outer,
            inner.id: inner,
            leaf.id: leaf,
        }.get(i)

        outer.children = [inner.id]
        inner.children = [leaf.id]
        outer.group_mode = "parallel"
        inner.group_mode = "parallel"

        # Drive the cascade by directly invoking __start__ as
        # the engine would — this avoids state-machine setup.
        outer.__start__(False)

        # inner.execute(CueAction.Start) spawns an async thread
        # (Cue.start is @async_function). Poll until leaf.execute
        # is called or the deadline expires — exits as soon as the
        # cascade completes (<10ms typical), avoiding both the
        # slowness and the flake-risk of a fixed sleep.
        deadline = time.monotonic() + 1.0
        while not leaf.execute.called and time.monotonic() < deadline:
            time.sleep(0.005)

        # Outer started inner; inner's __start__ should have
        # started the leaf.
        # We can't easily intercept inner.execute (it's a real
        # GroupCue); assert via leaf.execute being called.
        assert leaf.execute.called, (
            "leaf.execute should have been called via cascade "
            "outer -> inner -> leaf"
        )

    def test_outer_stop_cascades_through_inner_to_leaf(
        self, mock_app
    ):
        """outer.__stop__() must reach a leaf inside an already-
        running inner GroupCue. GroupCue.__stop__ filters by
        `state & IsRunning`, so this pins that the inner group's
        Running state isn't accidentally treated as inert."""
        import time
        from lisp.cues.cue import CueState
        from lisp.plugins.action_cues.group_cue import GroupCue

        mock_app.exclusive_manager.is_start_blocked.return_value = (
            False
        )
        mock_app.video_exclusive_manager.is_start_blocked.return_value = (
            False
        )

        outer = GroupCue(app=mock_app)
        inner = GroupCue(app=mock_app)
        inner.group_id = outer.id
        # Skip the start cascade — set inner directly to Running so
        # outer's __stop__ filter sees it as a stop target.
        inner._state = CueState.Running

        leaf = MagicMock()
        leaf.id = "leaf"
        leaf.group_id = inner.id
        leaf.effective_disabled = False
        leaf.state = CueState.Running
        leaf.execute = MagicMock()

        mock_app.cue_model.get.side_effect = lambda i: {
            outer.id: outer,
            inner.id: inner,
            leaf.id: leaf,
        }.get(i)

        outer.children = [inner.id]
        inner.children = [leaf.id]
        outer.group_mode = "parallel"
        inner.group_mode = "parallel"

        outer.__stop__(False)

        # inner.execute(CueAction.Stop) routes through the
        # @async_function decorator to a worker thread. Poll
        # for cascade completion.
        deadline = time.monotonic() + 1.0
        while not leaf.execute.called and time.monotonic() < deadline:
            time.sleep(0.005)

        assert leaf.execute.called, (
            "leaf.execute should have been called via stop "
            "cascade outer -> inner -> leaf"
        )

    def test_effective_disabled_propagates_two_levels(
        self, mock_app
    ):
        """Disabling the outer group makes a depth-2 leaf
        report effective_disabled = True via the existing
        ancestor-walk in Cue.effective_disabled."""
        from lisp.cues.cue import Cue
        from lisp.plugins.action_cues.group_cue import GroupCue

        outer = GroupCue(app=mock_app)
        inner = GroupCue(app=mock_app)
        inner.group_id = outer.id

        # Use a real Cue subclass-like object so we exercise
        # the actual effective_disabled property. The base Cue
        # is abstract enough; spawn a minimal concrete subclass.
        class _LeafCue(Cue):
            CueActions = (Cue.CueActions[0],)

        leaf = _LeafCue(app=mock_app)
        leaf.group_id = inner.id

        mock_app.cue_model.get.side_effect = lambda i: {
            outer.id: outer,
            inner.id: inner,
        }.get(i)

        assert leaf.effective_disabled is False
        outer.disabled = True
        assert leaf.effective_disabled is True

    def test_shuffle_on_load_multiple_shuffle_groups(
        self, mock_app
    ):
        """Every playlist+shuffle group gets shuffled
        independently — loop does not short-circuit."""
        from lisp.plugins.action_cues import ActionCues

        ids = [f"c{i}" for i in range(10)]

        g1 = GroupCue(mock_app)
        g1.children = list(ids)
        g1.group_mode = "playlist"
        g1.shuffle = True

        g2 = GroupCue(mock_app)
        g2.children = list(ids)
        g2.group_mode = "playlist"
        g2.shuffle = True

        mock_app.cue_model.__iter__ = lambda self: iter([g1, g2])

        ActionCues._shuffle_on_load(mock_app)

        assert g1.children != ids
        assert g2.children != ids

    def test_loop_does_not_reshuffle(self, group, mock_app):
        """Loop wrap-around must NOT re-shuffle.

        The shuffled order, established on toggle/load, must
        replay verbatim on every loop so the same track does
        not repeat back-to-back across the cycle boundary.
        """
        ids = [f"c{i}" for i in range(10)]
        children = {cid: _make_child(cid) for cid in ids}
        mock_app.cue_model.get = lambda cid: children.get(cid)
        group.children = list(ids)
        group.group_mode = "playlist"
        group.shuffle = True  # toggle triggers shuffle
        group.loop = True
        shuffled_order = list(group.children)
        assert shuffled_order != ids

        group.__start__(fade=False)
        # Simulate loop wrap: _play_child_at with index past end
        group._play_child_at(
            len(shuffled_order),
            group._resolve_children(),
        )

        assert group.children == shuffled_order

    def test_shuffle_syncs_layout_indices(
        self, group, mock_app
    ):
        """shuffle_children must move cues in the layout model
        so the UI row order matches self.children (the UI sorts
        by cue.index within a group, not by children list)."""
        ids = ["c1", "c2", "c3"]
        children = {}
        for i, cid in enumerate(ids, start=1):
            c = _make_child(cid)
            c.index = i  # children at indices 1,2,3
            children[cid] = c
        mock_app.cue_model.get = lambda cid: children.get(cid)
        group.index = 0  # group is at index 0, owns slots 1-3
        group.children = list(ids)
        group.group_mode = "playlist"

        group.shuffle_children()

        # Exactly the children that ended up in a different
        # slot should have triggered a model.move call.
        expected_moves = sum(
            1 for i, cid in enumerate(group.children, start=1)
            if children[cid].index != i
        )
        assert mock_app.layout.model.move.call_count == expected_moves

    def test_shuffle_skips_layout_when_no_layout(
        self, group, mock_app
    ):
        """If app.layout is None (no session), shuffle_children
        should still randomize the list without crashing."""
        ids = [f"c{i}" for i in range(10)]
        children = {cid: _make_child(cid) for cid in ids}
        mock_app.cue_model.get = lambda cid: children.get(cid)
        mock_app.layout = None
        group.children = list(ids)
        group.group_mode = "playlist"

        group.shuffle_children()

        assert group.children != ids

    def test_shuffle_serialization_round_trip(self, mock_app):
        """Shuffle Property should serialize and deserialize."""
        g = GroupCue(mock_app)
        g.shuffle = True
        props = g.properties()
        assert props["shuffle"] is True

        g2 = GroupCue(mock_app)
        g2.update_properties(props)
        assert g2.shuffle is True

    def test_shuffle_not_in_defaults_when_false(self, mock_app):
        g = GroupCue(mock_app)
        props = g.properties(defaults=False)
        assert "shuffle" not in props

    def test_session_loaded_signal_triggers_shuffle(self, mock_app):
        """The plugin must retain a strong reference to its session
        handler, or the weakref in Signal.connect would GC it and
        shuffle-on-load would silently never fire.
        """
        import gc
        from lisp.core.signal import Signal

        mock_app.session_loaded = Signal()
        mock_app.cue_factory = MagicMock()
        mock_app.window = MagicMock()

        g = GroupCue(mock_app)
        g.children = [f"c{i}" for i in range(10)]
        g.group_mode = "playlist"
        g.shuffle = True
        mock_app.cue_model.__iter__ = lambda self: iter([g])

        # Importing ActionCues triggers module load; instantiate it
        # so __init__ runs and connects the signal.
        from lisp.plugins.action_cues import ActionCues

        # Patch load_classes so __init__ does not re-register cues.
        with patch("lisp.plugins.action_cues.load_classes",
                   return_value=iter([])):
            plugin = ActionCues(mock_app)

        # Force a GC cycle — if the handler was weakly held, this
        # would collect the bare lambda and make the next emit
        # a silent no-op.
        gc.collect()

        original = list(g.children)
        mock_app.session_loaded.emit(None)

        assert g.children != original
        # Silence unused-var warning while keeping plugin alive
        assert plugin is not None


def _refused(child):
    """Make ``child`` refuse every start, as `Cue.execute` does for a
    cue blocked by an exclusive cue or by video exclusivity."""
    child.execute.return_value = False
    return child


class _EndObserver:
    """Named `end` observer (a bare lambda would be weakly dropped)."""

    def __init__(self, cue):
        self.event = threading.Event()
        cue.end.connect(self.on_end)

    def on_end(self, *_args):
        self.event.set()


class TestParallelRefusedChildren:
    """H31/M64: children refused a start must not leave a parallel
    group Running with nothing that can ever end it."""

    def _group_with(self, group, mock_app, *children):
        mock_app.cue_model.get = {c.id: c for c in children}.get
        group.children = [c.id for c in children]
        group.group_mode = "parallel"

    def test_all_children_refused_returns_false(self, group, mock_app):
        c1, c2 = _refused(_make_child("c1")), _refused(_make_child("c2"))
        self._group_with(group, mock_app, c1, c2)

        assert group.__start__(fade=False) is False
        assert group._connected_children == set()
        c1.end.disconnect.assert_called()
        c2.end.disconnect.assert_called()

    def test_refused_child_is_not_waited_for(self, group, mock_app):
        c1 = _make_child("c1")
        c2 = _refused(_make_child("c2"))
        self._group_with(group, mock_app, c1, c2)

        assert group.__start__(fade=False) is True
        assert group._connected_children == {"c1"}

        # The child that did start ends: that ends the group.
        group._state = CueState.Running
        group._on_child_ended(c1)
        assert group.state == CueState.Stop

    def test_group_ends_when_every_child_is_refused(
        self, group, mock_app
    ):
        """Through the real `Cue.start`: the group's end fires (so
        auto-follow runs) and it doesn't stay Running."""
        c1, c2 = _refused(_make_child("c1")), _refused(_make_child("c2"))
        self._group_with(group, mock_app, c1, c2)
        ended = _EndObserver(group)

        group.start()

        assert ended.event.wait(3.0), "group end never fired"
        assert not (group.state & CueState.IsRunning)


class TestPlaylistRefusedChildren:
    """H31/M64, playlist side: a refused child is skipped like a
    disabled one; when none can start the group ends."""

    def _playlist(self, group, mock_app, *children):
        mock_app.cue_model.get = {c.id: c for c in children}.get
        group.children = [c.id for c in children]
        group.group_mode = "playlist"

    def test_refused_first_child_skips_to_next(self, group, mock_app):
        c1 = _refused(_make_child("c1"))
        c2 = _make_child("c2")
        self._playlist(group, mock_app, c1, c2)

        assert group.__start__(fade=False) is True
        c2.execute.assert_called_once_with(CueAction.Start)
        assert group._playlist_index == 1
        assert group._connected_children == {"c2"}
        c1.end.disconnect.assert_called()

    def test_all_refused_returns_false(self, group, mock_app):
        c1, c2 = _refused(_make_child("c1")), _refused(_make_child("c2"))
        self._playlist(group, mock_app, c1, c2)

        assert group.__start__(fade=False) is False
        assert group._connected_children == set()

    def test_all_refused_with_loop_tries_each_child_once(
        self, group, mock_app
    ):
        c1, c2 = _refused(_make_child("c1")), _refused(_make_child("c2"))
        self._playlist(group, mock_app, c1, c2)
        group.loop = True

        assert group.__start__(fade=False) is False
        assert c1.execute.call_count == 1
        assert c2.execute.call_count == 1

    def test_group_ends_when_every_child_is_refused(
        self, group, mock_app
    ):
        c1 = _refused(_make_child("c1"))
        self._playlist(group, mock_app, c1)
        ended = _EndObserver(group)

        group.start()

        assert ended.event.wait(3.0), "group end never fired"
        assert not (group.state & CueState.IsRunning)

    def test_advance_skips_refused_child(self, group, mock_app):
        c1, c3 = _make_child("c1"), _make_child("c3")
        c2 = _refused(_make_child("c2"))
        self._playlist(group, mock_app, c1, c2, c3)
        group.__start__(fade=False)
        group._state = CueState.Running

        group._on_playlist_child_ended(c1)

        c3.execute.assert_called_once_with(CueAction.Start)
        assert group._playlist_index == 2
        assert group._connected_children == {"c3"}
        assert group.state & CueState.Running

    def test_advance_to_refused_last_child_ends_group(
        self, group, mock_app
    ):
        c1 = _make_child("c1")
        c2 = _refused(_make_child("c2"))
        self._playlist(group, mock_app, c1, c2)
        group.__start__(fade=False)
        group._state = CueState.Running

        group._on_playlist_child_ended(c1)

        assert group.state == CueState.Stop
        assert group._connected_children == set()

    def test_loop_advance_with_all_others_refused_restarts_current(
        self, group, mock_app
    ):
        """Looping: the walk wraps round to the child that just
        ended, which can start again."""
        c1 = _make_child("c1")
        c2 = _refused(_make_child("c2"))
        self._playlist(group, mock_app, c1, c2)
        group.loop = True
        group.__start__(fade=False)
        group._state = CueState.Running

        group._on_playlist_child_ended(c1)

        assert c1.execute.call_count == 2
        assert c2.execute.call_count == 1
        assert group._playlist_index == 0
        assert group.state & CueState.Running

    def test_loop_advance_with_all_refused_ends_group(
        self, group, mock_app
    ):
        c1 = _make_child("c1")
        c2 = _refused(_make_child("c2"))
        self._playlist(group, mock_app, c1, c2)
        group.loop = True
        group.__start__(fade=False)
        group._state = CueState.Running
        _refused(c1)  # now blocked too (e.g. exclusive cue started)

        group._on_playlist_child_ended(c1)

        assert c1.execute.call_count == 2
        assert c2.execute.call_count == 1
        assert group.state == CueState.Stop


class TestCrossfadeRefusedNextChild:
    """H31/M64 at the crossfade point: the outgoing child is only
    faded out once an incoming one has really started."""

    def _at_crossfade(self, group, mock_app, *children):
        mock_app.cue_model.get = {c.id: c for c in children}.get
        group.children = [c.id for c in children]
        group.group_mode = "playlist"
        group.crossfade = 1.0
        group._playlist_index = 0
        group._crossfade_armed = True
        group._connected_children = {children[0].id}

    def _running_c1(self):
        c1 = _make_child("c1", state=CueState.Running, duration=10000)
        c1.current_time = MagicMock(return_value=9500)
        c1.CueActions = (CueAction.Start, CueAction.FadeOutStop)
        return c1

    def test_refused_next_keeps_current_playing(
        self, group, mock_app, qtbot
    ):
        c1 = self._running_c1()
        c2 = _refused(_make_child("c2"))
        c2.CueActions = _FADE_CAPABLE
        self._at_crossfade(group, mock_app, c1, c2)

        group._check_crossfade()

        assert call(CueAction.FadeOutStop) not in c1.execute.call_args_list
        assert group._connected_children == {"c1"}
        assert group._playlist_index == 0
        assert group._crossfade_armed is False
        assert c1.fadeout_duration == 0
        qtbot.waitUntil(lambda: c2.fadein_duration == 0, timeout=1000)

    def test_refused_next_crossfades_into_the_one_after(
        self, group, mock_app
    ):
        c1 = self._running_c1()
        c2 = _refused(_make_child("c2"))
        c3 = _make_child("c3")
        c3.CueActions = _FADE_CAPABLE
        self._at_crossfade(group, mock_app, c1, c2, c3)

        group._check_crossfade()

        c3.execute.assert_called_once_with(CueAction.FadeInStart)
        c1.execute.assert_called_once_with(CueAction.FadeOutStop)
        assert group._playlist_index == 2
        assert group._connected_children == {"c3"}


class TestNestedGroupWithNothingPlayable:
    """H31: a nested group whose children are all disabled refuses
    its start; the outer group must see that refusal, not wait for
    an inner group that never ran."""

    def _nested(self, mock_app, outer_mode):
        leaf = _make_child("leaf")
        leaf.disabled = True
        leaf.effective_disabled = True
        inner = GroupCue(mock_app)
        outer = GroupCue(mock_app)
        cues = {leaf.id: leaf, inner.id: inner, outer.id: outer}
        mock_app.cue_model.get = cues.get
        inner.children = [leaf.id]
        outer.children = [inner.id]
        outer.group_mode = outer_mode
        return outer, inner

    def test_execute_start_reports_refusal(self, mock_app):
        _outer, inner = self._nested(mock_app, "parallel")
        assert inner.execute(CueAction.Start) is False

    @pytest.mark.parametrize("mode", ["parallel", "playlist"])
    def test_outer_group_does_not_wait_for_it(self, mock_app, mode):
        outer, _inner = self._nested(mock_app, mode)
        assert outer.__start__(fade=False) is False
        assert outer._connected_children == set()
