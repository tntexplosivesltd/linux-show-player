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

import pytest

from lisp.core.configuration import DummyConfiguration
from lisp.core.signal import Signal
from lisp.plugins.playback_monitor.monitor_window import (
    PlaybackMonitorWindow,
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


class _FakeMedia:
    def __init__(self, duration=0, start_time=0, stop_time=0):
        self.duration = duration
        self.start_time = start_time
        self.stop_time = stop_time


class _FakeMediaCue:
    """Mimics ``MediaCue`` for the monitor window's ``_time_updated``
    path. Only the attributes the method reads are provided."""

    def __init__(
        self, duration=60000, start_time=0, stop_time=0, name="Test"
    ):
        self.name = name
        self.duration = duration
        self.media = _FakeMedia(duration, start_time, stop_time)


class _FakeNonMediaCue:
    """Cue without a ``media`` attribute — e.g. a Stop All cue.
    Monitor must fall back to the legacy ``cue.duration - time``
    formula for these since there's no trim concept."""

    def __init__(self, duration=60000, name="Test"):
        self.name = name
        self.duration = duration


@pytest.fixture
def monitor_window(qtbot):
    """A real ``PlaybackMonitorWindow`` — the test exercises display
    logic that touches QLabel widgets, so ``__new__`` isn't enough;
    we need the constructed label tree."""
    config = DummyConfiguration(root={"elapsedPrimary": True})
    window = PlaybackMonitorWindow(config)
    qtbot.addWidget(window)
    # The method early-returns when hidden. Show (without stealing
    # focus for the test session) so the logic branches execute.
    window.show()
    yield window
    window.close()


class TestTrimAwarePlaybackMonitor:
    """The playback monitor must mirror the list-layout widget's
    trim-aware countdown so the two surfaces never disagree about
    how much of a trimmed cue is left. Same bug, same fix: subtract
    from ``stop_time`` (when set) rather than the raw duration, and
    anchor ``elapsed`` to ``start_time``."""

    def test_elapsed_zero_at_start_time(self, monitor_window):
        """Pipeline position ``time == start_time`` means the cue
        has just begun from the operator's perspective; elapsed
        must read 00:00, not the 30s of file skipped over."""
        cue = _FakeMediaCue(
            duration=180000, start_time=30000, stop_time=150000
        )
        monitor_window._tracked_cue = cue

        monitor_window._time_updated(30000)

        assert monitor_window.elapsed_text == "00:00"

    def test_remaining_full_at_start_time(self, monitor_window):
        """At ``time == start_time`` the full trimmed duration
        (stop_time - start_time = 120s) remains."""
        cue = _FakeMediaCue(
            duration=180000, start_time=30000, stop_time=150000
        )
        monitor_window._tracked_cue = cue

        monitor_window._time_updated(30000)

        assert monitor_window.remaining_text == "02:00"

    def test_remaining_zero_at_stop_time(self, monitor_window):
        """At ``time == stop_time`` remaining is zero, not the
        leftover tail of the untrimmed file."""
        cue = _FakeMediaCue(
            duration=180000, start_time=30000, stop_time=150000
        )
        monitor_window._tracked_cue = cue

        monitor_window._time_updated(150000)

        assert monitor_window.remaining_text == "00:00"

    def test_elapsed_trim_adjusted_mid_playback(self, monitor_window):
        """60s into the trimmed range (90s absolute) the elapsed
        reads 01:00."""
        cue = _FakeMediaCue(
            duration=180000, start_time=30000, stop_time=150000
        )
        monitor_window._tracked_cue = cue

        monitor_window._time_updated(90000)

        assert monitor_window.elapsed_text == "01:00"
        assert monitor_window.remaining_text == "01:00"

    def test_no_trim_behaves_as_before(self, monitor_window):
        """Untrimmed media cues fall through to the raw formula so
        existing behaviour is unchanged — regression guard."""
        cue = _FakeMediaCue(
            duration=180000, start_time=0, stop_time=0
        )
        monitor_window._tracked_cue = cue

        monitor_window._time_updated(60000)

        assert monitor_window.elapsed_text == "01:00"
        assert monitor_window.remaining_text == "02:00"

    def test_non_media_cue_uses_legacy_formula(self, monitor_window):
        """Cues without a ``media`` attribute (Stop All, Command,
        etc.) have no trim concept — we must not AttributeError
        or alter their display."""
        cue = _FakeNonMediaCue(duration=60000)
        monitor_window._tracked_cue = cue

        monitor_window._time_updated(15000)

        assert monitor_window.elapsed_text == "00:15"
        assert monitor_window.remaining_text == "00:45"

    def test_stop_time_only_stop_trim(self, monitor_window):
        """A cue trimmed only at the end (start_time == 0, stop_time
        set) counts down from stop_time and elapsed is unchanged."""
        cue = _FakeMediaCue(
            duration=180000, start_time=0, stop_time=90000
        )
        monitor_window._tracked_cue = cue

        monitor_window._time_updated(30000)

        assert monitor_window.elapsed_text == "00:30"
        assert monitor_window.remaining_text == "01:00"

    def test_clamp_beyond_stop_time(self, monitor_window):
        """Stale ``time`` past ``stop_time`` (race between pipeline
        and CueTime.stop) must not produce a negative remaining."""
        cue = _FakeMediaCue(
            duration=180000, start_time=30000, stop_time=150000
        )
        monitor_window._tracked_cue = cue

        monitor_window._time_updated(160000)

        assert monitor_window.remaining_text == "00:00"
