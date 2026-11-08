import logging
import threading
import time

import pytest
from unittest.mock import MagicMock, patch

from lisp.cues.cue_model import CueModel
from lisp.cues.cue import Cue, CueAction, CueState


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

    def test_pop_splices_promoted_children_into_grandparent_list(self):
        """C1 safety-net: a direct cue_model.remove of an inner group
        must not only retarget the promoted children's group_id but
        also splice them into the grandparent GroupCue's explicit
        `children` list, replacing the dead inner id. GroupCue
        playback iterates that list (`_resolve_children`), so without
        the splice the promoted children silently stop being playable.
        """
        from lisp.plugins.action_cues.group_cue import GroupCue

        model = CueModel()
        app = MagicMock()
        app.cue_model = model

        outer = GroupCue(app, id="outer")
        inner = GroupCue(app, id="inner")
        leaf = _make_cue("leaf", group_id="inner")

        inner.group_id = "outer"
        inner.children = ["leaf"]
        outer.children = ["inner"]

        model.add(outer)
        model.add(inner)
        model.add(leaf)

        model.pop("inner")

        # Pre-existing group_id promotion.
        assert leaf.group_id == "outer"
        # C1: grandparent's children list is spliced, dead id gone.
        assert outer.children == ["leaf"]
        assert [c.id for c in outer._resolve_children()] == ["leaf"]

    def test_pop_top_level_group_does_not_crash_on_empty_parent(self):
        """Removing a top-level group ("" parent) has no grandparent
        GroupCue to splice — the isinstance guard must no-op cleanly
        rather than trying to index into a non-existent children list.
        """
        from lisp.plugins.action_cues.group_cue import GroupCue

        model = CueModel()
        app = MagicMock()
        app.cue_model = model

        group = GroupCue(app, id="g")
        child = _make_cue("c", group_id="g")
        group.children = ["c"]
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


def _group_cue(app, cue_id, children, group_id=""):
    from lisp.plugins.action_cues.group_cue import GroupCue

    group = GroupCue(app, id=cue_id)
    group.group_id = group_id
    group.children = children
    return group


def _model_app():
    model = CueModel()
    app = MagicMock()
    app.cue_model = model
    return model, app


