import pytest
from unittest.mock import MagicMock

from lisp.cues.cue_model import CueModel
from lisp.cues.cue import CueAction


def _make_cue(cue_id="cue-1", group_id=""):
    cue = MagicMock()
    cue.id = cue_id
    cue.group_id = group_id
    cue.CueActions = (CueAction.Start,)
    return cue


class TestCueModelAdd:
    def test_add(self):
        model = CueModel()
        cue = _make_cue()
        model.add(cue)
        assert cue in model
        assert len(model) == 1

    def test_add_duplicate_raises(self):
        model = CueModel()
        cue = _make_cue()
        model.add(cue)
        with pytest.raises(ValueError):
            model.add(cue)

    def test_add_emits_signal(self):
        model = CueModel()
        added = []

        def on_added(c):
            added.append(c)

        model.item_added.connect(on_added)
        cue = _make_cue()
        model.add(cue)
        assert added == [cue]


class TestCueModelGet:
    def test_get_existing(self):
        model = CueModel()
        cue = _make_cue("abc")
        model.add(cue)
        assert model.get("abc") is cue

    def test_get_missing_returns_default(self):
        model = CueModel()
        assert model.get("missing") is None
        assert model.get("missing", "fallback") == "fallback"


class TestCueModelRemove:
    def test_remove(self):
        model = CueModel()
        cue = _make_cue()
        model.add(cue)
        model.remove(cue)
        assert cue not in model
        assert len(model) == 0

    def test_remove_emits_signal(self):
        model = CueModel()
        removed = []

        def on_removed(c):
            removed.append(c)

        model.item_removed.connect(on_removed)
        cue = _make_cue()
        model.add(cue)
        model.remove(cue)
        assert removed == [cue]


class TestCueModelPop:
    def test_pop_returns_cue(self):
        model = CueModel()
        cue = _make_cue("x")
        model.add(cue)
        popped = model.pop("x")
        assert popped is cue

    def test_pop_calls_interrupt(self):
        model = CueModel()
        cue = _make_cue()
        cue.CueActions = (CueAction.Interrupt,)
        model.add(cue)
        model.pop(cue.id)
        cue.interrupt.assert_called_once()

    def test_pop_calls_stop_if_no_interrupt(self):
        model = CueModel()
        cue = _make_cue()
        cue.CueActions = (CueAction.Stop,)
        model.add(cue)
        model.pop(cue.id)
        cue.stop.assert_called_once()

    def test_pop_promotes_children_to_dissolved_parent(self):
        """When a cue is removed, any cue whose group_id pointed at
        it must have its group_id retargeted to the removed cue's
        own group_id. Otherwise children become orphans pointing at
        a dead id, which survives session save/load and breaks
        nested-group hierarchies."""
        model = CueModel()
        outer = _make_cue("outer", group_id="")
        inner = _make_cue("inner", group_id="outer")
        leaf = _make_cue("leaf", group_id="inner")
        model.add(outer)
        model.add(inner)
        model.add(leaf)

        model.pop("inner")

        assert leaf.group_id == "outer", (
            f"expected leaf.group_id='outer' (grandparent), got "
            f"{leaf.group_id!r}"
        )

    def test_pop_promotes_children_to_top_when_parent_was_top(self):
        """Removing a top-level group should set its children's
        group_id to '' (top-level), preserving the legacy invariant."""
        model = CueModel()
        group = _make_cue("g", group_id="")
        child = _make_cue("c", group_id="g")
        model.add(group)
        model.add(child)

        model.pop("g")

        assert child.group_id == ""

    def test_pop_leaf_does_not_touch_unrelated_cues(self):
        """Popping a non-group cue must not mutate any other cue's
        group_id, since no cue points at the removed leaf."""
        model = CueModel()
        leaf = _make_cue("leaf", group_id="")
        sibling = _make_cue("sibling", group_id="")
        model.add(leaf)
        model.add(sibling)

        model.pop("leaf")

        assert sibling.group_id == ""


class TestCueModelReset:
    def test_reset_clears(self):
        model = CueModel()
        model.add(_make_cue("a"))
        model.add(_make_cue("b"))
        model.reset()
        assert len(model) == 0

    def test_reset_emits_signal(self):
        model = CueModel()
        reset_called = []

        def on_reset():
            reset_called.append(True)

        model.model_reset.connect(on_reset)
        model.reset()
        assert reset_called == [True]


class TestCueModelIteration:
    def test_iter(self):
        model = CueModel()
        c1, c2 = _make_cue("a"), _make_cue("b")
        model.add(c1)
        model.add(c2)
        assert set(model) == {c1, c2}

    def test_len(self):
        model = CueModel()
        assert len(model) == 0
        model.add(_make_cue())
        assert len(model) == 1

    def test_contains(self):
        model = CueModel()
        cue = _make_cue()
        assert cue not in model
        model.add(cue)
        assert cue in model

    def test_items(self):
        model = CueModel()
        cue = _make_cue("id1")
        model.add(cue)
        assert ("id1", cue) in model.items()

    def test_keys(self):
        model = CueModel()
        cue = _make_cue("id1")
        model.add(cue)
        assert "id1" in model.keys()


class TestCueModelFilter:
    def test_filter_default_returns_nothing_for_mocks(self):
        model = CueModel()
        cue = _make_cue()
        model.add(cue)
        # Default filter is Cue class; MagicMock is not a Cue subclass
        results = list(model.filter())
        assert len(results) == 0
