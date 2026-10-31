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

"""Pure (Qt-free) match logic for the list-layout find & jump bar.

Keeping this free of any Qt import lets the matching contract be
unit-tested without a QApplication, and keeps the controller's jump
arithmetic in one testable place.
"""


def find_matches(ordered_cues, text, color_name):
    """Return matching cues' model indices, in iteration order.

    A cue matches when:
      - ``text`` is empty OR (case-insensitively) is a substring of the
        cue's ``name`` OR of its ``cue_number``, AND
      - ``color_name`` is empty OR ``cue.color_name == color_name``.

    When both ``text`` and ``color_name`` are empty the search is
    inactive and ``[]`` is returned.
    """
    text = (text or "").strip().casefold()
    color_name = color_name or ""
    if not text and not color_name:
        return []

    matches = []
    for cue in ordered_cues:
        if color_name and cue.color_name != color_name:
            continue
        if text:
            name = (cue.name or "").casefold()
            number = (cue.cue_number or "").casefold()
            if text not in name and text not in number:
                continue
        matches.append(cue.index)
    return matches


def first_match_at_or_after(matches, index):
    """Position into ``matches`` of the first value >= ``index``.

    Falls back to 0 (wrap to the first match) when none qualify or
    ``matches`` is empty.
    """
    for pos, value in enumerate(matches):
        if value >= index:
            return pos
    return 0


def advance_match(pos, count, step):
    """Advance a match pointer by ``step`` with wrap-around."""
    if count <= 0:
        return 0
    return (pos + step) % count