class TestCueModelPopSplice:
    """Edge cases of the C1 safety-net splice in `CueModel.pop()`."""

    def test_pop_leaf_in_group_leaves_parent_list_alone(self):
        """A leaf has nothing to promote: its parent's children list
        must not change, so a plain re-add (undo) restores playback.
        """
        model, app = _model_app()
        g = _group_cue(app, "g", ["a", "b"])
        a = _make_cue("a", group_id="g")
        b = _make_cue("b", group_id="g")
        for cue in (g, a, b):
            model.add(cue)

        model.pop("a")

        assert g.children == ["a", "b"]
        assert [c.id for c in g._resolve_children()] == ["b"]

    def test_pop_multi_child_group_splices_in_order(self):
        """outer [x, inner, y] + inner [a, b, c] → [x, a, b, c, y]."""
        model, app = _model_app()
        outer = _group_cue(app, "outer", ["x", "inner", "y"])
        inner = _group_cue(app, "inner", ["a", "b", "c"], "outer")
        cues = [outer, inner] + [
            _make_cue(i, group_id="outer") for i in ("x", "y")
        ] + [_make_cue(i, group_id="inner") for i in ("c", "a", "b")]
        for cue in cues:
            model.add(cue)

        model.pop("inner")

        assert outer.children == ["x", "a", "b", "c", "y"]

    def test_pop_empty_group_drops_its_id_from_parent(self):
        model, app = _model_app()
        outer = _group_cue(app, "outer", ["x", "inner", "y"])
        inner = _group_cue(app, "inner", [], "outer")
        for cue in (outer, inner, _make_cue("x", "outer"),
                    _make_cue("y", "outer")):
            model.add(cue)

        model.pop("inner")

        assert outer.children == ["x", "y"]

    def test_pop_skips_stale_child_ids(self):
        """Ids listed in the removed group but no longer in the model
        must not be spliced into the grandparent."""
        model, app = _model_app()
        outer = _group_cue(app, "outer", ["inner"])
        inner = _group_cue(app, "inner", ["gone", "a"], "outer")
        for cue in (outer, inner, _make_cue("a", "inner")):
            model.add(cue)

        model.pop("inner")

        assert outer.children == ["a"]

    def test_pop_appends_stragglers_after_listed_children(self):
        """A cue pointing at the group but missing from its list still
        gets promoted, and spliced after the listed children."""
        model, app = _model_app()
        outer = _group_cue(app, "outer", ["inner"])
        inner = _group_cue(app, "inner", ["a"], "outer")
        for cue in (outer, inner, _make_cue("stray", "inner"),
                    _make_cue("a", "inner")):
            model.add(cue)

        model.pop("inner")

        assert outer.children == ["a", "stray"]

    def test_pop_three_levels_collapses_one_level(self):
        model, app = _model_app()
        top = _group_cue(app, "top", ["mid"])
        mid = _group_cue(app, "mid", ["low"], "top")
        low = _group_cue(app, "low", ["a"], "mid")
        for cue in (top, mid, low, _make_cue("a", "low")):
            model.add(cue)

        model.pop("mid")

        assert top.children == ["low"]
        assert low.group_id == "top"
        assert low.children == ["a"]

    def test_pop_group_id_cycle_does_not_make_group_contain_itself(self):
        """Corrupt session: A.group_id=B, B.group_id=A. Removing A must
        not splice "B" into B's own children list."""
        model, app = _model_app()
        a = _group_cue(app, "A", ["B"], group_id="B")
        b = _group_cue(app, "B", ["A"], group_id="A")
        model.add(a)
        model.add(b)

        model.pop("A")

        assert "B" not in b.children
        assert b.group_id != "B"

    def test_pop_with_malformed_children_does_not_raise(self):
        """A string `children` (corrupt session) must not raise mid-pop
        and leave the model half-updated."""
        model, app = _model_app()
        outer = _group_cue(app, "outer", ["inner"])
        outer.children = "inner"
        inner = _group_cue(app, "inner", ["a"], "outer")
        for cue in (outer, inner, _make_cue("a", "inner")):
            model.add(cue)

        model.pop("inner")

        assert model.get("inner") is None


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

    def test_reset_empty_model(self):
        model = CueModel()
        model.reset()
        assert len(model) == 0


# ---------------------------------------------------------------------------
# Session teardown (Session.finalize -> reset) must halt running cues, as
# pop() does: otherwise they're orphaned, and one held alive (e.g. by a
# running fade) keeps playing and keeps its projection sink. These use
# real cues: `Cue.interrupt`/`stop` run on their own threads, so mocks
# with synchronous methods would test behaviour production doesn't have.
# ---------------------------------------------------------------------------


class _HaltableCue(Cue):
    """A real cue whose interrupt/stop takes `delay` seconds, as
    releasing media or a fade does, and can be held by `release`."""

    CueActions = (CueAction.Start, CueAction.Stop, CueAction.Interrupt)

    def __init__(self, app, id=None, delay=0.05):
        super().__init__(app, id=id)
        self.delay = delay
        self.release = threading.Event()
        self.release.set()
        self.halts = 0

    def _halting(self):
        self.halts += 1
        time.sleep(self.delay)
        self.release.wait()

    def __interrupt__(self, fade=False):
        self._halting()

    def __stop__(self, fade=False):
        self._halting()
        return True


class _StopOnlyCue(_HaltableCue):
    CueActions = (CueAction.Start, CueAction.Stop)


class _NoHaltCue(_HaltableCue):
    CueActions = (CueAction.Start,)


def _active(cls, app, cue_id, state=CueState.Running, **kwargs):
    cue = cls(app, id=cue_id, **kwargs)
    cue._state = state
    return cue


