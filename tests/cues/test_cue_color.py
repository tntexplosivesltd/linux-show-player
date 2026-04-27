# This file is part of Linux Show Player
#
# Copyright 2026
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

from lisp.cues.cue import Cue


class TestCueColorName:
    def test_default_is_empty_string(self, mock_app):
        cue = Cue(mock_app)
        assert cue.color_name == ""

    def test_can_set_to_canonical_name(self, mock_app):
        cue = Cue(mock_app)
        cue.color_name = "Red"
        assert cue.color_name == "Red"

    def test_round_trips_through_properties(self, mock_app):
        cue = Cue(mock_app)
        cue.color_name = "Blue"
        props = cue.properties()
        assert props.get("color_name") == "Blue"

    def test_round_trips_through_update_properties(self, mock_app):
        cue = Cue(mock_app)
        cue.update_properties({"color_name": "Green"})
        assert cue.color_name == "Green"
