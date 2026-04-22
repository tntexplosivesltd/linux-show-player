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

"""Unit tests for ``TrimmableWaveformWidget`` and ``TrimmableTimelineWidget``.

The trimmable widget overlays draggable start/stop markers on the
existing peak/RMS waveform. These tests exercise the widget in isolation
— a fake Waveform double avoids GStreamer, and the inspector page is
covered separately in ``tests/ui/test_media_cue_settings.py``.
"""

import pytest
from PyQt5.QtCore import Qt


class _FakeWaveform:
    """Stand-in for Waveform — no pipeline, no file I/O."""

    def __init__(self, duration_ms=10_000):
        from lisp.core.signal import Signal
        self.duration = duration_ms
        self.peak_samples = []
        self.rms_samples = []
        self.ready = Signal()
        self.failed = Signal()

    def load_waveform(self):
        return False

    def is_ready(self):
        return bool(self.peak_samples and self.rms_samples)

    def mark_ready(self, samples=256):
        self.peak_samples = [0.5] * samples
        self.rms_samples = [0.25] * samples
        self.ready.emit()

    def mark_failed(self):
        self.failed.emit()

    def clear(self):
        self.peak_samples = []
        self.rms_samples = []


class TestTrimmableWaveformWidgetDefaults:
    def test_initial_markers_span_full_duration(self, qtbot):
        """Fresh widget: start at 0, stop at duration.

        This is the "play to natural end" default users expect when
        opening a cue that was never trimmed.
        """
        from lisp.ui.widgets.waveform import TrimmableWaveformWidget

        waveform = _FakeWaveform(duration_ms=5_000)
        widget = TrimmableWaveformWidget(waveform)
        qtbot.addWidget(widget)

        assert widget.startTime() == 0
        assert widget.stopTime() == 5_000

    def test_ready_updates_stop_to_duration(self, qtbot):
        """Late-arriving duration must update the stop marker.

        Real Waveforms are often constructed with ``duration=0`` and
        learn the real duration after the pipeline probes the file.
        """
        from lisp.ui.widgets.waveform import TrimmableWaveformWidget

        waveform = _FakeWaveform(duration_ms=0)
        widget = TrimmableWaveformWidget(waveform)
        qtbot.addWidget(widget)

        assert widget.stopTime() == 0  # initial snap

        waveform.duration = 8_000
        waveform.mark_ready()
        qtbot.wait(10)

        assert widget.stopTime() == 8_000


class TestTrimmableWaveformWidgetSetters:
    def test_set_start_clamps_to_valid_range(self, qtbot):
        from lisp.ui.widgets.waveform import TrimmableWaveformWidget
        waveform = _FakeWaveform(duration_ms=10_000)
        widget = TrimmableWaveformWidget(waveform)
        qtbot.addWidget(widget)

        widget.setStartTime(-500)
        assert widget.startTime() == 0

        widget.setStartTime(20_000)
        assert widget.startTime() == widget.stopTime() - 1

    def test_set_stop_clamps_to_valid_range(self, qtbot):
        from lisp.ui.widgets.waveform import TrimmableWaveformWidget
        waveform = _FakeWaveform(duration_ms=10_000)
        widget = TrimmableWaveformWidget(waveform)
        qtbot.addWidget(widget)

        widget.setStartTime(3_000)
        widget.setStopTime(1_000)
        assert widget.stopTime() == widget.startTime() + 1

        widget.setStopTime(999_999)
        assert widget.stopTime() == 10_000

    def test_set_start_emits_signal(self, qtbot):
        from lisp.ui.widgets.waveform import TrimmableWaveformWidget
        waveform = _FakeWaveform(duration_ms=10_000)
        widget = TrimmableWaveformWidget(waveform)
        qtbot.addWidget(widget)

        with qtbot.waitSignal(widget.startTimeChanged, timeout=100) as blocker:
            widget.setStartTime(2_500)
        assert blocker.args == [2_500]

    def test_set_stop_emits_signal(self, qtbot):
        from lisp.ui.widgets.waveform import TrimmableWaveformWidget
        waveform = _FakeWaveform(duration_ms=10_000)
        widget = TrimmableWaveformWidget(waveform)
        qtbot.addWidget(widget)

        with qtbot.waitSignal(widget.stopTimeChanged, timeout=100) as blocker:
            widget.setStopTime(7_500)
        assert blocker.args == [7_500]

    def test_silent_setters_suppress_emission(self, qtbot):
        from lisp.ui.widgets.waveform import TrimmableWaveformWidget
        waveform = _FakeWaveform(duration_ms=10_000)
        widget = TrimmableWaveformWidget(waveform)
        qtbot.addWidget(widget)

        emitted = []
        widget.startTimeChanged.connect(lambda v: emitted.append(v))
        widget.stopTimeChanged.connect(lambda v: emitted.append(v))

        widget.setStartTime(1_000, silent=True)
        widget.setStopTime(9_000, silent=True)

        assert emitted == []
        assert widget.startTime() == 1_000
        assert widget.stopTime() == 9_000


