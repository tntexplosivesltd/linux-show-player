"""RemoveCuesCommand: deleting cues must be losslessly undoable for the
group hierarchy, not just for model membership.

`CueModel.pop()` promotes a removed group's children to its parent
(rewriting their `group_id`) and splices them into the grandparent
GroupCue's explicit `children` list. GroupCue playback iterates that
list (`_resolve_children`), so an undo that only re-adds the removed
cue (what the generic `ModelRemoveItemsCommand` does) leaves cues that
the UI shows inside a group but that never play when the group is
GO'd. These tests assert `children` and `_resolve_children()`, the
playback invariant, not just `group_id`.
"""

from unittest.mock import MagicMock

import pytest

from lisp.cues.cue_model import CueModel


def _leaf(cue_id, group_id=""):
    cue = MagicMock()
    cue.id = cue_id
    cue.group_id = group_id
    cue.CueActions = ()
    return cue


@pytest.fixture
def app():
    app = MagicMock()
    app.cue_model = CueModel()
    return app


def _group(app, cue_id, children, group_id=""):
    from lisp.plugins.action_cues.group_cue import GroupCue

    group = GroupCue(app, id=cue_id)
    group.group_id = group_id
    group.children = list(children)
    return group


def _resolved(group):
    return [c.id for c in group._resolve_children()]


def _remove(app, *cues):
    from lisp.command.group import RemoveCuesCommand

    return RemoveCuesCommand(app.cue_model, *cues)


class TestRemoveLeafFromGroup:
    def test_delete_then_undo_restores_leaf_playback(self, app):
        """The review's repro: g.children=[a, b], delete a, undo →
        a must be back in g.children and resolvable for playback."""
        g = _group(app, "g", ["a", "b"])
        a = _leaf("a", group_id="g")
        b = _leaf("b", group_id="g")
        for cue in (g, a, b):
            app.cue_model.add(cue)

        cmd = _remove(app, a)
        cmd.do()
        assert app.cue_model.get("a") is None

        cmd.undo()

        assert g.children == ["a", "b"]
        assert a.group_id == "g"
        assert _resolved(g) == ["a", "b"]

    def test_delete_leaf_does_not_splice_parent_list(self, app):
        """A leaf has nothing to promote, so the parent's children
        list must be left alone (the dead id is skipped by
        `_resolve_children` and comes back to life on undo)."""
        g = _group(app, "g", ["a", "b"])
        a = _leaf("a", group_id="g")
        b = _leaf("b", group_id="g")
        for cue in (g, a, b):
            app.cue_model.add(cue)

        _remove(app, a).do()

        assert g.children == ["a", "b"]
        assert _resolved(g) == ["b"]


class TestRemoveNestedGroup:
    def _build(self, app):
        # o: [x, i, y]; i: [a, b]
        o = _group(app, "o", ["x", "i", "y"])
        i = _group(app, "i", ["a", "b"], group_id="o")
        x = _leaf("x", group_id="o")
        y = _leaf("y", group_id="o")
        a = _leaf("a", group_id="i")
        b = _leaf("b", group_id="i")
        for cue in (o, x, i, a, b, y):
            app.cue_model.add(cue)
        return o, i, x, y, a, b

    def test_delete_promotes_children_into_grandparent(self, app):
        o, i, x, y, a, b = self._build(app)

        _remove(app, i).do()

        assert o.children == ["x", "a", "b", "y"]
        assert a.group_id == "o" and b.group_id == "o"
        assert _resolved(o) == ["x", "a", "b", "y"]

    def test_undo_restores_full_hierarchy(self, app):
        o, i, x, y, a, b = self._build(app)

        cmd = _remove(app, i)
        cmd.do()
        cmd.undo()

        assert app.cue_model.get("i") is i
        assert o.children == ["x", "i", "y"]
        assert i.children == ["a", "b"]
        assert a.group_id == "i" and b.group_id == "i"
        assert _resolved(o) == ["x", "i", "y"]
        assert _resolved(i) == ["a", "b"]

    def test_redo_after_undo_promotes_again(self, app):
        o, i, x, y, a, b = self._build(app)

        cmd = _remove(app, i)
        cmd.do()
        cmd.undo()
        cmd.redo()

        assert app.cue_model.get("i") is None
        assert o.children == ["x", "a", "b", "y"]
        assert a.group_id == "o" and b.group_id == "o"

    def test_repeated_undo_redo_cycles_are_lossless(self, app):
        o, i, x, y, a, b = self._build(app)

        cmd = _remove(app, i)
        cmd.do()
        for _ in range(3):
            cmd.undo()
            cmd.redo()
        cmd.undo()

        assert o.children == ["x", "i", "y"]
        assert a.group_id == "i" and b.group_id == "i"


