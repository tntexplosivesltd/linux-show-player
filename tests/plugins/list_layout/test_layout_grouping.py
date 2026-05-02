"""Unit tests for ListLayout._group_cues nesting behavior.

These tests exercise the layout-level command path that selects
which cues are valid grouping inputs. They use a real CueModel
plus a real GroupCue instance to verify isinstance behavior, but
mock the layout itself (we only need its `_group_cues` method
and the `app` and `_list_model` attributes).
"""
from unittest.mock import MagicMock

import pytest

from lisp.cues.cue_model import CueModel
from lisp.plugins.action_cues.group_cue import GroupCue


@pytest.fixture
def app_with_model():
    app = MagicMock()
    app.cue_model = CueModel()
    app.commands_stack = MagicMock()
    return app


@pytest.fixture
def layout(app_with_model):
    """A bare object exposing just what _group_cues needs."""
    from lisp.plugins.list_layout.layout import ListLayout

    obj = ListLayout.__new__(ListLayout)
    obj.app = app_with_model
    obj._list_model = MagicMock()
    return obj


def _make_leaf_cue(app, cue_id, group_id=""):
    cue = MagicMock()
    cue.id = cue_id
    cue.group_id = group_id
    cue.index = 0
    app.cue_model.add(cue)
    return cue


def test_group_cues_accepts_groupcue_in_selection(
    layout, app_with_model
):
    """Selecting a GroupCue plus a leaf and grouping should
    produce a parent group containing both — the inner group
    must not be filtered out."""
    inner = GroupCue(app=app_with_model)
    app_with_model.cue_model.add(inner)
    leaf = _make_leaf_cue(app_with_model, "leaf-1")

    layout._group_cues([inner, leaf])

    # Verify the command was pushed to the stack
    assert app_with_model.commands_stack.do.called
    cmd = app_with_model.commands_stack.do.call_args.args[0]
    # The inner group must appear in the new group's children
    assert inner.id in cmd._child_ids
    assert leaf.id in cmd._child_ids


def test_group_cues_drops_descendant_of_selected_group(
    layout, app_with_model
):
    """Existing live-parent filter: a child whose group_id points
    to a live group in the selection is silently dropped, leaving
    only the parent group to be wrapped."""
    inner = GroupCue(app=app_with_model)
    app_with_model.cue_model.add(inner)
    descendant = _make_leaf_cue(
        app_with_model, "desc", group_id=inner.id
    )

    layout._group_cues([inner, descendant])

    assert app_with_model.commands_stack.do.called
    cmd = app_with_model.commands_stack.do.call_args.args[0]
    assert cmd._child_ids == [inner.id]


def test_group_cues_cycle_guard_aborts_on_corrupted_chain(
    layout, app_with_model
):
    """Pathological case: an existing cycle in group_id pointers
    must not crash _group_cues nor produce a command. We build a
    cycle a -> b -> a and pass [a, b]; the filter would let them
    through because their direct parents are 'live', but the
    cycle guard aborts."""
    a = MagicMock()
    a.id = "a"
    a.group_id = "b"  # points at b
    a.index = 0
    b = MagicMock()
    b.id = "b"
    b.group_id = "a"  # points at a -> cycle
    b.index = 1
    app_with_model.cue_model.add(a)
    app_with_model.cue_model.add(b)

    layout._group_cues([a, b])

    assert not app_with_model.commands_stack.do.called