class TestCueModelResetHalts:
    # Running/Pause go through the slow `__interrupt__`, so they pin
    # the wait. PreWait is set to Stop by `Cue.interrupt` itself, so it
    # pins only that PreWait counts as active (an `_ACTIVE` of just
    # Running | Pause would leave it running).
    @pytest.mark.parametrize(
        "state", [CueState.Running, CueState.Pause, CueState.PreWait]
    )
    def test_active_cues_are_stopped_when_reset_returns(
        self, mock_app, state
    ):
        model = CueModel()
        cues = [
            _active(_HaltableCue, mock_app, "a", state),
            _active(_HaltableCue, mock_app, "b", state),
        ]
        for cue in cues:
            model.add(cue)

        model.reset()

        # Not "eventually": reset waits for the halt threads, so the
        # next session never starts alongside the old cues.
        assert [cue.state for cue in cues] == [CueState.Stop] * 2
        assert len(model) == 0

    @pytest.mark.parametrize(
        "state",
        [
            CueState.Stop | CueState.PostWait,
            CueState.Stop | CueState.PostWait_Pause,
            CueState.PreWait_Pause,
        ],
    )
    def test_waiting_cues_have_their_wait_cancelled(self, mock_app, state):
        # A finished cue still counting its post-wait would otherwise
        # fire its follow-up after the session has been replaced.
        model = CueModel()
        cue = _active(_HaltableCue, mock_app, "a", state)
        model.add(cue)

        model.reset()

        assert cue.state == CueState.Stop
        assert len(model) == 0

    def test_cue_without_interrupt_is_stopped(self, mock_app):
        model = CueModel()
        cue = _active(_StopOnlyCue, mock_app, "a")
        model.add(cue)

        model.reset()

        assert cue.state == CueState.Stop
        assert cue.halts == 1

    def test_idle_cues_are_not_halted(self, mock_app):
        model = CueModel()
        idle = _HaltableCue(mock_app, id="idle")
        model.add(idle)

        with patch.object(idle, "interrupt") as interrupt:
            model.reset()

        interrupt.assert_not_called()
        assert len(model) == 0

    def test_cue_with_no_halt_action_is_dropped_without_waiting(
        self, mock_app, monkeypatch
    ):
        monkeypatch.setattr(CueModel, "HALT_TIMEOUT", 5.0)
        model = CueModel()
        model.add(_active(_NoHaltCue, mock_app, "a"))

        started = time.monotonic()
        model.reset()

        assert time.monotonic() - started < 1.0
        assert len(model) == 0

    def test_direct_handlers_still_find_the_cue_in_the_model(
        self, mock_app
    ):
        model = CueModel()
        cue = _active(_HaltableCue, mock_app, "a")
        model.add(cue)
        found = []

        # A named function: signals hold weak references.
        def on_interrupted(c):
            found.append(model.get(c.id) is c)

        cue.interrupted.connect(on_interrupted)
        model.reset()

        assert found == [True]
        assert len(model) == 0

    def test_a_stuck_cue_delays_reset_only_up_to_the_timeout(
        self, mock_app, monkeypatch, caplog
    ):
        monkeypatch.setattr(CueModel, "HALT_TIMEOUT", 0.2)
        model = CueModel()
        stuck = _active(_HaltableCue, mock_app, "stuck")
        stuck.release.clear()
        model.add(stuck)
        try:
            started = time.monotonic()
            with caplog.at_level(logging.WARNING):
                model.reset()
            elapsed = time.monotonic() - started
        finally:
            stuck.release.set()

        assert 0.2 <= elapsed < 1.5
        assert len(model) == 0
        assert "still active" in caplog.text

    def test_a_cue_that_fails_to_halt_does_not_stop_the_rest(
        self, mock_app, caplog
    ):
        model = CueModel()
        bad = _active(_HaltableCue, mock_app, "bad")
        good = _active(_HaltableCue, mock_app, "good")
        model.add(bad)
        model.add(good)
        reset_called = []

        def on_reset():
            reset_called.append(True)

        model.model_reset.connect(on_reset)
        with patch.object(
            bad, "interrupt", side_effect=RuntimeError("boom")
        ), caplog.at_level(logging.ERROR):
            model.reset()

        assert good.state == CueState.Stop
        assert len(model) == 0
        assert reset_called == [True]
        assert "Failed to halt cue 'bad'" in caplog.text

    def test_running_group_and_children_are_all_stopped(self, mock_app):
        # GroupCue.__interrupt__ cascades to its children through
        # app.cue_model, which must still hold them at that point.
        from lisp.plugins.action_cues.group_cue import GroupCue

        model = CueModel()
        app = MagicMock()
        app.cue_model = model
        group = GroupCue(app, id="g")
        children = [
            _active(_HaltableCue, mock_app, f"c{i}") for i in range(2)
        ]
        group.children = [child.id for child in children]
        for child in children:
            child.group_id = "g"
        group._state = CueState.Running
        model.add(group)
        for child in children:
            model.add(child)

        model.reset()

        assert group.state & CueState.IsStopped
        assert [c.state for c in children] == [CueState.Stop] * 2
        assert len(model) == 0


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


