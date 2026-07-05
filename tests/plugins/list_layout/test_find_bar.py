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

import pytest
from PyQt5.QtCore import Qt
from PyQt5.QtTest import QTest

from lisp.plugins.list_layout.find_bar import FindBar


@pytest.fixture
def bar(qtbot):
    w = FindBar()
    qtbot.addWidget(w)
    w.show()
    return w


def test_typing_emits_query_changed(bar, qtbot):
    with qtbot.waitSignal(bar.queryChanged) as blocker:
        bar.queryEdit.setText("thunder")
    assert blocker.args == ["thunder"]
    assert bar.query() == "thunder"


def test_enter_emits_find_next(bar, qtbot):
    with qtbot.waitSignal(bar.findNext):
        QTest.keyClick(bar.queryEdit, Qt.Key_Return)


def test_shift_enter_emits_find_prev(bar, qtbot):
    with qtbot.waitSignal(bar.findPrev):
        QTest.keyClick(bar.queryEdit, Qt.Key_Return, Qt.ShiftModifier)


def test_escape_emits_closed(bar, qtbot):
    with qtbot.waitSignal(bar.closed):
        QTest.keyClick(bar.queryEdit, Qt.Key_Escape)


def test_counter_shows_position(bar):
    bar.setMatchCounter(2, 7)
    assert bar.counterLabel.text() == "2/7"


def test_counter_zero_with_query_marks_invalid(bar):
    bar.queryEdit.setText("nope")
    bar.setMatchCounter(0, 0)
    assert bar.queryEdit.styleSheet() != ""


def test_counter_zero_without_query_is_blank(bar):
    bar.queryEdit.setText("")
    bar.setMatchCounter(0, 0)
    assert bar.counterLabel.text() == ""
    assert bar.queryEdit.styleSheet() == ""


def test_counter_zero_with_query_shows_zero_over_zero(bar):
    # An active search matching nothing shows "0/0" so the operator can
    # tell it apart from an idle bar (which stays blank).
    bar.queryEdit.setText("nope")
    bar.setMatchCounter(0, 0)
    assert bar.counterLabel.text() == "0/0"


def test_counter_zero_with_color_only_marks_invalid(bar):
    # Colour-only searches with no matches must also signal "no match":
    # invalid tint and "0/0", even though the text field is empty.
    bar.queryEdit.setText("")
    bar.colorPalette.setColor("Red")
    bar.setMatchCounter(0, 0)
    assert bar.queryEdit.styleSheet() != ""
    assert bar.counterLabel.text() == "0/0"
