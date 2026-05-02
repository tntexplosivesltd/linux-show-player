# This file is part of Linux Show Player
#
# Copyright 2026 Linux Show Player Contributors
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

"""Helpers for managing static `cue_number` identifiers.

The cue_number is a free-form string travelling with each cue across
reorders. Auto-assignment picks the next free positive integer (as a
string) so freshly-added cues never collide with existing values.
Custom user labels (e.g. "Pre-1") are skipped when computing the next
free value — only ASCII non-negative integers participate in the
auto-increment sequence.
"""

import re

_NON_NEG_INT = re.compile(r"\d+")


def _as_positive_int(value):
    """Return the positive integer represented by `value`, or None.

    Strict ASCII match: rejects negatives ("-3"), unicode digits ("１"),
    whitespace (" 5 "), hex ("0x10"), and empty strings. The strictness
    is deliberate — `int()` alone parses all of those into something,
    which would let a user-typed "-3" wreck the auto-increment max.
    """
    if not isinstance(value, str):
        return None
    if not _NON_NEG_INT.fullmatch(value):
        return None
    return int(value)


def next_cue_number(cue_model, exclude=None):
    """Return the next free positive-integer cue_number as a string.

    Walks `cue_model`, considers only cues with strict ASCII
    non-negative integer cue_numbers, returns ``str(max + 1)``. The
    optional `exclude` arg lets the caller skip a single cue (useful
    when reassigning during a collision check — the cue under repair
    shouldn't count towards its own max).
    """
    max_n = 0
    for existing in cue_model:
        if existing is exclude:
            continue
        n = _as_positive_int(existing.cue_number)
        if n is not None and n > max_n:
            max_n = n
    return str(max_n + 1)


def is_collision(cue_model, value, exclude=None):
    """Return True iff some cue (other than `exclude`) already uses `value`.

    Empty `value` is never a collision — multiple unset cues coexist
    until the auto-assigner fills them in.
    """
    if not value:
        return False
    for existing in cue_model:
        if existing is exclude:
            continue
        if existing.cue_number == value:
            return True
    return False
