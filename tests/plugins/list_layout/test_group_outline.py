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

"""Unit tests for group outline rendering in CueListView."""

import pytest

from lisp.cues.cue import Cue
from lisp.cues.cue_model import CueModel
from lisp.plugins.action_cues.group_cue import GroupCue
from lisp.plugins.list_layout.list_view import CueListView
from lisp.plugins.list_layout.models import CueListModel
from lisp.ui.icons import IconTheme


@pytest.fixture(autouse=True)
def _icon_theme():
    """List-column widgets pull icons via IconTheme at construction."""
    if IconTheme._GlobalTheme is None:
        IconTheme.set_theme_name("lisp")
    yield


def _build_view_with_group(mock_app, child_count=2, group_mode="parallel"):
    """Build a CueListView containing one GroupCue with N children.

    Returns (view, group_item).
    """
    cue_model = CueModel()
    list_model = CueListModel(cue_model)
    mock_app.cue_model = cue_model

    view = CueListView(list_model)

    group = GroupCue(id="g", app=mock_app)
    group.group_mode = group_mode
    cue_model.add(group)

    for i in range(child_count):
        child = Cue(id=f"c{i}", app=mock_app)
        child.group_id = "g"
        cue_model.add(child)

    group_item = view._group_items[group.id]
    return view, group_item


class TestGroupOutlineColors:
    def test_parallel_mode_maps_to_green(self):
        color = CueListView.GROUP_OUTLINE_COLORS.get("parallel")
        assert color is not None
        assert color.green() > color.red()
        assert color.green() > color.blue()

    def test_playlist_mode_maps_to_orange(self):
        color = CueListView.GROUP_OUTLINE_COLORS.get("playlist")
        assert color is not None
        # Orange: red dominant, some green, little blue
        assert color.red() > color.blue()
        assert color.green() > color.blue()

    def test_unknown_mode_returns_none(self):
        assert CueListView.GROUP_OUTLINE_COLORS.get("nonsense") is None


class TestGroupOutlineRect:
    """_groupOutlineRect returns the paint rectangle for a group."""

    def test_empty_visual_rect_returns_none(
        self, qapp, mock_app, monkeypatch,
    ):
        """If visualItemRect ever returns an empty rect (Qt's sentinel
        for 'layout not computed'), the helper returns None so
        paintEvent skips rather than drawing garbage."""
        from PyQt5.QtCore import QRect
        view, group_item = _build_view_with_group(mock_app)
        monkeypatch.setattr(
            view, "visualItemRect", lambda _item: QRect()
        )
        assert view._groupOutlineRect(group_item) is None

    def test_expanded_group_spans_header_plus_children(
        self, qapp, qtbot, mock_app,
    ):
        view, group_item = _build_view_with_group(mock_app, child_count=2)
        group_item.setExpanded(True)
        view.resize(600, 400)
        qtbot.addWidget(view)
        view.show()
        qtbot.waitExposed(view)

        rect = view._groupOutlineRect(group_item)
        header_rect = view.visualItemRect(group_item)
        last_child_rect = view.visualItemRect(
            group_item.child(group_item.childCount() - 1)
        )

        assert rect is not None
        # Rect should extend from near the header top to near the last
        # child bottom (exact values shift by the inset, so compare with
        # tolerance of a few pixels).
        assert abs(rect.top() - header_rect.top()) <= 3
        assert abs(rect.bottom() - last_child_rect.bottom()) <= 3

    def test_collapsed_group_is_header_only(
        self, qapp, qtbot, mock_app,
    ):
        view, group_item = _build_view_with_group(mock_app, child_count=2)
        group_item.setExpanded(False)
        view.resize(600, 400)
        qtbot.addWidget(view)
        view.show()
        qtbot.waitExposed(view)

        rect = view._groupOutlineRect(group_item)
        header_rect = view.visualItemRect(group_item)

        assert rect is not None
        # Rect height should be approximately the header row height.
        assert abs(rect.height() - header_rect.height()) <= 5

    def test_empty_group_is_header_only(
        self, qapp, qtbot, mock_app,
    ):
        view, group_item = _build_view_with_group(mock_app, child_count=0)
        group_item.setExpanded(True)
        view.resize(600, 400)
        qtbot.addWidget(view)
        view.show()
        qtbot.waitExposed(view)

        rect = view._groupOutlineRect(group_item)
        header_rect = view.visualItemRect(group_item)

        assert rect is not None
        assert abs(rect.height() - header_rect.height()) <= 5