def _send_mouse(widget, kind, x, y, buttons=Qt.NoButton):
    """Synchronously deliver a mouse event bypassing QTest.mouseMove flakiness."""
    from PyQt5.QtCore import QEvent, QPoint
    from PyQt5.QtGui import QMouseEvent
    from PyQt5.QtWidgets import QApplication

    event_type = {
        "press": QEvent.MouseButtonPress,
        "move": QEvent.MouseMove,
        "release": QEvent.MouseButtonRelease,
    }[kind]
    button = Qt.LeftButton if kind != "move" else Qt.NoButton
    QApplication.sendEvent(
        widget,
        QMouseEvent(event_type, QPoint(x, y), button, buttons, Qt.NoModifier),
    )


class TestTrimmableWaveformWidgetMouse:
    def test_press_near_start_grabs_start_marker(self, qtbot):
        from lisp.ui.widgets.waveform import TrimmableWaveformWidget

        waveform = _FakeWaveform(duration_ms=10_000)
        widget = TrimmableWaveformWidget(waveform)
        qtbot.addWidget(widget)
        widget.resize(400, 120)
        widget.show()
        qtbot.waitExposed(widget)
        widget.setStartTime(2_000, silent=True)
        widget.setStopTime(8_000, silent=True)

        # 2000ms at 400px / 10000ms = x=80
        _send_mouse(widget, "press", 82, 60)
        _send_mouse(widget, "move", 200, 60, buttons=Qt.LeftButton)

        # At 200px the time is ~5000ms — start should follow.
        assert 4_500 <= widget.startTime() <= 5_500
        _send_mouse(widget, "release", 200, 60)

    def test_press_near_stop_grabs_stop_marker(self, qtbot):
        from lisp.ui.widgets.waveform import TrimmableWaveformWidget

        waveform = _FakeWaveform(duration_ms=10_000)
        widget = TrimmableWaveformWidget(waveform)
        qtbot.addWidget(widget)
        widget.resize(400, 120)
        widget.show()
        qtbot.waitExposed(widget)
        widget.setStartTime(2_000, silent=True)
        widget.setStopTime(8_000, silent=True)

        # 8000ms at 400px / 10000ms = x=320
        _send_mouse(widget, "press", 318, 60)
        _send_mouse(widget, "move", 240, 60, buttons=Qt.LeftButton)

        # At 240px the time is ~6000ms — stop should follow.
        assert 5_500 <= widget.stopTime() <= 6_500
        _send_mouse(widget, "release", 240, 60)

    def test_release_emits_trim_released_once(self, qtbot):
        from lisp.ui.widgets.waveform import TrimmableWaveformWidget

        waveform = _FakeWaveform(duration_ms=10_000)
        widget = TrimmableWaveformWidget(waveform)
        qtbot.addWidget(widget)
        widget.resize(400, 120)
        widget.show()
        qtbot.waitExposed(widget)
        widget.setStartTime(2_000, silent=True)

        releases = []
        widget.trimReleased.connect(lambda: releases.append(True))

        _send_mouse(widget, "press", 82, 60)
        _send_mouse(widget, "move", 120, 60, buttons=Qt.LeftButton)
        _send_mouse(widget, "move", 160, 60, buttons=Qt.LeftButton)
        assert releases == []  # no emissions during move

        _send_mouse(widget, "release", 160, 60)
        qtbot.wait(10)
        assert len(releases) == 1


