from unittest.mock import MagicMock, patch

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
    child.group_id = ""
    child.exclusive = False
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


class TestCrossfadePreservation:
    def test_crossfade_sets_fadeout_for_execute(
        self, group, mock_app
    ):
        """Crossfade should set fadeout_duration before executing
        FadeOutStop so the worker thread reads the correct value.
        The property is restored asynchronously via a one-shot
        stopped signal handler (tested in E2E)."""
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
        The property is restored asynchronously via a one-shot
        started signal handler (tested in E2E)."""
        c1 = _make_child(
            "c1", state=CueState.Running, duration=10000
        )
        c1.current_time = MagicMock(return_value=9500)
        c2 = _make_child("c2")
        c2.fadein_duration = 0
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
        # execute call; restore happens via started signal
        c2.execute.assert_called_once_with(CueAction.FadeInStart)
        c2.started.connect.assert_called()


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
    def test_shuffle_reorders_children_on_start(
        self, group, mock_app
    ):
        """Starting a stopped shuffle playlist should randomize
        the children list."""
        ids = [f"c{i}" for i in range(10)]
        children = {cid: _make_child(cid) for cid in ids}
        mock_app.cue_model.get = lambda cid: children.get(cid)
        group.children = list(ids)
        group.group_mode = "playlist"
        group.shuffle = True

        group.__start__(fade=False)

        # With 10 children the probability of the shuffle
        # producing the original order is 1/10! ≈ 0.00003%
        assert group.children != ids

    def test_shuffle_does_not_reorder_on_resume(
        self, group, mock_app
    ):
        """Resuming a paused shuffle playlist must NOT re-shuffle."""
        c1 = _make_child("c1", state=CueState.Stop)
        c2 = _make_child("c2", state=CueState.Pause)
        mock_app.cue_model.get = lambda cid: {
            "c1": c1, "c2": c2
        }.get(cid)
        group.children = ["c1", "c2"]
        group.group_mode = "playlist"
        group.shuffle = True
        group._playlist_index = 1

        group.__start__(fade=False)

        # Children order unchanged — we resumed, not restarted
        assert group.children == ["c1", "c2"]
        assert group._playlist_index == 1

    def test_no_shuffle_when_flag_false(self, group, mock_app):
        """With shuffle=False, children order is preserved."""
        ids = ["c1", "c2", "c3"]
        children = {cid: _make_child(cid) for cid in ids}
        mock_app.cue_model.get = lambda cid: children.get(cid)
        group.children = list(ids)
        group.group_mode = "playlist"
        group.shuffle = False

        group.__start__(fade=False)

        assert group.children == ["c1", "c2", "c3"]

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

    def test_loop_does_not_reshuffle(self, group, mock_app):
        """Loop wrap-around must NOT re-shuffle — spec requirement.

        _start_playlist is not called on loop; _play_child_at
        only resets index to 0. Verify the order is stable across
        a wrap, so the same shuffled sequence replays on loop.
        """
        ids = [f"c{i}" for i in range(10)]
        children = {cid: _make_child(cid) for cid in ids}
        mock_app.cue_model.get = lambda cid: children.get(cid)
        group.children = list(ids)
        group.group_mode = "playlist"
        group.shuffle = True
        group.loop = True

        # Fresh start — triggers shuffle
        group.__start__(fade=False)
        shuffled_order = list(group.children)
        assert shuffled_order != ids

        # Simulate loop wrap: _play_child_at with index past end
        group._play_child_at(
            len(shuffled_order),
            group._resolve_children(),
            fade=False,
        )

        # Children order unchanged — loop reused same shuffle
        assert group.children == shuffled_order

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
