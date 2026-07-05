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

"""Controller-level tests for the find & jump state machine.

We don't instantiate a real ``ListLayout`` (that needs the full Qt
object graph); instead we build one via ``__new__`` and wire just the
attributes the find methods touch, mirroring ``test_disabled_skip.py``.
The ``FindBar`` and ``CueListView`` are ``MagicMock`` stand-ins so we
can assert on ``set_search_dim`` / ``setExpanded`` without a display.
"""

from unittest.mock import MagicMock

from lisp.cues.cue import Cue


class _StubModel:
    """Iterable stand-in for ``CueListModel``: supports iteration
    (for ``find_matches``), ``len()`` and ``item(index)``."""

    def __init__(self, cues):
        self._cues = cues
        for i, c in enumerate(cues):
            c.index = i

    def __len__(self):
        return len(self._cues)

    def __iter__(self):
        return iter(self._cues)

    def item(self, index):
        if 0 <= index < len(self._cues):
            return self._cues[index]
        return None


def _cue(mock_app, name, color_name="", group_id=""):
    c = Cue(app=mock_app)
    c.name = name
    c.color_name = color_name
    c.group_id = group_id
    return c


def _make(mock_app, cues, text="", color="", standby=0, visible=True):
    from lisp.plugins.list_layout.layout import ListLayout

    layout = ListLayout.__new__(ListLayout)  # skip heavy __init__
    layout.app = mock_app
    layout._list_model = _StubModel(cues)
    layout._find_matches = []
    layout._find_pos = -1
    layout._find_landed = False

    layout._standby = standby
    layout.standby_index = lambda: layout._standby

    def set_standby(idx):
        layout._standby = idx

    layout.set_standby_index = set_standby

    view = MagicMock()
    view.findBar.query.return_value = text
    view.findBar.color.return_value = color
    view.findBar.isVisible.return_value = visible
    layout._view = view
    return layout


class TestFindLanding:
    def test_first_next_lands_on_first_match_at_or_after_standby(
        self, mock_app
    ):
        cues = [
            _cue(mock_app, "red one"),
            _cue(mock_app, "blue"),
            _cue(mock_app, "red two"),
            _cue(mock_app, "green"),
        ]
        # standby sits on index 1 ("blue"), which is NOT a match.
        layout = _make(mock_app, cues, text="red", standby=1)
        layout._recompute_find()
        assert layout._find_matches == [0, 2]

        layout._find_next()
        # First match at/after standby index 1 is model index 2.
        assert layout.standby_index() == 2

    def test_first_prev_lands_on_match_before_cursor(self, mock_app):
        cues = [
            _cue(mock_app, "red one"),
            _cue(mock_app, "blue"),
            _cue(mock_app, "red two"),
            _cue(mock_app, "green"),
        ]
        layout = _make(mock_app, cues, text="red", standby=1)
        layout._recompute_find()

        layout._find_prev()
        # First match before cursor index 1 is model index 0.
        assert layout.standby_index() == 0

    def test_next_wraps_after_landing(self, mock_app):
        cues = [
            _cue(mock_app, "red one"),
            _cue(mock_app, "blue"),
            _cue(mock_app, "red two"),
        ]
        layout = _make(mock_app, cues, text="red", standby=0)
        layout._recompute_find()

        layout._find_next()  # land on 0
        assert layout.standby_index() == 0
        layout._find_next()  # advance to 2
        assert layout.standby_index() == 2
        layout._find_next()  # wrap to 0
        assert layout.standby_index() == 0


class TestZeroMatch:
    def test_next_is_noop_when_no_matches(self, mock_app):
        cues = [_cue(mock_app, "alpha"), _cue(mock_app, "beta")]
        layout = _make(mock_app, cues, text="zzz", standby=1)
        layout._recompute_find()
        assert layout._find_matches == []

        layout._find_next()  # must not raise / must not move standby
        assert layout.standby_index() == 1

    def test_prev_is_noop_when_no_matches(self, mock_app):
        cues = [_cue(mock_app, "alpha"), _cue(mock_app, "beta")]
        layout = _make(mock_app, cues, text="zzz", standby=1)
        layout._recompute_find()

        layout._find_prev()
        assert layout.standby_index() == 1


class TestAncestorExpansion:
    def test_jump_expands_collapsed_ancestor_group(self, mock_app):
        group = _cue(mock_app, "Act 1")
        child = _cue(mock_app, "Thunder", group_id=group.id)
        cues = [group, child]  # indices 0, 1

        mock_app.cue_model = MagicMock()
        mock_app.cue_model.get.side_effect = lambda gid: (
            group if gid == group.id else None
        )

        layout = _make(mock_app, cues, text="thunder", standby=0)
        item = MagicMock()
        layout._view.listView.cueItemAt.return_value = item

        layout._recompute_find()
        assert layout._find_matches == [1]

        layout._find_next()  # jump to the child inside the group
        # The ancestor group's tree item must have been expanded.
        layout._view.listView.cueItemAt.assert_any_call(group.index)
        item.setExpanded.assert_called_with(True)


class TestPropertyChangeRecompute:
    def test_rename_while_open_updates_matches(self, mock_app):
        c0 = _cue(mock_app, "quiet")
        c1 = _cue(mock_app, "storm")
        layout = _make(mock_app, [c0, c1], text="thunder", visible=True)
        layout._recompute_find()
        assert layout._find_matches == []

        # Operator renames c1 to something that now matches.
        c1.name = "thunder storm"
        layout._on_cue_prop_changed_find(c1, "name", c1.name)
        assert layout._find_matches == [1]

    def test_non_searchable_property_does_not_recompute(self, mock_app):
        c0 = _cue(mock_app, "thunder")
        layout = _make(mock_app, [c0], text="thunder", visible=True)
        layout._recompute_find()
        assert layout._find_matches == [0]

        layout._recompute_find = MagicMock()  # spy: must NOT be called
        layout._on_cue_prop_changed_find(c0, "duration", 5000)
        layout._recompute_find.assert_not_called()

    def test_no_recompute_when_bar_hidden(self, mock_app):
        c0 = _cue(mock_app, "quiet")
        layout = _make(mock_app, [c0], text="thunder", visible=False)
        layout._recompute_find = MagicMock()  # spy
        layout._on_cue_prop_changed_find(c0, "name", "thunder")
        layout._recompute_find.assert_not_called()
