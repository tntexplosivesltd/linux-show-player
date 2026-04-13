# This file is part of Linux Show Player
#
# Copyright 2017 Francesco Ceruti <ceppofrancy@gmail.com>
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

from lisp.plugins.playback_monitor.monitor_window import (
    format_monitor_time,
)


class TestFormatMonitorTime:
    def test_zero(self):
        assert format_monitor_time(0) == "00:00"

    def test_seconds_only(self):
        assert format_monitor_time(5000) == "00:05"

    def test_minutes_and_seconds(self):
        assert format_monitor_time(81000) == "01:21"

    def test_rounds_down_milliseconds(self):
        assert format_monitor_time(81999) == "01:21"

    def test_exactly_one_hour(self):
        assert format_monitor_time(3600000) == "01:00:00"

    def test_over_one_hour(self):
        assert format_monitor_time(3723000) == "01:02:03"

    def test_negative_clamps_to_zero(self):
        assert format_monitor_time(-500) == "00:00"