class TestCueModelPopSpliceDrift:
    """Sessions whose group_id back-links and children lists have drifted."""

    def test_pop_appends_when_parent_does_not_list_the_group(self):
        """Grandparent doesn't list the dissolved group: the promoted
        children must still land in its playback list (appended), or
        they show nested in the UI but never play -- the C1 symptom."""
        model, app = _model_app()
        outer = _group_cue(app, "outer", ["x"])
        inner = _group_cue(app, "inner", ["a"], "outer")
        for cue in (outer, inner, _make_cue("x", "outer"),
                    _make_cue("a", "inner")):
            model.add(cue)

        model.pop("inner")

        assert outer.children == ["x", "a"]

    def test_pop_never_splices_an_ancestor_into_its_descendant(self):
        """Stale back-link: X lists P, P lists G, but X.group_id == G.
        Removing G promotes X into P; splicing X into P.children would
        create an X -> P -> X playback cycle."""
        model, app = _model_app()
        x = _group_cue(app, "X", ["P"], group_id="G")
        p = _group_cue(app, "P", ["G"], group_id="X")
        g = _group_cue(app, "G", [], group_id="P")
        for cue in (x, p, g):
            model.add(cue)

        model.pop("G")

        assert "X" not in p.children


class TestCorruptChildren:
    def test_group_cue_drops_non_string_child_ids(self):
        """children is sanitised whenever it's set (session load
        included): unhashable/non-str entries are dropped, order kept."""
        _model, app = _model_app()
        g = _group_cue(app, "g", [["bad"], "a", {}, "b", 3])

        assert g.children == ["a", "b"]

    def test_pop_with_unhashable_child_entry_completes(self):
        """Hand-edited children like [["bad"], "a"] must not make pop()
        fail half-way (cue gone, links half-rewritten, no undo)."""
        model, app = _model_app()
        outer = _group_cue(app, "outer", ["inner"])
        inner = _group_cue(app, "inner", ["a"], "outer")
        a = _make_cue("a", "inner")
        for cue in (outer, inner, a):
            model.add(cue)
        inner.children = [["bad"], "a"]

        model.pop("inner")

        assert a.group_id == "outer"
        assert outer.children == ["a"]

    def test_pop_self_parented_group_promotes_children_to_top(self):
        """Corrupt G.group_id == G.id: children must not be left
        pointing at the group that is being removed."""
        model, app = _model_app()
        g = _group_cue(app, "G", ["a"], group_id="G")
        a = _make_cue("a", "G")
        model.add(g)
        model.add(a)

        model.pop("G")

        assert a.group_id == ""
