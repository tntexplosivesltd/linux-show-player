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

"""Tests for the cue_number helpers and clone behaviour.

The auto-assign side now lives on `Application` (hooked to
`cue_model.item_added`), so most of the interesting logic is in the
pure helpers `next_cue_number` / `is_collision`. The factory side is
just clone-pop-to-force-fresh-number.
"""

from unittest.mock import MagicMock

from lisp.cues.cue_factory import CueFactory
from lisp.cues.cue_number import is_collision, next_cue_number


class _FakeCue:
    def __init__(self, cue_number=""):
        self.cue_number = cue_number


class TestNextCueNumber:
    def test_empty_model_returns_one(self):
        assert next_cue_number([]) == "1"

    def test_increments_max_numeric(self):
        cues = [_FakeCue("1"), _FakeCue("5"), _FakeCue("3")]
        assert next_cue_number(cues) == "6"

    def test_skips_non_numeric_labels(self):
        cues = [_FakeCue("Pre-1"), _FakeCue("2"), _FakeCue("backstage")]
        assert next_cue_number(cues) == "3"

    def test_skips_blank_entries(self):
        cues = [_FakeCue(""), _FakeCue("4"), _FakeCue("")]
        assert next_cue_number(cues) == "5"

    def test_rejects_negative_numbers(self):
        # int("-3") would parse to -3, breaking max() — the regex
        # guard must reject it so blank cues still map to a sane
        # positive sequence.
        cues = [_FakeCue("-3"), _FakeCue("2")]
        assert next_cue_number(cues) == "3"

    def test_rejects_unicode_digits(self):
        # int("１") (fullwidth) parses to 1; the strict ASCII regex
        # excludes it.
        cues = [_FakeCue("１"), _FakeCue("4")]
        assert next_cue_number(cues) == "5"

    def test_rejects_whitespace(self):
        cues = [_FakeCue(" 9 "), _FakeCue("2")]
        assert next_cue_number(cues) == "3"

    def test_exclude_skips_a_cue(self):
        cue = _FakeCue("10")
        cues = [_FakeCue("3"), cue]
        # If we're reassigning `cue` itself, its current value
        # shouldn't pin the max above the others.
        assert next_cue_number(cues, exclude=cue) == "4"


class TestIsCollision:
    def test_unique_value_no_collision(self):
        cues = [_FakeCue("1"), _FakeCue("2")]
        assert is_collision(cues, "3") is False

    def test_duplicate_value_collides(self):
        cues = [_FakeCue("1"), _FakeCue("2")]
        assert is_collision(cues, "1") is True

    def test_empty_value_never_collides(self):
        cues = [_FakeCue(""), _FakeCue("")]
        assert is_collision(cues, "") is False

    def test_exclude_skips_self(self):
        cue = _FakeCue("5")
        cues = [_FakeCue("3"), cue]
        # The cue itself is the only "5" — excluding it makes "5"
        # available for the caller to keep using.
        assert is_collision(cues, "5", exclude=cue) is False


class TestCloneCueDropsNumber:
    """`CueFactory.clone_cue` pops `cue_number` so the auto-assigner
    (Application's `item_added` hook) gives the clone a fresh value
    instead of duplicating the original."""

    def test_clone_strips_cue_number(self):
        original = MagicMock()
        original.__class__.__name__ = "FakeCue"
        original.properties.return_value = {
            "id": "orig-id",
            "name": "Original",
            "cue_number": "5",
        }

        app = MagicMock()
        factory = CueFactory(app)
        clone_target = MagicMock()
        factory.register_factory("FakeCue", lambda **kw: clone_target)

        factory.clone_cue(original)

        clone_target.update_properties.assert_called_once()
        applied = clone_target.update_properties.call_args[0][0]
        assert "id" not in applied
        assert "cue_number" not in applied
        assert applied["name"] == "Original"
