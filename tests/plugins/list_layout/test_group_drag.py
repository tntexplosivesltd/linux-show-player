# This file is part of Linux Show Player
#
# Copyright 2026 Francesco Ceruti <ceppofrancy@gmail.com>
#
# Linux Show Player is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# Linux Show Player is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Linux Show Player.  If not, see <http://www.gnu.org/licenses/>.

"""Regression test for the group-drag widget-loss bug.

When a GroupCue item is moved (either dragged in the UI or moved via
`layout.move_cue`), the QTreeWidget takes the group subtree out and
re-inserts it at the new position. `setItemWidget`-installed widgets
for the group's tree-children get orphaned during that take/reinsert
cycle and need to be re-created — otherwise clicking a child crashes
with `AttributeError: 'NoneType' object has no attribute
'setStyleSheet'` from `__updateItemStyle`.
"""

import pytest

from lisp.cues.cue import Cue
from lisp.cues.cue_model import CueModel
from lisp.plugins.action_cues.group_cue import GroupCue
from lisp.plugins.list_layout.list_view import CueListView
from lisp.plugins.list_layout.models import CueListModel
from lisp.ui.icons import IconTheme


@pytest.fixture(autouse=True)
def _icon_theme():
    """List-column widgets (CueStatusIcons, NextActionIcon) pull icons
    via IconTheme.get at construction time."""
    if IconTheme._GlobalTheme is None:
        IconTheme.set_theme_name("lisp")
    yield


def _make_group(mock_app, cue_id="g"):
    # id is a WriteOnceProperty — must be set via the constructor.
    return GroupCue(id=cue_id, app=mock_app)


def _make_child(mock_app, cue_id, group_id):
    cue = Cue(id=cue_id, app=mock_app)
    cue.group_id = group_id
    return cue


class TestGroupDragWidgetLoss:
    """Moving a GroupCue must preserve itemWidgets on its tree children."""

    def _build(self, mock_app):
        """Build the model-view pair and return (view, group, children).

        View is constructed before adding cues so it can observe every
        item_added signal (it subscribes in __init__, doesn't enumerate
        an existing model).
        """
        cue_model = CueModel()
        list_model = CueListModel(cue_model)
        mock_app.cue_model = cue_model

        view = CueListView(list_model)

        before = Cue(id="before", app=mock_app)
        group = _make_group(mock_app, "g")
        child_a = _make_child(mock_app, "ca", "g")
        child_b = _make_child(mock_app, "cb", "g")
        after = Cue(id="after", app=mock_app)

        for cue in (before, group, child_a, child_b, after):
            cue_model.add(cue)

        return view, group, [child_a, child_b], list_model

    def test_group_move_preserves_child_widgets(
        self, qapp, mock_app,
    ):
        view, group, children, model = self._build(mock_app)

        # Sanity-check the initial state: every child item has widgets in
        # every column (confirms the bug is about the move, not setup).
        initial_group_item = view._group_items[group.id]
        assert initial_group_item.childCount() == len(children)
        for i in range(initial_group_item.childCount()):
            child_item = initial_group_item.child(i)
            for col in range(view.columnCount()):
                assert view.itemWidget(child_item, col) is not None, (
                    f"initial setup missing column {col} widget"
                )

        # Move the group from index 1 to index 3 (past the children in
        # the flat model, mirroring a user drag).
        model.move(1, 3)

        # After the move, every child's item widgets must still be present.
        group_item = view._group_items[group.id]
        assert group_item.childCount() == len(children), (
            "children count changed unexpectedly"
        )
        for i in range(group_item.childCount()):
            child_item = group_item.child(i)
            for col in range(view.columnCount()):
                widget = view.itemWidget(child_item, col)
                assert widget is not None, (
                    f"child {child_item.cue.id} column {col} "
                    f"lost its widget after group move"
                )

    def test_group_move_leaves_group_item_widgets_intact(
        self, qapp, mock_app,
    ):
        """The moved group's own widgets must also survive — not just
        its children's. The recursion starts at the item itself, so
        `__setupItemWidgets(item)` still runs on the top-level group.
        """
        view, group, _, model = self._build(mock_app)

        model.move(1, 3)

        group_item = view._group_items[group.id]
        for col in range(view.columnCount()):
            assert view.itemWidget(group_item, col) is not None, (
                f"group column {col} widget lost after move"
            )
