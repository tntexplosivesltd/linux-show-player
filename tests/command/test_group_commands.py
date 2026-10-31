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

    def test_ungroup_nested_splices_grandparent_children_list(
        self, mock_app, mock_list_model
    ):
        """The real playback invariant behind C1.

        GroupCue playback iterates the group's own explicit
        `children` id list (`_resolve_children`), NOT the set of
        cues whose `group_id` points at it. So promoting a child
        by only rewriting `group_id` (what the other tests assert)
        silently drops it from the grandparent's playback: the dead
        inner-group id stays in `children` and the promoted id never
        gets added. Assert the list itself and `_resolve_children`.
        """
        from lisp.command.group import (
            GroupCuesCommand,
            UngroupCuesCommand,
        )
        from lisp.plugins.action_cues.group_cue import GroupCue

        # Real GroupCue objects so `children` / `_resolve_children`
        # behave like production, not MagicMock stand-ins.
        mock_app.cue_factory.create_cue.side_effect = [
            GroupCue(mock_app, id="inner_grp3"),
            GroupCue(mock_app, id="outer_grp3"),
        ]

        leaf = _make_cue("leaf3", index=2)
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

        assert outer_group.children == [inner_group.id]

        ungroup_cmd = UngroupCuesCommand(
            mock_app, mock_list_model, inner_group
        )
        ungroup_cmd.do()

        # Pre-existing proxy invariant.
        assert leaf.group_id == outer_group.id
        # C1: the grandparent's explicit children list is spliced —
        # the dead inner id is replaced by the promoted child id.
        assert outer_group.children == [leaf.id]
        # ...so playback resolution actually finds the promoted child.
        assert [
            c.id for c in outer_group._resolve_children()
        ] == [leaf.id]

    def test_ungroup_nested_undo_restores_grandparent_children(
        self, mock_app, mock_list_model
    ):
        """Undo must put the dissolved group back into the
        grandparent's `children` list exactly where it was, so a
        redo/undo cycle is lossless for playback resolution too."""
        from lisp.command.group import (
            GroupCuesCommand,
            UngroupCuesCommand,
        )
        from lisp.plugins.action_cues.group_cue import GroupCue

        mock_app.cue_factory.create_cue.side_effect = [
            GroupCue(mock_app, id="inner_grp4"),
            GroupCue(mock_app, id="outer_grp4"),
        ]

        leaf = _make_cue("leaf4", index=2)
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

        assert outer_group.children == [inner_group.id]
        assert [
            c.id for c in outer_group._resolve_children()
        ] == [inner_group.id]

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


def _real_group(app, cue_id, children, group_id=""):
    from lisp.plugins.action_cues.group_cue import GroupCue

    group = GroupCue(app, id=cue_id)
    group.group_id = group_id
    group.children = list(children)
    return group


