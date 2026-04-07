from unittest.mock import MagicMock, patch

import pytest

from lisp.cues.cue_model import CueModel


@pytest.fixture
def mock_app():
    app = MagicMock()
    app.cue_model = CueModel()
    return app


@pytest.fixture
def mock_list_model():
    model = MagicMock()
    return model


def _make_cue(cue_id, index=0, group_id=""):
    cue = MagicMock()
    cue.id = cue_id
    cue.index = index
    cue.group_id = group_id
    cue.CueActions = ()
    return cue


class TestGroupCuesCommand:
    def test_do_creates_group_and_sets_children(
        self, mock_app, mock_list_model
    ):
        from lisp.command.group import GroupCuesCommand

        c1 = _make_cue("c1", index=0)
        c2 = _make_cue("c2", index=1)
        mock_app.cue_model.add(c1)
        mock_app.cue_model.add(c2)

        cmd = GroupCuesCommand(mock_app, mock_list_model, [c1, c2])
        cmd.do()

        # Children should have group_id set
        assert c1.group_id == cmd._group_cue.id
        assert c2.group_id == cmd._group_cue.id

        # Group cue should be in the model
        assert mock_app.cue_model.get(cmd._group_cue.id) is not None

        # Group cue should list both children
        assert cmd._group_cue.children == ["c1", "c2"]

    def test_undo_restores_group_ids(
        self, mock_app, mock_list_model
    ):
        from lisp.command.group import GroupCuesCommand

        c1 = _make_cue("c1", index=0)
        c2 = _make_cue("c2", index=1)
        mock_app.cue_model.add(c1)
        mock_app.cue_model.add(c2)

        cmd = GroupCuesCommand(mock_app, mock_list_model, [c1, c2])
        cmd.do()
        group_id = cmd._group_cue.id
        cmd.undo()

        assert c1.group_id == ""
        assert c2.group_id == ""
        assert mock_app.cue_model.get(group_id) is None

    def test_redo_reuses_same_group_cue(
        self, mock_app, mock_list_model
    ):
        from lisp.command.group import GroupCuesCommand

        c1 = _make_cue("c1", index=0)
        mock_app.cue_model.add(c1)

        cmd = GroupCuesCommand(mock_app, mock_list_model, [c1])
        cmd.do()
        first_id = cmd._group_cue.id
        cmd.undo()
        cmd.redo()
        second_id = cmd._group_cue.id

        assert first_id == second_id

    def test_children_sorted_by_index(
        self, mock_app, mock_list_model
    ):
        from lisp.command.group import GroupCuesCommand

        c1 = _make_cue("c1", index=3)
        c2 = _make_cue("c2", index=1)
        c3 = _make_cue("c3", index=5)
        mock_app.cue_model.add(c1)
        mock_app.cue_model.add(c2)
        mock_app.cue_model.add(c3)

        cmd = GroupCuesCommand(
            mock_app, mock_list_model, [c1, c2, c3]
        )
        # Children should be sorted by index
        assert cmd._child_ids == ["c2", "c1", "c3"]


class TestUngroupCuesCommand:
    def test_do_clears_group_ids(
        self, mock_app, mock_list_model
    ):
        from lisp.command.group import (
            GroupCuesCommand,
            UngroupCuesCommand,
        )

        c1 = _make_cue("c1", index=0)
        c2 = _make_cue("c2", index=1)
        mock_app.cue_model.add(c1)
        mock_app.cue_model.add(c2)

        group_cmd = GroupCuesCommand(
            mock_app, mock_list_model, [c1, c2]
        )
        group_cmd.do()
        group_cue = group_cmd._group_cue

        ungroup_cmd = UngroupCuesCommand(
            mock_app, mock_list_model, group_cue
        )
        ungroup_cmd.do()

        assert c1.group_id == ""
        assert c2.group_id == ""
        assert mock_app.cue_model.get(group_cue.id) is None

    def test_undo_restores_group(
        self, mock_app, mock_list_model
    ):
        from lisp.command.group import (
            GroupCuesCommand,
            UngroupCuesCommand,
        )

        c1 = _make_cue("c1", index=0)
        mock_app.cue_model.add(c1)

        group_cmd = GroupCuesCommand(
            mock_app, mock_list_model, [c1]
        )
        group_cmd.do()
        group_cue = group_cmd._group_cue

        ungroup_cmd = UngroupCuesCommand(
            mock_app, mock_list_model, group_cue
        )
        ungroup_cmd.do()
        ungroup_cmd.undo()

        assert c1.group_id == group_cue.id
        assert mock_app.cue_model.get(group_cue.id) is group_cue
