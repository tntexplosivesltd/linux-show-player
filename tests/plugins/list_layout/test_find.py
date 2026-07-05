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

from types import SimpleNamespace

from lisp.plugins.list_layout.find import (
    advance_match,
    find_matches,
    first_match_at_or_after,
)


def _cue(index, name="", cue_number="", color_name=""):
    return SimpleNamespace(
        index=index, name=name, cue_number=cue_number, color_name=color_name
    )


CUES = [
    _cue(0, name="Opening music", cue_number="1", color_name="Red"),
    _cue(1, name="Thunder", cue_number="2", color_name="Blue"),
    _cue(2, name="House lights", cue_number="12.5", color_name="Red"),
    _cue(3, name="Blackout", cue_number="13", color_name=""),
]


def test_empty_query_and_colour_is_inactive():
    assert find_matches(CUES, "", "") == []


def test_name_substring_case_insensitive():
    assert find_matches(CUES, "THUNDER", "") == [1]
    assert find_matches(CUES, "lights", "") == [2]


def test_cue_number_substring():
    # "12" is a substring of cue_number "12.5" (index 2) only.
    assert find_matches(CUES, "12", "") == [2]


def test_text_matches_name_or_number():
    # "1" appears in cue_number "1", "12.5", "13".
    assert find_matches(CUES, "1", "") == [0, 2, 3]


def test_colour_narrows_matches():
    assert find_matches(CUES, "", "Red") == [0, 2]


def test_text_and_colour_are_anded():
    # "House" matches only index 2; it is Red, so it survives.
    assert find_matches(CUES, "House", "Red") == [2]
    # "Thunder" matches index 1 but that cue is Blue, not Red.
    assert find_matches(CUES, "Thunder", "Red") == []


def test_first_match_at_or_after():
    assert first_match_at_or_after([0, 2, 3], 0) == 0
    assert first_match_at_or_after([0, 2, 3], 1) == 1  # first >= 1 is 2 (pos 1)
    assert first_match_at_or_after([0, 2, 3], 3) == 2
    assert first_match_at_or_after([0, 2, 3], 99) == 0  # wrap
    assert first_match_at_or_after([], 5) == 0


def test_advance_match_wraps():
    assert advance_match(0, 3, 1) == 1
    assert advance_match(2, 3, 1) == 0   # wrap forward
    assert advance_match(0, 3, -1) == 2  # wrap backward
    assert advance_match(0, 0, 1) == 0   # empty guard