class TestTrimmableWaveformWidgetPaint:
    def test_paint_survives_without_peaks(self, qtbot):
        """Pre-ready paint must not crash — peaks list is empty."""
        from lisp.ui.widgets.waveform import TrimmableWaveformWidget
        waveform = _FakeWaveform(duration_ms=10_000)
        widget = TrimmableWaveformWidget(waveform)
        qtbot.addWidget(widget)
        widget.resize(400, 120)
        widget.show()
        qtbot.waitExposed(widget)

    def test_paint_survives_with_peaks(self, qtbot):
        """Ready paint draws peaks + markers + shaded region."""
        from lisp.ui.widgets.waveform import TrimmableWaveformWidget
        waveform = _FakeWaveform(duration_ms=10_000)
        waveform.mark_ready()
        widget = TrimmableWaveformWidget(waveform)
        qtbot.addWidget(widget)
        widget.resize(400, 120)
        widget.show()
        qtbot.waitExposed(widget)

    def test_paint_handles_inverted_region(self, qtbot):
        """Paint must not divide-by-zero when start == stop - 1."""
        from lisp.ui.widgets.waveform import TrimmableWaveformWidget
        waveform = _FakeWaveform(duration_ms=10_000)
        widget = TrimmableWaveformWidget(waveform)
        qtbot.addWidget(widget)
        widget.resize(400, 120)
        widget.setStartTime(4_999)
        widget.setStopTime(5_000)
        widget.show()
        qtbot.waitExposed(widget)


class TestTrimmableWaveformWidgetKeyboard:
    def test_left_nudges_start_back_100ms(self, qtbot):
        from PyQt5.QtTest import QTest
        from lisp.ui.widgets.waveform import TrimmableWaveformWidget

        waveform = _FakeWaveform(duration_ms=10_000)
        widget = TrimmableWaveformWidget(waveform)
        qtbot.addWidget(widget)
        widget.resize(400, 120)
        widget.show()
        qtbot.waitExposed(widget)
        widget.setStartTime(5_000, silent=True)
        widget.focusStartMarker()

        QTest.keyClick(widget, Qt.Key_Left)
        assert widget.startTime() == 4_900

    def test_shift_right_nudges_stop_forward_1000ms(self, qtbot):
        from PyQt5.QtTest import QTest
        from lisp.ui.widgets.waveform import TrimmableWaveformWidget

        waveform = _FakeWaveform(duration_ms=10_000)
        widget = TrimmableWaveformWidget(waveform)
        qtbot.addWidget(widget)
        widget.resize(400, 120)
        widget.show()
        qtbot.waitExposed(widget)
        widget.setStartTime(1_000, silent=True)
        widget.setStopTime(5_000, silent=True)
        widget.focusStopMarker()

        QTest.keyClick(widget, Qt.Key_Right, Qt.ShiftModifier)
        assert widget.stopTime() == 6_000


