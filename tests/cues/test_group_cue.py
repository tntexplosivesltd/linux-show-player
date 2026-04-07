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
