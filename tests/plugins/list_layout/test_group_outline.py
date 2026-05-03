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

    def test_nested_expanded_outer_spans_to_grandchild(
        self, qapp, qtbot, mock_app,
    ):
        """An expanded outer group containing an expanded inner
        group must span all the way down to the inner group's
        last visible leaf, not stop at the inner group's header.
        Otherwise the outer outline visibly cuts off mid-tree."""
        cue_model = CueModel()
        list_model = CueListModel(cue_model)
        mock_app.cue_model = cue_model

        view = CueListView(list_model)

        outer = GroupCue(id="outer", app=mock_app)
        cue_model.add(outer)
        inner = GroupCue(id="inner", app=mock_app)
        inner.group_id = "outer"
        cue_model.add(inner)
        leaf = Cue(id="leaf", app=mock_app)
        leaf.group_id = "inner"
        cue_model.add(leaf)

        outer_item = view._group_items["outer"]
        inner_item = view._group_items["inner"]
        outer_item.setExpanded(True)
        inner_item.setExpanded(True)

        view.resize(600, 400)
        qtbot.addWidget(view)
        view.show()
        qtbot.waitExposed(view)

        rect = view._groupOutlineRect(outer_item)
        leaf_item = inner_item.child(0)
        leaf_rect = view.visualItemRect(leaf_item)

        assert rect is not None
        # The outer outline's bottom must align with the deepest
        # visible leaf, not with the inner group's header.
        assert abs(rect.bottom() - leaf_rect.bottom()) <= 3, (
            f"outer rect bottom {rect.bottom()} should align with "
            f"leaf bottom {leaf_rect.bottom()}, not with inner "
            f"header bottom {view.visualItemRect(inner_item).bottom()}"
        )

    def test_nested_collapsed_inner_stops_at_inner_header(
        self, qapp, qtbot, mock_app,
    ):
        """When the inner group is collapsed, the outer outline
        should extend only to the inner group's header — the
        inner's children aren't visible, so neither should the
        outer's box include their (hidden) rows."""
        cue_model = CueModel()
        list_model = CueListModel(cue_model)
        mock_app.cue_model = cue_model

        view = CueListView(list_model)

        outer = GroupCue(id="outer", app=mock_app)
        cue_model.add(outer)
        inner = GroupCue(id="inner", app=mock_app)
        inner.group_id = "outer"
        cue_model.add(inner)
        leaf = Cue(id="leaf", app=mock_app)
        leaf.group_id = "inner"
        cue_model.add(leaf)

        outer_item = view._group_items["outer"]
        inner_item = view._group_items["inner"]
        outer_item.setExpanded(True)
        inner_item.setExpanded(False)

        view.resize(600, 400)
        qtbot.addWidget(view)
        view.show()
        qtbot.waitExposed(view)

        rect = view._groupOutlineRect(outer_item)
        inner_rect = view.visualItemRect(inner_item)

        assert rect is not None
        assert abs(rect.bottom() - inner_rect.bottom()) <= 3


class TestGroupOutlinePaint:
    """paintEvent must not raise when a group is visible."""

    def test_paint_with_parallel_group_does_not_crash(
        self, qapp, qtbot, mock_app,
    ):
        view, group_item = _build_view_with_group(
            mock_app, child_count=2, group_mode="parallel",
        )
        group_item.setExpanded(True)
        view.resize(600, 400)
        qtbot.addWidget(view)
        view.show()
        qtbot.waitExposed(view)

        # Force a repaint. If paintEvent raises, this crashes the test.
        view.viewport().repaint()

    def test_paint_with_unknown_mode_does_not_crash(
        self, qapp, qtbot, mock_app,
    ):
        """Groups with modes outside the colour map must not break paint."""
        view, group_item = _build_view_with_group(mock_app, child_count=1)
        group_item.cue.group_mode = "future_mode_xyz"
        view.resize(600, 400)
        qtbot.addWidget(view)
        view.show()
        qtbot.waitExposed(view)

        view.viewport().repaint()

    def test_paint_with_collapsed_group_does_not_crash(
        self, qapp, qtbot, mock_app,
    ):
        view, group_item = _build_view_with_group(mock_app, child_count=3)
        group_item.setExpanded(False)
        view.resize(600, 400)
        qtbot.addWidget(view)
        view.show()
        qtbot.waitExposed(view)

        view.viewport().repaint()


class TestGroupOutlineRepaints:
    """Changes that affect the outline must invalidate the viewport."""

    def test_group_mode_change_triggers_repaint(
        self, qapp, qtbot, mock_app, monkeypatch,
    ):
        view, group_item = _build_view_with_group(
            mock_app, child_count=1, group_mode="parallel",
        )
        view.resize(600, 400)
        qtbot.addWidget(view)
        view.show()
        qtbot.waitExposed(view)

        calls = []
        real_update = view.viewport().update
        monkeypatch.setattr(
            view.viewport(), "update",
            lambda *a, **kw: (calls.append(1), real_update(*a, **kw))[1],
        )

        group_item.cue.group_mode = "playlist"

        assert calls, (
            "viewport().update() should be called on group_mode change"
        )

    def test_expand_triggers_repaint(
        self, qapp, qtbot, mock_app, monkeypatch,
    ):
        view, group_item = _build_view_with_group(mock_app, child_count=2)
        group_item.setExpanded(False)
        view.resize(600, 400)
        qtbot.addWidget(view)
        view.show()
        qtbot.waitExposed(view)

        calls = []
        real_update = view.viewport().update
        monkeypatch.setattr(
            view.viewport(), "update",
            lambda *a, **kw: (calls.append(1), real_update(*a, **kw))[1],
        )

        group_item.setExpanded(True)

        assert calls, "viewport().update() should be called on expand"

    def test_collapse_triggers_repaint(
        self, qapp, qtbot, mock_app, monkeypatch,
    ):
        view, group_item = _build_view_with_group(mock_app, child_count=2)
        group_item.setExpanded(True)
        view.resize(600, 400)
        qtbot.addWidget(view)
        view.show()
        qtbot.waitExposed(view)

        calls = []
        real_update = view.viewport().update
        monkeypatch.setattr(
            view.viewport(), "update",
            lambda *a, **kw: (calls.append(1), real_update(*a, **kw))[1],
        )

        group_item.setExpanded(False)

        assert calls, "viewport().update() should be called on collapse"
