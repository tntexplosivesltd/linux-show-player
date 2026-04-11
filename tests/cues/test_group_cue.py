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
    def test_crossfade_preserves_child_fadeout_duration(
        self, group, mock_app
    ):
        """Crossfade should not permanently modify a child's
        fadeout_duration property (it would be serialized)."""
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

        assert c1.fadeout_duration == 0

    def test_crossfade_preserves_next_child_fadein_duration(
        self, group, mock_app
    ):
        """Crossfade should not permanently modify the next
        child's fadein_duration property."""
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

        assert c2.fadein_duration == 0


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
