"""Test that removing a nested GroupCue reparents its children
to the surviving grandparent QTreeWidgetItem, not to top-level.

The test builds the QTreeWidget structure directly (bypassing
__cueAdded, which currently places all GroupCues at top-level)
and calls __cueRemoved directly to isolate the reparenting logic.
"""
import pytest

from lisp.cues.cue import Cue
from lisp.cues.cue_model import CueModel
from lisp.plugins.action_cues.group_cue import GroupCue
from lisp.plugins.list_layout.list_view import CueListView, CueTreeWidgetItem
from lisp.plugins.list_layout.models import CueListModel
from lisp.ui.icons import IconTheme


@pytest.fixture(autouse=True)
def _icon_theme():
    """List-column widgets pull icons via IconTheme at construction."""
    if IconTheme._GlobalTheme is None:
        IconTheme.set_theme_name("lisp")
    yield


@pytest.fixture
def bare_view(qapp, mock_app):
    """A CueListView connected to an empty model."""
    cue_model = CueModel()
    list_model = CueListModel(cue_model)
    mock_app.cue_model = cue_model
    view = CueListView(list_model)
    yield view, mock_app


def _build_nested_tree(view, mock_app):
    """Build outer -> inner -> leaf directly in the QTreeWidget.

    Returns (outer_group, inner_group, leaf_cue,
             outer_item, inner_item, leaf_item).

    All three cues are real objects (GroupCue / Cue) so that
    __setupItemWidgets (called during __cueRemoved) can construct
    list column widgets without TypeError.

    We bypass __cueAdded deliberately: that method always places
    GroupCues at top-level (nested GroupCue support is a future
    change). Here we care only about __cueRemoved's reparenting
    logic, so we build the tree manually.
    """
    outer = GroupCue(id="outer", app=mock_app)
    inner = GroupCue(id="inner", app=mock_app)
    inner.group_id = outer.id
    leaf = Cue(id="leaf", app=mock_app)
    leaf.group_id = inner.id
    leaf.index = 0

    # Build QTreeWidgetItems manually
    outer_item = CueTreeWidgetItem(outer)
    inner_item = CueTreeWidgetItem(inner)
    leaf_item = CueTreeWidgetItem(leaf)

    # Insert outer at top-level; nest inner under outer; leaf under inner
    view.insertTopLevelItem(0, outer_item)
    outer_item.insertChild(0, inner_item)
    inner_item.insertChild(0, leaf_item)

    # Populate _group_items as __cueAdded would
    view._group_items[outer.id] = outer_item
    view._group_items[inner.id] = inner_item

    # Wire the signal connections that __cueRemoved will disconnect
    inner.property_changed.connect(
        view._CueListView__cuePropChanged
    )
    inner.started.connect(view._CueListView__groupStarted)

    return outer, inner, leaf, outer_item, inner_item, leaf_item


def test_removing_nested_group_reparents_children_to_grandparent(
    bare_view, qapp
):
    """Build outer -> inner -> leaf; remove inner. Leaf must
    appear under the outer item, not at top-level."""
    view, mock_app = bare_view

    (
        outer, inner, leaf,
        outer_item, inner_item, leaf_item,
    ) = _build_nested_tree(view, mock_app)

    # Sanity-check the initial structure
    assert inner_item.parent() is outer_item
    assert outer_item.indexOfChild(inner_item) == 0
    assert inner_item.indexOfChild(leaf_item) == 0

    # Call __cueRemoved on inner directly (name-mangled method)
    view._CueListView__cueRemoved(inner)

    # leaf_item should now live under outer_item, not at top-level
    assert leaf_item.parent() is outer_item, (
        f"expected leaf to be under outer ({outer.id}); "
        f"parent is {leaf_item.parent()}"
    )
    # Confirm leaf is not also at top-level
    top_ids = {
        view.topLevelItem(i).cue.id
        for i in range(view.topLevelItemCount())
    }
    assert leaf.id not in top_ids, (
        f"leaf ({leaf.id}) appeared at top-level unexpectedly; "
        f"top-level cue ids: {top_ids}"
    )
    # inner group item must be gone from _group_items
    assert inner.id not in view._group_items


def test_removing_top_level_group_still_reparents_to_top(
    bare_view, qapp
):
    """Removing a top-level GroupCue must still send its children
    to top-level (the original behavior must be preserved)."""
    view, mock_app = bare_view

    group = GroupCue(id="tlg", app=mock_app)
    leaf = Cue(id="tl_leaf", app=mock_app)
    leaf.group_id = group.id
    leaf.index = 0

    group_item = CueTreeWidgetItem(group)
    leaf_item = CueTreeWidgetItem(leaf)
    view.insertTopLevelItem(0, group_item)
    group_item.insertChild(0, leaf_item)
    view._group_items[group.id] = group_item

    group.property_changed.connect(view._CueListView__cuePropChanged)
    group.started.connect(view._CueListView__groupStarted)

    view._CueListView__cueRemoved(group)

    # leaf must now be at top-level
    top_ids = {
        view.topLevelItem(i).cue.id
        for i in range(view.topLevelItemCount())
    }
    assert leaf.id in top_ids, (
        f"leaf ({leaf.id}) not found at top-level; "
        f"top-level ids: {top_ids}"
    )
    assert leaf_item.parent() is None