class TestRemoveTopLevelGroup:
    def test_undo_restores_children_group_ids(self, app):
        """Pre-existing gap: pop() promotes a top-level group's
        children to "" and a plain re-add never pointed them back."""
        g = _group(app, "g", ["a", "b"])
        a = _leaf("a", group_id="g")
        b = _leaf("b", group_id="g")
        for cue in (g, a, b):
            app.cue_model.add(cue)

        cmd = _remove(app, g)
        cmd.do()
        assert a.group_id == "" and b.group_id == ""

        cmd.undo()

        assert a.group_id == "g" and b.group_id == "g"
        assert _resolved(g) == ["a", "b"]


class TestRemoveMultiple:
    def test_delete_group_and_one_of_its_children(self, app):
        """Removing a group together with one of its children (a
        multi-selection delete) must also undo cleanly."""
        o = _group(app, "o", ["i"])
        i = _group(app, "i", ["a", "b"], group_id="o")
        a = _leaf("a", group_id="i")
        b = _leaf("b", group_id="i")
        for cue in (o, i, a, b):
            app.cue_model.add(cue)

        cmd = _remove(app, i, a)
        cmd.do()
        assert app.cue_model.get("i") is None
        assert app.cue_model.get("a") is None

        cmd.undo()

        assert o.children == ["i"]
        assert i.children == ["a", "b"]
        assert a.group_id == "i" and b.group_id == "i"
        assert _resolved(i) == ["a", "b"]


def _hierarchy(app):
    """Every cue's group_id, each group's children, and what each group
    actually resolves for playback -- the full state undo must restore."""
    from lisp.plugins.action_cues.group_cue import GroupCue

    state = {}
    for cue in app.cue_model:
        entry = {"group_id": cue.group_id}
        if isinstance(cue, GroupCue):
            entry["children"] = list(cue.children)
            entry["resolved"] = _resolved(cue)
        state[cue.id] = entry
    return state


def _three_level(app):
    # t: [x, m, y]; m: [l]; l: [a, b]
    t = _group(app, "t", ["x", "m", "y"])
    m = _group(app, "m", ["l"], group_id="t")
    lo = _group(app, "l", ["a", "b"], group_id="m")
    cues = {"t": t, "m": m, "l": lo}
    cues["x"] = _leaf("x", group_id="t")
    cues["y"] = _leaf("y", group_id="t")
    cues["a"] = _leaf("a", group_id="l")
    cues["b"] = _leaf("b", group_id="l")
    for cue_id in ("t", "x", "m", "l", "a", "b", "y"):
        app.cue_model.add(cues[cue_id])
    return cues


def _siblings(app):
    # g1: [a]; g2: [b, c] -- two top-level groups
    cues = {
        "g1": _group(app, "g1", ["a"]),
        "g2": _group(app, "g2", ["b", "c"]),
        "a": _leaf("a", group_id="g1"),
        "b": _leaf("b", group_id="g2"),
        "c": _leaf("c", group_id="g2"),
    }
    for cue_id in ("g1", "a", "g2", "b", "c"):
        app.cue_model.add(cues[cue_id])
    return cues


@pytest.mark.parametrize(
    "build, delete_ids",
    [
        (_three_level, ["m", "l"]),
        (_three_level, ["l", "m"]),
        (_siblings, ["g1", "g2"]),
        (_siblings, ["g2", "g1"]),
    ],
    ids=["3lvl-outer-first", "3lvl-inner-first", "siblings", "siblings-rev"],
)
def test_multi_group_delete_round_trips(app, build, delete_ids):
    """Deleting several groups in one command, where pop()'s splices
    cascade, must undo/redo/undo back to exactly the starting state."""
    cues = build(app)
    original = _hierarchy(app)

    cmd = _remove(app, *(cues[i] for i in delete_ids))
    cmd.do()
    after_do = _hierarchy(app)
    for cue_id in delete_ids:
        assert app.cue_model.get(cue_id) is None

    cmd.undo()
    assert _hierarchy(app) == original

    cmd.redo()
    assert _hierarchy(app) == after_do

    cmd.undo()
    assert _hierarchy(app) == original


def test_touchable_is_deterministically_ordered(app):
    """Restore order drives property_changed signal order: it must not
    depend on set/hash order. Removed cues first (removal order), then
    the other affected cues in model order."""
    o = _group(app, "o", ["i"])
    i = _group(app, "i", ["a", "b"], group_id="o")
    a = _leaf("a", group_id="i")
    b = _leaf("b", group_id="i")
    for cue in (o, i, a, b):
        app.cue_model.add(cue)

    cmd = _remove(app, i)

    assert [c.id for c in cmd._touchable()] == ["i", "o", "a", "b"]
