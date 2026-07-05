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

from unittest.mock import MagicMock, patch

import pytest

from lisp.cues.cue import Cue
from lisp.cues.cue_model import CueModel
from lisp.plugins.list_layout.list_view import CueListView
from lisp.plugins.list_layout.models import CueListModel
from lisp.ui.icons import IconTheme


@pytest.fixture(autouse=True)
def _icon_theme():
    if IconTheme._GlobalTheme is None:
        IconTheme.set_theme_name("lisp")
    yield


def _build_view_with_cues(mock_app, count):
    cue_model = CueModel()
    list_model = CueListModel(cue_model)
    mock_app.cue_model = cue_model

    fake_app = MagicMock()
    fake_app.pre_arm_manager = None

    with patch(
        "lisp.plugins.list_layout.list_view.Application",
        return_value=fake_app,
    ):
        view = CueListView(list_model)

    cues = []
    for i in range(count):
        cue = Cue(id=f"c{i}", app=mock_app)
        cue.name = f"Cue {i}"
        cue_model.add(cue)
        cues.append(cue)
    return view, cues


def _name_css(view, item):
    # Column 3 is the NameWidget (a QLabel). Its stylesheet carries the
    # dim colour when the row is de-emphasised.
    return view.itemWidget(item, 3).styleSheet()


class TestSearchDim:
    def test_non_match_is_dimmed_and_match_is_not(self, mock_app):
        view, cues = _build_view_with_cues(mock_app, 3)
        # Match only c1.
        view.set_search_dim({"c1"}, active=True)

        match_item = view.cueItemAt(1)
        other_item = view.cueItemAt(0)
        assert "160, 160, 160" in _name_css(view, other_item)
        assert "160, 160, 160" not in _name_css(view, match_item)

    def test_clear_restores_all_rows(self, mock_app):
        view, cues = _build_view_with_cues(mock_app, 3)
        view.set_search_dim({"c1"}, active=True)
        view.set_search_dim(set(), active=False)

        for i in range(3):
            item = view.cueItemAt(i)
            assert "160, 160, 160" not in _name_css(view, item)
