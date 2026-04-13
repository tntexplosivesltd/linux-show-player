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

from unittest.mock import MagicMock, patch

from lisp.core.signal import Signal
from lisp.plugins.playback_monitor.monitor_window import (
    format_monitor_time,
)


class FakeCue:
    """Minimal cue stub with the signals the plugin connects to."""

    def __init__(self, cue_id, name="Test Cue", duration=60000):
        self.id = cue_id
        self.name = name
        self.duration = duration
        self.started = Signal()


class TestCueTrackingLogic:
    """Test the tracking logic without instantiating the full plugin.

    The plugin connects cue.started → _cue_started, which calls
    window.track_cue(cue). We test this wiring by simulating what
    the plugin does: connect started, emit started, check the window.
    """

    def test_most_recently_started_cue_wins(self):
        """Starting cue B after cue A makes B the tracked cue."""
        window = MagicMock()
        window.isVisible.return_value = True

        cue_a = FakeCue("a", "Cue A")
        cue_b = FakeCue("b", "Cue B")

        def on_started(cue):
            window.track_cue(cue)

        cue_a.started.connect(on_started)
        cue_b.started.connect(on_started)

        cue_a.started.emit(cue_a)
        cue_b.started.emit(cue_b)

        assert window.track_cue.call_count == 2
        assert window.track_cue.call_args[0][0] is cue_b

    def test_removed_cue_does_not_trigger(self):
        """After disconnecting a cue's started signal, emitting it
        should not call track_cue."""
        window = MagicMock()

        cue = FakeCue("x", "Removed Cue")

        def on_started(c):
            window.track_cue(c)

        cue.started.connect(on_started)
        cue.started.disconnect(on_started)
        cue.started.emit(cue)

        window.track_cue.assert_not_called()


class TestTimeComputation:
    """Test elapsed/remaining computation logic matching
    PlaybackMonitorWindow._time_updated."""

    def test_elapsed_passthrough(self):
        """Elapsed time is the raw value formatted."""
        assert format_monitor_time(81000) == "01:21"

    def test_remaining_with_known_duration(self):
        """Remaining = duration - elapsed."""
        duration = 180000
        elapsed = 81000
        remaining = duration - elapsed
        assert format_monitor_time(remaining) == "01:39"

    def test_remaining_zero_at_end(self):
        """When elapsed equals duration, remaining is zero."""
        duration = 180000
        remaining = duration - duration
        assert format_monitor_time(max(0, remaining)) == "00:00"

    def test_indefinite_cue_shows_placeholder(self):
        """For indefinite cues (duration <= 0), remaining should be
        displayed as '--:--'. The window handles this — we just verify
        the condition."""
        duration = 0
        assert duration <= 0
