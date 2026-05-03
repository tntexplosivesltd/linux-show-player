from unittest.mock import MagicMock, patch

import pytest

from lisp.cues.cue_model import CueModel


@pytest.fixture
def mock_app():
    app = MagicMock()
    app.cue_model = CueModel()
    # Default: cue_factory returns a fresh, well-formed mock
    # GroupCue with group_id="" each call. Tests that need
    # specific ids can override .side_effect explicitly.
    _counter = {"n": 0}

    def _make_group(*args, **kwargs):
        _counter["n"] += 1
        cue = MagicMock()
        cue.id = f"grp_{_counter['n']}"
        cue.group_id = ""
        cue.children = []
        cue.CueActions = ()
        return cue

    app.cue_factory.create_cue.side_effect = _make_group
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

    def test_ungroup_nested_promotes_to_grandparent(
        self, mock_app, mock_list_model
    ):
        """When the dissolved group itself has a parent, its
        children's group_id should become the grandparent's id,
        not the empty string."""
        from lisp.command.group import (
            GroupCuesCommand,
            UngroupCuesCommand,
        )

        # Return distinct group-cue mocks for each factory call so
        # two GroupCuesCommand instances don't share the same object.
        mock_app.cue_factory.create_cue.side_effect = [
            _make_cue("inner_grp", index=0),
            _make_cue("outer_grp", index=0),
        ]

        # Build outer group with one inner group, inner group with
        # one child. After ungrouping the inner group, the child
        # should remain inside outer.
        leaf = _make_cue("leaf", index=2)
        mock_app.cue_model.add(leaf)

        # Group [leaf] -> inner_group
        inner_cmd = GroupCuesCommand(
            mock_app, mock_list_model, [leaf]
        )
        inner_cmd.do()
        inner_group = inner_cmd._group_cue

        # Group [inner_group] -> outer_group
        outer_cmd = GroupCuesCommand(
            mock_app, mock_list_model, [inner_group]
        )
        outer_cmd.do()
        outer_group = outer_cmd._group_cue

        # Sanity: at this point inner.group_id == outer.id and
        # leaf.group_id == inner.id
        assert inner_group.group_id == outer_group.id
        assert leaf.group_id == inner_group.id

        # Now ungroup inner_group; leaf should become a child of
        # outer_group, not top-level.
        ungroup_cmd = UngroupCuesCommand(
            mock_app, mock_list_model, inner_group
        )
        ungroup_cmd.do()

        assert leaf.group_id == outer_group.id, (
            f"expected leaf.group_id={outer_group.id!r} "
            f"(grandparent), got {leaf.group_id!r}"
        )
        assert mock_app.cue_model.get(inner_group.id) is None

    def test_ungroup_nested_undo_restores_chain(
        self, mock_app, mock_list_model
    ):
        """Undoing the ungroup must restore both the inner group
        and the original parent->child link."""
        from lisp.command.group import (
            GroupCuesCommand,
            UngroupCuesCommand,
        )

        # Return distinct group-cue mocks for each factory call so
        # two GroupCuesCommand instances don't share the same object.
        mock_app.cue_factory.create_cue.side_effect = [
            _make_cue("inner_grp2", index=0),
            _make_cue("outer_grp2", index=0),
        ]

        leaf = _make_cue("leaf2", index=0)
        mock_app.cue_model.add(leaf)

        inner_cmd = GroupCuesCommand(
            mock_app, mock_list_model, [leaf]
        )
        inner_cmd.do()
        inner_group = inner_cmd._group_cue

        outer_cmd = GroupCuesCommand(
            mock_app, mock_list_model, [inner_group]
        )
        outer_cmd.do()
        outer_group = outer_cmd._group_cue

        ungroup_cmd = UngroupCuesCommand(
            mock_app, mock_list_model, inner_group
        )
        ungroup_cmd.do()
        ungroup_cmd.undo()

        # undo() restores: inner_group back in the model, and
        # leaf's group_id back to inner_group.id. inner_group's
        # own group_id is never mutated by do() — the third
        # assertion documents that invariant rather than testing
        # an undo() side effect.
        assert mock_app.cue_model.get(inner_group.id) is inner_group
        assert leaf.group_id == inner_group.id
        assert inner_group.group_id == outer_group.id
