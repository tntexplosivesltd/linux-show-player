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

"""The Playback Monitor shows its times as seven-segment LCD digits."""

from unittest.mock import MagicMock, patch

import pytest
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QLCDNumber

from lisp.backend.media import MediaState
from lisp.core.configuration import DummyConfiguration
from lisp.plugins.playback_monitor.monitor_window import (
    PlaybackMonitorWindow,
)


class _FakeMediaCue:
    def __init__(self, duration=180000):
        self.name = "Test"
        self.duration = duration
        self.media = MagicMock()
        self.media.start_time = 0
        self.media.stop_time = 0
        self.media.state = MediaState.Playing


@pytest.fixture(autouse=True)
def _drop_reference_lcds():
    yield
    while _refs:
        _refs.pop().deleteLater()


@pytest.fixture
def window(qtbot):
    config = DummyConfiguration(root={"elapsedPrimary": True})
    win = PlaybackMonitorWindow(config)
    qtbot.addWidget(win)
    win.resize(300, 245)
    win.show()
    qtbot.waitExposed(win)
    yield win
    win.close()


def _render(widget):
    return widget.grab().toImage()


def _lit_height(widget):
    """Height in px of the drawn digits: rows with any pixel that
    differs from the background (top-left corner) colour."""
    img = _render(widget)
    bg = img.pixel(0, 0)
    rows = [
        y
        for y in range(img.height())
        if any(img.pixel(x, y) != bg for x in range(img.width()))
    ]
    return rows[-1] - rows[0] + 1 if rows else 0


_refs = []


def _reference_lcd(lcd, text):
    """A stock QLCDNumber set up like ``lcd`` and showing ``text``."""
    ref = QLCDNumber()
    _refs.append(ref)
    ref.setSegmentStyle(lcd.segmentStyle())
    ref.setDigitCount(lcd.digitCount())
    ref.setFrameShape(lcd.frameShape())
    ref.setStyleSheet(lcd.styleSheet())
    ref.setPalette(lcd.palette())
    ref.resize(lcd.size())
    ref.display(text)
    return ref


def _displays(window):
    return window._primary_display, window._secondary_display


def test_times_are_flat_lcd_digits(window):
    for lcd in _displays(window):
        assert isinstance(lcd, QLCDNumber)
        assert lcd.segmentStyle() == QLCDNumber.Flat


def test_lcd_draws_the_time_it_reports(window, qtbot):
    """``text()`` must be what the digits show, not a stored copy
    that drifted from the widget: render against a stock QLCDNumber
    showing the same string."""
    window._tracked_cue = _FakeMediaCue(duration=180000)
    window._time_updated(42000)

    primary, secondary = _displays(window)
    assert primary.text() == "00:42"
    assert secondary.text() == "02:18"
    for lcd in (primary, secondary):
        assert _render(lcd) == _render(_reference_lcd(lcd, lcd.text()))
        assert _render(lcd) != _render(_reference_lcd(lcd, "00:00"))


@pytest.mark.parametrize(
    "elapsed_ms, duration_ms, digits",
    [
        (42000, 180000, 5),  # MM:SS
        (42000, 2 * 3600 * 1000, 8),  # remaining HH:MM:SS
    ],
)
def test_digit_count_follows_the_text(
    window, elapsed_ms, duration_ms, digits
):
    """Short times get 5 wide digits instead of 8 cramped ones."""
    window._tracked_cue = _FakeMediaCue(duration=duration_ms)
    window._time_updated(elapsed_ms)

    _, secondary = _displays(window)
    assert secondary.digitCount() == len(secondary.text()) == digits


def test_unknown_duration_shows_dashes(window):
    cue = _FakeMediaCue(duration=0)
    # track_cue builds a CueTime, which keys on the id and connects
    # to ``changed("duration")``; with no duration it does no more.
    cue.id = "no-duration-cue"
    cue.changed = MagicMock()
    window.track_cue(cue)

    _, secondary = _displays(window)
    assert secondary.text() == "--:--"
    assert secondary.digitCount() == 5


def test_click_swaps_the_lcd_values(window, qtbot):
    window._tracked_cue = _FakeMediaCue(duration=180000)
    window._time_updated(42000)

    # Click the big digits, as an operator would: the press must
    # reach the window through the LCD.
    qtbot.mouseClick(window._primary_display, Qt.LeftButton)

    primary, secondary = _displays(window)
    assert window._config.get("elapsedPrimary") is False
    assert primary.text() == "02:18"
    assert secondary.text() == "00:42"
    assert window.elapsed_text == "00:42"
    assert window.remaining_text == "02:18"
    assert _render(primary) == _render(_reference_lcd(primary, "02:18"))


@pytest.mark.parametrize("size", [(300, 200), (300, 245), (400, 300)])
def test_primary_digits_dominate_the_window(window, size):
    """The drawn digits, not just the widgets: at the minimum, show
    and default sizes the large time is at least a third of the
    window tall (the old bold label's digits were ~35%) and several
    times the small one."""
    window.resize(*size)
    window._tracked_cue = _FakeMediaCue(duration=180000)
    window._time_updated(98000)
    primary, secondary = _displays(window)

    big, small = _lit_height(primary), _lit_height(secondary)
    assert big >= window.height() / 3
    assert 0 < small and big >= 3 * small


def test_rollover_to_hours_on_one_window(window):
    """59:59 -> 1:00:00 on a live window: the digit count follows
    the string and every digit is drawn. (QLCDNumber's overflow
    signal never fires for string input, so the render comparison is
    the check that nothing is cut off.)"""
    window._tracked_cue = _FakeMediaCue(duration=2 * 3600 * 1000)
    primary, _ = _displays(window)

    for ms, text in (
        (3599000, "59:59"),
        (3600000, "01:00:00"),
        (3601000, "01:00:01"),
    ):
        window._time_updated(ms)
        assert primary.text() == text
        assert primary.digitCount() == len(text)
        assert _render(primary) == _render(_reference_lcd(primary, text))


def test_unchanged_text_does_not_redraw(window):
    """Ticks inside the same second must not repaint the LCD."""
    window._tracked_cue = _FakeMediaCue(duration=180000)
    window._time_updated(42000)
    primary, _ = _displays(window)

    with patch.object(primary, "display") as display:
        window._time_updated(42500)
        window._time_updated(42900)
        display.assert_not_called()
        window._time_updated(43000)
        display.assert_called_once_with("00:43")