class TestTrimmableTimelineWidget:
    def test_has_trim_api(self, qtbot):
        """Same API surface as TrimmableWaveformWidget."""
        from lisp.ui.widgets.waveform import TrimmableTimelineWidget

        widget = TrimmableTimelineWidget(duration_ms=10_000)
        qtbot.addWidget(widget)

        assert widget.startTime() == 0
        assert widget.stopTime() == 10_000

    def test_set_duration_rescales_stop(self, qtbot):
        """Post-construction duration change snaps stop marker."""
        from lisp.ui.widgets.waveform import TrimmableTimelineWidget

        widget = TrimmableTimelineWidget(duration_ms=0)
        qtbot.addWidget(widget)
        widget.setDuration(5_000)
        assert widget.stopTime() == 5_000

    def test_paint_survives(self, qtbot):
        from lisp.ui.widgets.waveform import TrimmableTimelineWidget
        widget = TrimmableTimelineWidget(duration_ms=10_000)
        qtbot.addWidget(widget)
        widget.resize(400, 120)
        widget.show()
        qtbot.waitExposed(widget)

    def test_mouse_drag_moves_nearest_marker(self, qtbot):
        """Same click-nearest-marker UX as TrimmableWaveformWidget."""
        from PyQt5.QtCore import QPoint
        from PyQt5.QtGui import QMouseEvent
        from lisp.ui.widgets.waveform import TrimmableTimelineWidget

        widget = TrimmableTimelineWidget(duration_ms=10_000)
        qtbot.addWidget(widget)
        widget.resize(400, 120)
        widget.show()
        qtbot.waitExposed(widget)

        # Click near start (x=0 maps to 0 ms); drag to x=100 → 2_500 ms.
        press = QMouseEvent(
            QMouseEvent.MouseButtonPress,
            QPoint(5, 60),
            Qt.LeftButton,
            Qt.LeftButton,
            Qt.NoModifier,
        )
        widget.mousePressEvent(press)
        move = QMouseEvent(
            QMouseEvent.MouseMove,
            QPoint(100, 60),
            Qt.NoButton,
            Qt.LeftButton,
            Qt.NoModifier,
        )
        widget.mouseMoveEvent(move)
        assert widget.startTime() == 2_500

    def test_keyboard_nudge_moves_active_marker(self, qtbot):
        from PyQt5.QtGui import QKeyEvent
        from lisp.ui.widgets.waveform import TrimmableTimelineWidget

        widget = TrimmableTimelineWidget(duration_ms=10_000)
        qtbot.addWidget(widget)
        widget.focusStartMarker()
        widget.setStartTime(500)

        evt = QKeyEvent(
            QKeyEvent.KeyPress, Qt.Key_Right, Qt.NoModifier
        )
        widget.keyPressEvent(evt)
        assert widget.startTime() == 600  # 100 ms step

    def test_mouse_release_emits_trim_released(self, qtbot):
        from PyQt5.QtCore import QPoint
        from PyQt5.QtGui import QMouseEvent
        from lisp.ui.widgets.waveform import TrimmableTimelineWidget

        widget = TrimmableTimelineWidget(duration_ms=10_000)
        qtbot.addWidget(widget)
        widget.resize(400, 120)

        fired = {"n": 0}
        widget.trimReleased.connect(
            lambda: fired.__setitem__("n", fired["n"] + 1)
        )

        press = QMouseEvent(
            QMouseEvent.MouseButtonPress,
            QPoint(5, 60),
            Qt.LeftButton,
            Qt.LeftButton,
            Qt.NoModifier,
        )
        release = QMouseEvent(
            QMouseEvent.MouseButtonRelease,
            QPoint(100, 60),
            Qt.LeftButton,
            Qt.NoButton,
            Qt.NoModifier,
        )
        widget.mousePressEvent(press)
        widget.mouseReleaseEvent(release)

        assert fired["n"] == 1


class TestWaveformWidgetDetach:
    def test_detach_breaks_ready_connection(self, qtbot):
        """After detach(), a late ready emission must not hit the widget.

        Real scenario: user navigates away from a cue before its decode
        pipeline finishes. The page calls waveform.clear() + schedules
        the widget for deletion; a queued ready emission still fires
        and would land on a Qt-dead widget.
        """
        from lisp.ui.widgets.waveform import TrimmableWaveformWidget

        waveform = _FakeWaveform(duration_ms=0)
        widget = TrimmableWaveformWidget(waveform)
        qtbot.addWidget(widget)

        calls = {"ready": 0}
        original = widget._ready

        def counting():
            calls["ready"] += 1
            return original()

        widget._ready = counting
        # Re-connect so our counter sees the emission.
        waveform.ready.disconnect(original)
        from lisp.core.signal import Connection
        waveform.ready.connect(counting, Connection.QtQueued)

        widget.detach()
        waveform.duration = 5_000
        waveform.mark_ready()
        qtbot.wait(20)

        assert calls["ready"] == 0