class TestUngroupSplice:
    """Splice edge cases for UngroupCuesCommand on a nested group,
    built directly in the model with real GroupCue objects so the
    `[:index]`/`[index+1:]` slices and multi-child order are exercised.
    """

    def _build(self, mock_app, inner_children=("a", "b", "c")):
        # outer: [x, inner, y]; inner: inner_children
        outer = _real_group(mock_app, "outer", ["x", "inner", "y"])
        inner = _real_group(
            mock_app, "inner", inner_children, group_id="outer"
        )
        cues = [outer, inner]
        cues += [_make_cue(i, group_id="outer") for i in ("x", "y")]
        cues += [_make_cue(i, group_id="inner") for i in inner_children]
        for cue in cues:
            mock_app.cue_model.add(cue)
        return outer, inner

    def test_multi_child_do_undo_redo(self, mock_app, mock_list_model):
        from lisp.command.group import UngroupCuesCommand

        outer, inner = self._build(mock_app)
        cmd = UngroupCuesCommand(mock_app, mock_list_model, inner)

        cmd.do()
        assert outer.children == ["x", "a", "b", "c", "y"]
        assert [c.id for c in outer._resolve_children()] == [
            "x", "a", "b", "c", "y",
        ]

        cmd.undo()
        assert outer.children == ["x", "inner", "y"]
        assert inner.children == ["a", "b", "c"]
        assert [c.id for c in inner._resolve_children()] == [
            "a", "b", "c",
        ]

        cmd.redo()
        assert outer.children == ["x", "a", "b", "c", "y"]

    def test_empty_inner_group(self, mock_app, mock_list_model):
        from lisp.command.group import UngroupCuesCommand

        outer, inner = self._build(mock_app, inner_children=())
        cmd = UngroupCuesCommand(mock_app, mock_list_model, inner)

        cmd.do()
        assert outer.children == ["x", "y"]
        cmd.undo()
        assert outer.children == ["x", "inner", "y"]

    def test_stragglers_are_spliced_too(self, mock_app, mock_list_model):
        """A cue pointing at the inner group but missing from its list
        is promoted by pop(); it must also land in outer's list, after
        the listed children (same rule as CueModel.pop)."""
        from lisp.command.group import UngroupCuesCommand

        outer, inner = self._build(mock_app, inner_children=("a",))
        mock_app.cue_model.add(_make_cue("stray", group_id="inner"))
        cmd = UngroupCuesCommand(mock_app, mock_list_model, inner)

        cmd.do()

        assert outer.children == ["x", "a", "stray", "y"]
        assert mock_app.cue_model.get("stray").group_id == "outer"

    def test_three_levels_collapses_one_level(
        self, mock_app, mock_list_model
    ):
        from lisp.command.group import UngroupCuesCommand

        top = _real_group(mock_app, "top", ["mid"])
        mid = _real_group(mock_app, "mid", ["low"], group_id="top")
        low = _real_group(mock_app, "low", ["a"], group_id="mid")
        for cue in (top, mid, low, _make_cue("a", group_id="low")):
            mock_app.cue_model.add(cue)

        cmd = UngroupCuesCommand(mock_app, mock_list_model, mid)
        cmd.do()

        assert top.children == ["low"]
        assert low.group_id == "top"
        assert [c.id for c in low._resolve_children()] == ["a"]

        cmd.undo()
        assert top.children == ["mid"]
        assert mid.children == ["low"]
        assert low.group_id == "mid"

    def test_redo_that_skips_splice_does_not_reuse_stale_snapshot(
        self, mock_app, mock_list_model
    ):
        """If a redo() finds the group id no longer in the parent's
        list, undo() must not write back the snapshot taken in an
        earlier do()."""
        from lisp.command.group import UngroupCuesCommand

        outer, inner = self._build(mock_app, inner_children=("a",))
        cmd = UngroupCuesCommand(mock_app, mock_list_model, inner)
        cmd.do()
        cmd.undo()

        # Something else drops inner from outer's list in between.
        outer.children = ["x", "y"]
        cmd.redo()
        cmd.undo()

        assert outer.children == ["x", "y"]


class TestUngroupCorruptHierarchy:
    def test_two_cycle_never_points_a_cue_at_itself(
        self, mock_app, mock_list_model
    ):
        """Corrupt 2-cycle: G.group_id == C, C.group_id == G, G lists C.
        Ungrouping G must not leave C.group_id == "C"."""
        from lisp.command.group import UngroupCuesCommand

        g = _real_group(mock_app, "G", ["C"], group_id="C")
        c = _real_group(mock_app, "C", ["G"], group_id="G")
        mock_app.cue_model.add(g)
        mock_app.cue_model.add(c)

        UngroupCuesCommand(mock_app, mock_list_model, g).do()

        assert c.group_id != "C"
        assert "C" not in c.children

    def test_appends_when_parent_does_not_list_the_group(
        self, mock_app, mock_list_model
    ):
        from lisp.command.group import UngroupCuesCommand

        outer = _real_group(mock_app, "outer", ["x"])
        inner = _real_group(mock_app, "inner", ["a"], group_id="outer")
        for cue in (outer, inner, _make_cue("x", group_id="outer"),
                    _make_cue("a", group_id="inner")):
            mock_app.cue_model.add(cue)

        cmd = UngroupCuesCommand(mock_app, mock_list_model, inner)
        cmd.do()
        assert outer.children == ["x", "a"]

        cmd.undo()
        assert outer.children == ["x"]


class TestUngroupCorruptChildren:
    def test_unhashable_child_entry_completes(
        self, mock_app, mock_list_model
    ):
        from lisp.command.group import UngroupCuesCommand

        outer = _real_group(mock_app, "outer", ["inner"])
        inner = _real_group(mock_app, "inner", ["a"], group_id="outer")
        a = _make_cue("a", group_id="inner")
        for cue in (outer, inner, a):
            mock_app.cue_model.add(cue)
        inner.children = [["bad"], "a"]

        UngroupCuesCommand(mock_app, mock_list_model, inner).do()

        assert a.group_id == "outer"
        assert outer.children == ["a"]

    def test_self_parented_group_promotes_children_to_top(
        self, mock_app, mock_list_model
    ):
        from lisp.command.group import UngroupCuesCommand

        g = _real_group(mock_app, "G", ["a"], group_id="G")
        a = _make_cue("a", group_id="G")
        mock_app.cue_model.add(g)
        mock_app.cue_model.add(a)

        UngroupCuesCommand(mock_app, mock_list_model, g).do()

        assert a.group_id == ""
