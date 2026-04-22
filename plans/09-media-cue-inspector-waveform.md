# Media Cue Inspector Waveform Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a draggable-marker waveform to the Media Cue inspector page so start/stop trim becomes a visual, grabbable surface alongside the existing numeric fields. Also map the `stop_time == 0` sentinel to `duration` on display so the field is no longer opaque.

**Architecture:** Two new widget classes live in `lisp/ui/widgets/waveform.py` — `TrimmableWaveformWidget(WaveformWidget)` overlays start/stop markers on peak data, and `TrimmableTimelineWidget(QWidget)` provides a flat fallback for image cues and decode failures. `MediaCueSettings` (`lisp/ui/settings/cue_pages/media_cue.py`) is restructured into a two-column grid (narrow left with start/stop/loop fields, wide right with the waveform). The page bridges numeric-field edits and marker drags bidirectionally via `silent=True` setters + `blockSignals()`. `trimReleased` on the marker widget drives the page's existing `commit_requested` signal — no changes to `InspectorCommitEngine`. Backend stays untouched; `GstWaveform` already handles audio and video via `uridecodebin`.

**Tech Stack:** Python 3.9+, PyQt5 (QWidget, QPainter, QTimeEdit, QGridLayout, QSpinBox), existing `lisp.backend.waveform.Waveform`, `lisp.ui.widgets.waveform.WaveformWidget`, pytest + pytest-qt.

**Spec:** `docs/specs/2026-04-22-media-cue-inspector-waveform-design.md`

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `lisp/ui/widgets/waveform.py` | Modify | Add `TrimmableWaveformWidget(WaveformWidget)` and `TrimmableTimelineWidget(QWidget)`. Existing `WaveformWidget` + `WaveformSlider` untouched — the running-cue panel continues using them. |
| `lisp/ui/settings/cue_pages/media_cue.py` | Modify | Restructure to two-column grid. Add sentinel mapping on load, bidirectional sync between numeric fields and waveform trimmer, image-cue detection, and multi-select placeholder. |
| `tests/ui/widgets/test_trimmable_waveform.py` | Create | Unit tests for both new widgets, using a `_FakeWaveform` double. |
| `tests/ui/test_media_cue_settings.py` | Create | Integration tests for `MediaCueSettings` — sentinel mapping, live sync, image/multi-select branches. |

## Shared test helper

Every test in this plan that touches `TrimmableWaveformWidget` needs a waveform double. Copy this into both test files verbatim — don't factor into a shared conftest yet (the two test files drift independently as new cases are added).

```python
class _FakeWaveform:
    """Stand-in for Waveform — no pipeline, no file I/O.

    Matches just the surface WaveformWidget touches: ``ready`` and
    ``failed`` signals, ``duration``, ``peak_samples`` / ``rms_samples``,
    ``load_waveform()`` (no-op), ``is_ready()``.
    """

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
```

---

## Task 1: `TrimmableWaveformWidget` — class and defaults

**Files:**
- Modify: `lisp/ui/widgets/waveform.py` (append new class after `WaveformSlider`)
- Create: `tests/ui/widgets/test_trimmable_waveform.py`

- [ ] **Step 1: Create test file with fake waveform + initial-state test**

Create `tests/ui/widgets/test_trimmable_waveform.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

```bash
poetry run pytest tests/ui/widgets/test_trimmable_waveform.py::TestTrimmableWaveformWidgetDefaults::test_initial_markers_span_full_duration -v
```

Expected: `ImportError: cannot import name 'TrimmableWaveformWidget'`.

- [ ] **Step 3: Add the minimal class**

Append to `lisp/ui/widgets/waveform.py` (below `WaveformSlider`):

```python
class TrimmableWaveformWidget(WaveformWidget):
    """Waveform with draggable start/stop trim markers.

    Overlays two full-height vertical lines on top of the inherited
    peak/RMS paint. Emits per-frame signals during drag and a single
    ``trimReleased`` on mouse-up, so the inspector page can debounce
    its own commit logic.
    """

    startTimeChanged = pyqtSignal(int)
    stopTimeChanged = pyqtSignal(int)
    trimReleased = pyqtSignal()

    def __init__(self, waveform: Waveform, **kwargs):
        super().__init__(waveform, **kwargs)
        self._start_ms = 0
        self._stop_ms = self._waveform.duration
        self._active_marker = None

    def startTime(self) -> int:
        return self._start_ms

    def stopTime(self) -> int:
        return self._stop_ms
```

- [ ] **Step 4: Run test to verify it passes**

```bash
poetry run pytest tests/ui/widgets/test_trimmable_waveform.py::TestTrimmableWaveformWidgetDefaults::test_initial_markers_span_full_duration -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add lisp/ui/widgets/waveform.py tests/ui/widgets/test_trimmable_waveform.py
git -c commit.gpgsign=false commit -m "feat(waveform): scaffold TrimmableWaveformWidget

Adds the class skeleton with startTime/stopTime accessors and signal
declarations. Markers default to [0, duration] on construction."
```

---

## Task 2: Stop-time follows duration after `ready`

**Files:**
- Modify: `lisp/ui/widgets/waveform.py`
- Test: `tests/ui/widgets/test_trimmable_waveform.py`

The fake waveform passes `duration_ms` at construction, so Task 1's default case works. But the real pipeline often constructs `Waveform` with `duration=None` and populates it later. On `ready`, the widget must snap `_stop_ms` to the now-known duration unless the user has already moved it.

- [ ] **Step 1: Write failing test**

Append to `TestTrimmableWaveformWidgetDefaults`:

```python
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
```

- [ ] **Step 2: Run to verify fail**

```bash
poetry run pytest tests/ui/widgets/test_trimmable_waveform.py::TestTrimmableWaveformWidgetDefaults::test_ready_updates_stop_to_duration -v
```

Expected: `assert 0 == 8_000`.

- [ ] **Step 3: Implement — hook `_ready`**

Add to `TrimmableWaveformWidget`:

```python
    def _ready(self):
        # Run the base-class handler first so _maximum gets set.
        super()._ready()
        # Snap stop to the now-known duration, but only if the user
        # hasn't moved it yet (i.e., it still matches the old default).
        if self._stop_ms == 0 or self._stop_ms > self._waveform.duration:
            self._stop_ms = self._waveform.duration
            self.stopTimeChanged.emit(self._stop_ms)
            self.update()
```

- [ ] **Step 4: Run to verify pass**

```bash
poetry run pytest tests/ui/widgets/test_trimmable_waveform.py -v
```

Expected: both tests pass.

- [ ] **Step 5: Commit**

```bash
git add lisp/ui/widgets/waveform.py tests/ui/widgets/test_trimmable_waveform.py
git -c commit.gpgsign=false commit -m "feat(waveform): snap stop marker to duration on ready"
```

---

## Task 3: `setStartTime` / `setStopTime` with clamp invariants

**Files:**
- Modify: `lisp/ui/widgets/waveform.py`
- Test: `tests/ui/widgets/test_trimmable_waveform.py`

The spec mandates `start_ms < stop_ms` with 1 ms precision, enforced in the setters so both drag and numeric paths hit the same code.

- [ ] **Step 1: Write failing tests**

Add to the test file:

```python
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
```

- [ ] **Step 2: Run to verify fail**

```bash
poetry run pytest tests/ui/widgets/test_trimmable_waveform.py::TestTrimmableWaveformWidgetSetters -v
```

Expected: `AttributeError: 'TrimmableWaveformWidget' object has no attribute 'setStartTime'`.

- [ ] **Step 3: Implement setters with clamp**

Add to `TrimmableWaveformWidget`:

```python
    def setStartTime(self, ms: int, silent: bool = False) -> None:
        upper = self._stop_ms - 1 if self._stop_ms > 0 else 0
        ms = max(0, min(int(ms), upper))
        if ms == self._start_ms:
            return
        self._start_ms = ms
        if not silent:
            self.startTimeChanged.emit(ms)
        self.update()

    def setStopTime(self, ms: int, silent: bool = False) -> None:
        upper = self._waveform.duration
        lower = self._start_ms + 1
        ms = max(lower, min(int(ms), upper))
        if ms == self._stop_ms:
            return
        self._stop_ms = ms
        if not silent:
            self.stopTimeChanged.emit(ms)
        self.update()
```

- [ ] **Step 4: Run to verify pass**

```bash
poetry run pytest tests/ui/widgets/test_trimmable_waveform.py -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add lisp/ui/widgets/waveform.py tests/ui/widgets/test_trimmable_waveform.py
git -c commit.gpgsign=false commit -m "feat(waveform): trimmable setters with clamp + signals"
```

---

## Task 4: Mouse press/drag/release on markers

**Files:**
- Modify: `lisp/ui/widgets/waveform.py`
- Test: `tests/ui/widgets/test_trimmable_waveform.py`

Mouse dispatch is by x-proximity: click nearer the start marker grabs start; nearer the stop marker grabs stop. Drag updates the active marker. Release emits `trimReleased` once.

- [ ] **Step 1: Write failing tests**

Append:

```python
class TestTrimmableWaveformWidgetMouse:
    def _ms_per_px(self, widget):
        return widget.maximum() / widget.width()

    def test_press_near_start_grabs_start_marker(self, qtbot):
        from PyQt5.QtCore import QPoint
        from PyQt5.QtTest import QTest
        from lisp.ui.widgets.waveform import TrimmableWaveformWidget

        waveform = _FakeWaveform(duration_ms=10_000)
        widget = TrimmableWaveformWidget(waveform)
        qtbot.addWidget(widget)
        widget.resize(400, 120)
        widget.setStartTime(2_000, silent=True)
        widget.setStopTime(8_000, silent=True)

        # 2000ms at 400px / 10000ms = x=80
        QTest.mousePress(widget, Qt.LeftButton, pos=QPoint(82, 60))
        # Drag a little
        QTest.mouseMove(widget, QPoint(200, 60))

        # At 200px the time is ~5000ms — start should follow.
        assert 4_500 <= widget.startTime() <= 5_500
        QTest.mouseRelease(widget, Qt.LeftButton, pos=QPoint(200, 60))

    def test_press_near_stop_grabs_stop_marker(self, qtbot):
        from PyQt5.QtCore import QPoint
        from PyQt5.QtTest import QTest
        from lisp.ui.widgets.waveform import TrimmableWaveformWidget

        waveform = _FakeWaveform(duration_ms=10_000)
        widget = TrimmableWaveformWidget(waveform)
        qtbot.addWidget(widget)
        widget.resize(400, 120)
        widget.setStartTime(2_000, silent=True)
        widget.setStopTime(8_000, silent=True)

        # 8000ms at 400px / 10000ms = x=320
        QTest.mousePress(widget, Qt.LeftButton, pos=QPoint(318, 60))
        QTest.mouseMove(widget, QPoint(240, 60))

        # At 240px the time is ~6000ms — stop should follow.
        assert 5_500 <= widget.stopTime() <= 6_500
        QTest.mouseRelease(widget, Qt.LeftButton, pos=QPoint(240, 60))

    def test_release_emits_trim_released_once(self, qtbot):
        from PyQt5.QtCore import QPoint
        from PyQt5.QtTest import QTest
        from lisp.ui.widgets.waveform import TrimmableWaveformWidget

        waveform = _FakeWaveform(duration_ms=10_000)
        widget = TrimmableWaveformWidget(waveform)
        qtbot.addWidget(widget)
        widget.resize(400, 120)
        widget.setStartTime(2_000, silent=True)

        releases = []
        widget.trimReleased.connect(lambda: releases.append(True))

        QTest.mousePress(widget, Qt.LeftButton, pos=QPoint(82, 60))
        QTest.mouseMove(widget, QPoint(120, 60))
        QTest.mouseMove(widget, QPoint(160, 60))
        assert releases == []  # no emissions during move

        QTest.mouseRelease(widget, Qt.LeftButton, pos=QPoint(160, 60))
        qtbot.wait(10)
        assert len(releases) == 1
```

- [ ] **Step 2: Run to verify fail**

```bash
poetry run pytest tests/ui/widgets/test_trimmable_waveform.py::TestTrimmableWaveformWidgetMouse -v
```

Expected: events fire but markers don't move — assertions fail.

- [ ] **Step 3: Implement mouse handlers**

Add to `TrimmableWaveformWidget`:

```python
    _HIT_THRESHOLD_PX = 8

    def _ms_per_px(self) -> float:
        return self._valueToPx or 1.0

    def _x_for(self, ms: int) -> int:
        return int(ms / self._ms_per_px())

    def _ms_for(self, x: int) -> int:
        return int(round(x * self._ms_per_px()))

    def mousePressEvent(self, event):
        if event.button() != Qt.LeftButton:
            return
        x = event.x()
        dist_start = abs(x - self._x_for(self._start_ms))
        dist_stop = abs(x - self._x_for(self._stop_ms))
        if dist_start <= dist_stop:
            self._active_marker = "start"
        else:
            self._active_marker = "stop"

    def mouseMoveEvent(self, event):
        if self._active_marker is None:
            return
        ms = self._ms_for(event.x())
        if self._active_marker == "start":
            self.setStartTime(ms)
        else:
            self.setStopTime(ms)

    def mouseReleaseEvent(self, event):
        if event.button() != Qt.LeftButton or self._active_marker is None:
            return
        self._active_marker = None
        self.trimReleased.emit()
```

Also add `from PyQt5.QtCore import Qt` if not already present (it is — line 3 of the file).

- [ ] **Step 4: Run to verify pass**

```bash
poetry run pytest tests/ui/widgets/test_trimmable_waveform.py -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add lisp/ui/widgets/waveform.py tests/ui/widgets/test_trimmable_waveform.py
git -c commit.gpgsign=false commit -m "feat(waveform): drag markers + trimReleased on mouse-up"
```

---

## Task 5: Marker overlay paint + shaded region

**Files:**
- Modify: `lisp/ui/widgets/waveform.py`
- Test: `tests/ui/widgets/test_trimmable_waveform.py`

Pixel-exact paint tests are excluded per spec. Instead we assert that paint runs without raising, and that `update()` gets called after setter changes — the visual correctness is eyeballed during UI testing.

- [ ] **Step 1: Write failing test**

Append:

```python
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
        # If paintEvent raises, the show() above would have propagated it.

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
```

- [ ] **Step 2: Run — expect the three tests to pass trivially** (paintEvent inherits from base, which already handles both cases), but add the overlay logic so the widget actually shows markers.

```bash
poetry run pytest tests/ui/widgets/test_trimmable_waveform.py::TestTrimmableWaveformWidgetPaint -v
```

Expected: tests pass (base paintEvent handles the cases). This step validates the no-crash contract before we add overlay code that could regress it.

- [ ] **Step 3: Add overlay paintEvent**

Add to `TrimmableWaveformWidget`:

```python
    def paintEvent(self, event):
        # Draw peaks first using the base class.
        super().paintEvent(event)

        # Overlay the trim region and markers.
        painter = QPainter()
        painter.begin(self)
        x_start = self._x_for(self._start_ms)
        x_stop = self._x_for(self._stop_ms)

        # Shaded fill between markers — "kept" region.
        if x_stop > x_start:
            region_brush = QBrush(QColor(75, 154, 250, 40))
            painter.setPen(QPen(QColor(0, 0, 0, 0)))
            painter.setBrush(region_brush)
            painter.drawRect(
                x_start, 0, x_stop - x_start, self.height()
            )

        # Full-height vertical marker lines.
        marker_pen = QPen(QColor(75, 154, 250))
        marker_pen.setWidth(2)
        painter.setPen(marker_pen)
        painter.drawLine(x_start, 0, x_start, self.height())
        painter.drawLine(x_stop, 0, x_stop, self.height())

        painter.end()
```

- [ ] **Step 4: Re-run paint tests**

```bash
poetry run pytest tests/ui/widgets/test_trimmable_waveform.py -v
```

Expected: all paint tests still pass; existing marker tests unchanged.

- [ ] **Step 5: Commit**

```bash
git add lisp/ui/widgets/waveform.py tests/ui/widgets/test_trimmable_waveform.py
git -c commit.gpgsign=false commit -m "feat(waveform): overlay markers + shaded trim region"
```

---

## Task 6: Keyboard navigation on markers

**Files:**
- Modify: `lisp/ui/widgets/waveform.py`
- Test: `tests/ui/widgets/test_trimmable_waveform.py`

`Left`/`Right` = ±100 ms on the active marker. `Shift+Left`/`Shift+Right` = ±1000 ms. Widget must accept focus for the keys to arrive.

- [ ] **Step 1: Write failing tests**

Append:

```python
class TestTrimmableWaveformWidgetKeyboard:
    def test_left_nudges_start_back_100ms(self, qtbot):
        from PyQt5.QtCore import Qt
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
        from PyQt5.QtCore import Qt
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
```

- [ ] **Step 2: Run to verify fail**

```bash
poetry run pytest tests/ui/widgets/test_trimmable_waveform.py::TestTrimmableWaveformWidgetKeyboard -v
```

Expected: `AttributeError: 'TrimmableWaveformWidget' object has no attribute 'focusStartMarker'`.

- [ ] **Step 3: Implement keyboard + focus helpers**

Add to the `__init__` (before `super().__init__`'s return is fine, but put it at the end of `__init__`):

```python
        self.setFocusPolicy(Qt.StrongFocus)
```

Add methods:

```python
    def focusStartMarker(self):
        self._active_marker = "start"
        self.setFocus(Qt.OtherFocusReason)
        self.update()

    def focusStopMarker(self):
        self._active_marker = "stop"
        self.setFocus(Qt.OtherFocusReason)
        self.update()

    def keyPressEvent(self, event):
        if self._active_marker is None:
            super().keyPressEvent(event)
            return

        step = 1_000 if event.modifiers() & Qt.ShiftModifier else 100
        key = event.key()
        if key == Qt.Key_Left:
            delta = -step
        elif key == Qt.Key_Right:
            delta = step
        else:
            super().keyPressEvent(event)
            return

        if self._active_marker == "start":
            self.setStartTime(self._start_ms + delta)
        else:
            self.setStopTime(self._stop_ms + delta)
        self.trimReleased.emit()
```

- [ ] **Step 4: Run to verify pass**

```bash
poetry run pytest tests/ui/widgets/test_trimmable_waveform.py -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add lisp/ui/widgets/waveform.py tests/ui/widgets/test_trimmable_waveform.py
git -c commit.gpgsign=false commit -m "feat(waveform): keyboard nudging for trim markers

Left/Right = 100ms; Shift+Left/Right = 1000ms. Each keypress emits
trimReleased so the inspector commits per step, matching how a typed
time in the numeric field commits on change."
```

---

## Task 7: `TrimmableTimelineWidget` fallback

**Files:**
- Modify: `lisp/ui/widgets/waveform.py`
- Test: `tests/ui/widgets/test_trimmable_waveform.py`

A flat-timeline widget for cases where no peaks exist (image cues, waveform decode failure). Same marker API as `TrimmableWaveformWidget`, but no peaks layer — just a flat horizontal line with the two draggable markers over it.

- [ ] **Step 1: Write failing tests**

Append:

```python
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
```

- [ ] **Step 2: Run to verify fail**

```bash
poetry run pytest tests/ui/widgets/test_trimmable_waveform.py::TestTrimmableTimelineWidget -v
```

Expected: `ImportError: cannot import name 'TrimmableTimelineWidget'`.

- [ ] **Step 3: Implement** (append to `lisp/ui/widgets/waveform.py`)

```python
class TrimmableTimelineWidget(QWidget):
    """Flat-timeline fallback with the same trim API.

    Used when peak data isn't available (image cues, audio-less video,
    decode failure). Paints a flat horizontal line under the same
    marker overlay that TrimmableWaveformWidget uses.
    """

    startTimeChanged = pyqtSignal(int)
    stopTimeChanged = pyqtSignal(int)
    trimReleased = pyqtSignal()

    def __init__(self, duration_ms: int = 0, **kwargs):
        super().__init__(**kwargs)
        self._duration = max(0, int(duration_ms))
        self._start_ms = 0
        self._stop_ms = self._duration
        self._active_marker = None
        self.setFocusPolicy(Qt.StrongFocus)

        self.backgroundColor = QColor(32, 32, 32)
        self.lineColor = QColor(130, 130, 130)
        self.markerColor = QColor(75, 154, 250)
        self.regionColor = QColor(75, 154, 250, 40)

    # --- API mirrors TrimmableWaveformWidget ----------------------

    def startTime(self) -> int:
        return self._start_ms

    def stopTime(self) -> int:
        return self._stop_ms

    def setDuration(self, ms: int):
        self._duration = max(0, int(ms))
        if self._stop_ms == 0 or self._stop_ms > self._duration:
            self._stop_ms = self._duration
            self.stopTimeChanged.emit(self._stop_ms)
        self.update()

    def setStartTime(self, ms: int, silent: bool = False) -> None:
        upper = self._stop_ms - 1 if self._stop_ms > 0 else 0
        ms = max(0, min(int(ms), upper))
        if ms == self._start_ms:
            return
        self._start_ms = ms
        if not silent:
            self.startTimeChanged.emit(ms)
        self.update()

    def setStopTime(self, ms: int, silent: bool = False) -> None:
        upper = self._duration
        lower = self._start_ms + 1
        ms = max(lower, min(int(ms), upper))
        if ms == self._stop_ms:
            return
        self._stop_ms = ms
        if not silent:
            self.stopTimeChanged.emit(ms)
        self.update()

    def _ms_per_px(self) -> float:
        if self.width() == 0 or self._duration == 0:
            return 1.0
        return self._duration / self.width()

    def _x_for(self, ms: int) -> int:
        return int(ms / self._ms_per_px())

    # --- Paint ----------------------------------------------------

    def paintEvent(self, event):
        painter = QPainter()
        painter.begin(self)
        painter.setPen(QPen(QColor(0, 0, 0, 0)))
        painter.setBrush(QBrush(self.backgroundColor))
        painter.drawRoundedRect(self.rect(), 6, 6)

        mid = self.height() / 2
        painter.setPen(QPen(self.lineColor))
        painter.drawLine(QLineF(0, mid, self.width(), mid))

        x_start = self._x_for(self._start_ms)
        x_stop = self._x_for(self._stop_ms)
        if x_stop > x_start:
            painter.setPen(QPen(QColor(0, 0, 0, 0)))
            painter.setBrush(QBrush(self.regionColor))
            painter.drawRect(
                x_start, 0, x_stop - x_start, self.height()
            )

        marker_pen = QPen(self.markerColor)
        marker_pen.setWidth(2)
        painter.setPen(marker_pen)
        painter.drawLine(x_start, 0, x_start, self.height())
        painter.drawLine(x_stop, 0, x_stop, self.height())

        painter.end()
```

Note: `QLineF` is already imported at the top of `waveform.py` (line 3).

- [ ] **Step 4: Run to verify pass**

```bash
poetry run pytest tests/ui/widgets/test_trimmable_waveform.py -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add lisp/ui/widgets/waveform.py tests/ui/widgets/test_trimmable_waveform.py
git -c commit.gpgsign=false commit -m "feat(waveform): TrimmableTimelineWidget fallback for no-peaks path"
```

---

## Task 8: `MediaCueSettings` — two-column restructure

**Files:**
- Modify: `lisp/ui/settings/cue_pages/media_cue.py`
- Create: `tests/ui/test_media_cue_settings.py`

Restructure the layout but keep the existing field behaviour. No waveform yet — Task 9 mounts it. This lets us TDD layout and field behaviour separately.

- [ ] **Step 1: Create test file with layout assertion**

Create `tests/ui/test_media_cue_settings.py`:

```python
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

"""Integration tests for ``MediaCueSettings``.

Covers the inspector-page concerns: two-column layout, sentinel
mapping on load, bidirectional numeric-field ↔ trimmer sync,
image-cue detection, and the multi-select placeholder.
"""

import pytest
from PyQt5.QtCore import QTime

from lisp.ui.settings.cue_pages.media_cue import MediaCueSettings


class _FakeWaveform:
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


class TestMediaCueSettingsLayout:
    def test_has_start_stop_loop_fields(self, qtbot):
        page = MediaCueSettings()
        qtbot.addWidget(page)
        assert page.startEdit is not None
        assert page.stopEdit is not None
        assert page.spinLoop is not None

    def test_grid_is_two_column(self, qtbot):
        """Column 0 = narrow fields, column 1 = wide waveform slot.

        ColumnStretch 1:3 gives the waveform ~75% of horizontal space.
        """
        page = MediaCueSettings()
        qtbot.addWidget(page)

        grid = page.layout()
        assert grid.columnStretch(0) == 1
        assert grid.columnStretch(1) == 3
```

- [ ] **Step 2: Run to verify fail**

```bash
poetry run pytest tests/ui/test_media_cue_settings.py::TestMediaCueSettingsLayout -v
```

Expected: `test_has_start_stop_loop_fields` passes (they exist today), but `test_grid_is_two_column` fails — current page uses `columnStretch(0, 0)` + implicit.

- [ ] **Step 3: Restructure the page**

Replace `MediaCueSettings.__init__` body in `lisp/ui/settings/cue_pages/media_cue.py` (lines 36-82) with:

```python
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        # Two-column layout: narrow left for fields, wide right for the
        # waveform trimmer. QLab-style. Waveform is mounted lazily in
        # loadSettings() once we know the cue's media source.
        grid = QGridLayout(self)
        grid.setContentsMargins(8, 4, 8, 4)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(2)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 3)

        self.startGroup = make_flat_group()
        self.startGroup.setLayout(QHBoxLayout())
        self.startGroup.layout().setContentsMargins(0, 0, 0, 0)
        self.startEdit = QTimeEdit(self.startGroup)
        self.startEdit.setDisplayFormat("HH:mm:ss.zzz")
        self.startEdit.setCurrentSection(QDateTimeEdit.SecondSection)
        self.startGroup.layout().addWidget(self.startEdit)
        grid.addWidget(self.startGroup, 0, 0)

        self.stopGroup = make_flat_group()
        self.stopGroup.setLayout(QHBoxLayout())
        self.stopGroup.layout().setContentsMargins(0, 0, 0, 0)
        self.stopEdit = QTimeEdit(self.stopGroup)
        self.stopEdit.setDisplayFormat("HH:mm:ss.zzz")
        self.stopEdit.setCurrentSection(QDateTimeEdit.SecondSection)
        self.stopGroup.layout().addWidget(self.stopEdit)
        grid.addWidget(self.stopGroup, 1, 0)

        self.loopGroup = make_flat_group()
        self.loopGroup.setLayout(QHBoxLayout())
        self.loopGroup.layout().setContentsMargins(0, 0, 0, 0)
        self.spinLoop = QSpinBox(self.loopGroup)
        self.spinLoop.setRange(-1, 1_000_000)
        self.loopGroup.layout().addWidget(self.spinLoop)
        grid.addWidget(self.loopGroup, 2, 0)

        # Column 1 reserved for the waveform trimmer. Pin the waveform
        # into rows 0-2 so it grows vertically with the dialog.
        self._waveformSlot = None  # Populated in loadSettings()
        self._waveformRow = (0, 3)  # (start_row, row_span)

        # Two captions live in the same grid cell as the waveform slot:
        # * ``placeholderLabel`` — "Select a single cue" in multi-select
        # * ``imagePlaceholder`` — "Trimming does not apply to image cues."
        # Only one is ever visible at a time; the trimmer (when mounted)
        # supersedes both.
        self.placeholderLabel = QLabel("", self)
        self.placeholderLabel.setAlignment(Qt.AlignCenter)
        self.placeholderLabel.setStyleSheet("color: #888;")
        self.placeholderLabel.hide()
        grid.addWidget(self.placeholderLabel, 0, 1, 3, 1)

        self.imagePlaceholder = QLabel("", self)
        self.imagePlaceholder.setAlignment(Qt.AlignCenter)
        self.imagePlaceholder.setStyleSheet("color: #888;")
        self.imagePlaceholder.hide()
        grid.addWidget(self.imagePlaceholder, 0, 1, 3, 1)

        grid.setRowStretch(3, 1)

        self.retranslateUi()
```

Update imports at top of file:

```python
from PyQt5.QtCore import QT_TRANSLATE_NOOP, QTime, Qt
from PyQt5.QtWidgets import (
    QDateTimeEdit,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QSpinBox,
    QTimeEdit,
)
```

- [ ] **Step 4: Run all tests**

```bash
poetry run pytest tests/ui/test_media_cue_settings.py -v
```

Expected: both layout tests pass. `loadSettings` / `getSettings` behaviour unchanged.

- [ ] **Step 5: Commit**

```bash
git add lisp/ui/settings/cue_pages/media_cue.py tests/ui/test_media_cue_settings.py
git -c commit.gpgsign=false commit -m "refactor(media-cue-settings): two-column layout with waveform slot

Splits the inspector page into narrow-left (start/stop/loop fields)
and wide-right (reserved for the waveform trimmer — mounted in a
follow-up). Preserves existing load/get/enable semantics."
```

---

## Task 9: Stop-time sentinel → duration on load

**Files:**
- Modify: `lisp/ui/settings/cue_pages/media_cue.py`
- Test: `tests/ui/test_media_cue_settings.py`

The backend's `stop_time == 0` means "play to natural end". Show it as the full duration in the field so the user sees a meaningful value. **No round-trip on save** — `getSettings()` returns whatever the user typed verbatim; backend equivalence preserved because `stop_time >= duration` and `stop_time == 0` both fall through the `0 < stop_time < duration` guard.

- [ ] **Step 1: Write failing tests**

Append to `tests/ui/test_media_cue_settings.py`:

```python
class TestStopTimeSentinelMapping:
    def test_zero_stop_time_displays_as_duration(self, qtbot):
        """stop_time == 0 with a known duration displays as duration."""
        page = MediaCueSettings()
        qtbot.addWidget(page)
        page.loadSettings(
            {"media": {"stop_time": 0, "duration": 180_000, "start_time": 0}}
        )

        assert page.stopEdit.time() == QTime.fromMSecsSinceStartOfDay(180_000)

    def test_nonzero_stop_time_displays_verbatim(self, qtbot):
        page = MediaCueSettings()
        qtbot.addWidget(page)
        page.loadSettings(
            {
                "media": {
                    "stop_time": 60_000,
                    "duration": 180_000,
                    "start_time": 0,
                }
            }
        )

        assert page.stopEdit.time() == QTime.fromMSecsSinceStartOfDay(60_000)

    def test_get_settings_returns_typed_value_verbatim(self, qtbot):
        """No sentinel translation on save — what the user sees is what persists."""
        page = MediaCueSettings()
        qtbot.addWidget(page)
        page.loadSettings(
            {"media": {"stop_time": 0, "duration": 180_000, "start_time": 0}}
        )

        settings = page.getSettings()
        assert settings["media"]["stop_time"] == 180_000

    def test_zero_duration_leaves_zero(self, qtbot):
        """When duration is unknown, the 0 sentinel can't be translated."""
        page = MediaCueSettings()
        qtbot.addWidget(page)
        page.loadSettings(
            {"media": {"stop_time": 0, "duration": 0, "start_time": 0}}
        )

        assert page.stopEdit.time() == QTime.fromMSecsSinceStartOfDay(0)
```

- [ ] **Step 2: Run to verify fail**

```bash
poetry run pytest tests/ui/test_media_cue_settings.py::TestStopTimeSentinelMapping -v
```

Expected: `test_zero_stop_time_displays_as_duration` fails (shows 0 currently).

- [ ] **Step 3: Patch `loadSettings`**

Replace `loadSettings` in `lisp/ui/settings/cue_pages/media_cue.py` with:

```python
    def loadSettings(self, settings):
        settings = settings.get("media", {})

        if "loop" in settings:
            self.spinLoop.setValue(settings["loop"])

        duration = settings.get("duration", 0)
        time = self._to_qtime(duration)
        self.startEdit.setMaximumTime(time)
        self.stopEdit.setMaximumTime(time)

        if "start_time" in settings:
            self.startEdit.setTime(self._to_qtime(settings["start_time"]))

        if "stop_time" in settings:
            stop_display = self._display_stop(settings["stop_time"], duration)
            self.stopEdit.setTime(self._to_qtime(stop_display))

    @staticmethod
    def _display_stop(stored_ms: int, duration_ms: int) -> int:
        """Map the ``0`` sentinel to duration for display.

        The backend treats ``stop_time == 0`` as "play to natural end";
        showing a literal zero in the field is confusing. Mapping to
        duration is display-only — ``getSettings()`` returns the field
        verbatim, so a save after a sentinel-mapped load will persist
        ``duration`` instead of ``0``. The two are behaviourally
        equivalent: both fall through the ``0 < stop_time < duration``
        guard in ``gst_media`` and play to natural end.
        """
        if stored_ms == 0 and duration_ms > 0:
            return duration_ms
        return stored_ms
```

- [ ] **Step 4: Run to verify pass**

```bash
poetry run pytest tests/ui/test_media_cue_settings.py -v
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add lisp/ui/settings/cue_pages/media_cue.py tests/ui/test_media_cue_settings.py
git -c commit.gpgsign=false commit -m "feat(media-cue-settings): map stop_time=0 to duration on display

The field no longer shows an opaque 0:00:00 placeholder. Save path
unchanged — what the user sees is what persists. Backend behaviour
preserved: stop_time >= duration is equivalent to stop_time == 0."
```

---

## Task 10: Image-cue detection — disable trim fields

**Files:**
- Modify: `lisp/ui/settings/cue_pages/media_cue.py`
- Test: `tests/ui/test_media_cue_settings.py`

When the cue's media contains an `ImageInput` element, both `start_time` and `stop_time` are no-ops (see `image_input.py:42-49`). Disable the fields with an explanatory caption. The Loop field stays enabled (existing behaviour).

- [ ] **Step 1: Write failing tests**

Append:

```python
class TestImageCueHandling:
    def test_image_cue_disables_trim_fields(self, qtbot):
        page = MediaCueSettings()
        qtbot.addWidget(page)
        page.loadSettings(
            {
                "media": {
                    "stop_time": 0,
                    "duration": 5_000,
                    "start_time": 0,
                    "_element_classes": ["ImageInput", "VideoSink"],
                }
            }
        )

        assert not page.startEdit.isEnabled()
        assert not page.stopEdit.isEnabled()

    def test_image_cue_loop_field_stays_enabled(self, qtbot):
        page = MediaCueSettings()
        qtbot.addWidget(page)
        page.loadSettings(
            {
                "media": {
                    "stop_time": 0,
                    "duration": 5_000,
                    "_element_classes": ["ImageInput"],
                    "loop": 0,
                }
            }
        )
        assert page.spinLoop.isEnabled()

    def test_audio_cue_fields_stay_enabled(self, qtbot):
        page = MediaCueSettings()
        qtbot.addWidget(page)
        page.loadSettings(
            {
                "media": {
                    "stop_time": 60_000,
                    "duration": 180_000,
                    "_element_classes": ["UriInput", "Volume"],
                }
            }
        )
        assert page.startEdit.isEnabled()
        assert page.stopEdit.isEnabled()
```

**Note:** `_element_classes` is a synthetic key passed by the test to simulate the list of element class names on a real cue. The production load path reads the live `media.elements` list; the test uses this key to avoid constructing a full GstMedia. See Step 3 — `loadSettings` consults either source.

- [ ] **Step 2: Run to verify fail**

```bash
poetry run pytest tests/ui/test_media_cue_settings.py::TestImageCueHandling -v
```

Expected: all three fail — fields always enabled today.

- [ ] **Step 3: Implement image detection**

Add helper and hook into `loadSettings`. In `media_cue.py`:

```python
    def loadSettings(self, settings):
        media = settings.get("media", {})
        is_image = self._is_image_cue(media)

        if "loop" in media:
            self.spinLoop.setValue(media["loop"])

        duration = media.get("duration", 0)
        time = self._to_qtime(duration)
        self.startEdit.setMaximumTime(time)
        self.stopEdit.setMaximumTime(time)

        if "start_time" in media:
            self.startEdit.setTime(self._to_qtime(media["start_time"]))

        if "stop_time" in media:
            stop_display = self._display_stop(media["stop_time"], duration)
            self.stopEdit.setTime(self._to_qtime(stop_display))

        # Image cues: trim fields are no-ops (imagefreeze ignores seek).
        self.startEdit.setEnabled(not is_image)
        self.stopEdit.setEnabled(not is_image)

    @staticmethod
    def _is_image_cue(media_settings: dict) -> bool:
        """Detect an image cue by its element class list.

        Production calls pass ``_element_classes`` as a list of
        class-name strings derived from ``cue.media.elements``; tests
        can pass the key directly.
        """
        classes = media_settings.get("_element_classes", [])
        return "ImageInput" in classes
```

**Wiring the production path:** callers of `MediaCueSettings.loadSettings` are the inspector framework — `lisp/ui/inspector/` dispatches the cue's `properties(defaults=True)` dict into the page. MediaCue's properties include `media` (the GstMedia instance's serialized dict). We need to inject `_element_classes` upstream or read it from the live cue.

Cleaner: have the page read the live cue object through its existing binding. The inspector already passes the cue via `properties()`. Look at how other pages access element state — `cue_general.py` reads `settings["stylesheet"]` (already serialized).

Actually the simplest correct approach: accept that `settings["media"]` is a dict (GstMedia.__getstate__) and probe for an `"ImageInput"` entry inside it. GstMedia serializes each element class as a key under the media dict. Let me verify:

```bash
grep -n "elements.*update_properties\|class_defaults\|GstMediaElements" lisp/plugins/gst_backend/gst_media_elements.py
```

Given the class_defaults() key pattern, `media_settings` will contain `"ImageInput"` as a top-level key when an ImageInput is present. Replace `_is_image_cue`:

```python
    @staticmethod
    def _is_image_cue(media_settings: dict) -> bool:
        """An image cue has an ``ImageInput`` element in its media dict.

        ``GstMedia.__getstate__`` flattens each element's state under
        a key named after the element class. Test callers may inject
        ``_element_classes`` directly to avoid constructing a full
        media; production passes the real serialized dict.
        """
        if "ImageInput" in media_settings:
            return True
        return "ImageInput" in media_settings.get("_element_classes", [])
```

- [ ] **Step 4: Run to verify pass**

```bash
poetry run pytest tests/ui/test_media_cue_settings.py -v
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add lisp/ui/settings/cue_pages/media_cue.py tests/ui/test_media_cue_settings.py
git -c commit.gpgsign=false commit -m "feat(media-cue-settings): disable trim fields for image cues

imagefreeze ignores GStreamer seek stop positions and images have no
start offset, so start_time/stop_time are no-ops. Disable the fields
so the UI stops offering knobs that don't turn anything. Loop still
applies (the EOS timer re-arms on each loop iteration)."
```

---

## Task 11: Multi-select placeholder

**Files:**
- Modify: `lisp/ui/settings/cue_pages/media_cue.py`
- Test: `tests/ui/test_media_cue_settings.py`

When the inspector is showing more than one cue, waveforms can't meaningfully compose — hide the waveform slot and show a placeholder. Numeric fields continue to work via the existing checkable-group pattern.

- [ ] **Step 1: Write failing test**

Append:

```python
class TestMultiSelectPlaceholder:
    def test_single_cue_shows_waveform_slot(self, qtbot):
        page = MediaCueSettings()
        qtbot.addWidget(page)
        page.loadSettings({"media": {"duration": 10_000}})
        assert not page.placeholderLabel.isVisible() or not page.isVisible()
        # More meaningful once visible:
        page.show()
        qtbot.waitExposed(page)
        assert not page.placeholderLabel.isVisible()

    def test_enable_check_true_shows_placeholder(self, qtbot):
        """enableCheck(True) is how the inspector signals multi-select."""
        page = MediaCueSettings()
        qtbot.addWidget(page)
        page.show()
        qtbot.waitExposed(page)

        page.enableCheck(True)
        assert page.placeholderLabel.isVisible()
```

- [ ] **Step 2: Run to verify fail**

```bash
poetry run pytest tests/ui/test_media_cue_settings.py::TestMultiSelectPlaceholder -v
```

Expected: the second test fails (no placeholder toggling in enableCheck).

- [ ] **Step 3: Hook `enableCheck`**

Update `enableCheck`:

```python
    def enableCheck(self, enabled):
        self.setGroupEnabled(self.startGroup, enabled)
        self.setGroupEnabled(self.stopGroup, enabled)
        self.setGroupEnabled(self.loopGroup, enabled)
        # Multi-select: the inspector calls enableCheck(True) when more
        # than one cue is focused. Waveforms don't compose across cues,
        # so hide the trimmer and show a placeholder caption.
        self.placeholderLabel.setText(
            translate("MediaCueSettings", "Select a single cue")
            if enabled
            else ""
        )
        self.placeholderLabel.setVisible(enabled)
```

- [ ] **Step 4: Run to verify pass**

```bash
poetry run pytest tests/ui/test_media_cue_settings.py -v
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add lisp/ui/settings/cue_pages/media_cue.py tests/ui/test_media_cue_settings.py
git -c commit.gpgsign=false commit -m "feat(media-cue-settings): multi-select placeholder caption

Waveforms don't compose across cues. In multi-select, hide the
trimmer slot and show 'Select a single cue'. Numeric fields
continue to accept multi-edit via their checkable groups."
```

---

## Task 12: Mount the waveform trimmer + live sync (numeric ↔ marker)

**Files:**
- Modify: `lisp/ui/settings/cue_pages/media_cue.py`
- Test: `tests/ui/test_media_cue_settings.py`

This is the meat. `loadSettings` takes a live cue reference (not just a settings dict) so it can construct a `TrimmableWaveformWidget` from `get_backend().media_waveform(cue.media)`. Bidirectional sync keeps fields and markers coherent.

**The `loadSettings` API currently only gets a `settings` dict** — the cue reference isn't passed. The cleanest extension is to read the cue via the inspector engine's existing binding plumbing, but the quickest correct approach is to let the page cache a cue reference through a setter that the inspector calls.

Inspecting `lisp/ui/inspector/commit.py:220` (from the spec) shows the engine already binds to `commit_requested`. The inspector dispatches `loadSettings(settings)` where `settings` is built from `cue.properties()`. For the waveform, we need the live media object — we'll wire a new page-level method `setCue(cue)` that the inspector calls alongside `loadSettings`.

- [ ] **Step 1: Write failing sync tests**

Append:

```python
class TestWaveformTrimmerSync:
    def _load_with_waveform(self, page, qtbot, duration=10_000):
        waveform = _FakeWaveform(duration_ms=duration)
        page._install_waveform(waveform, use_timeline=False)
        page.loadSettings(
            {
                "media": {
                    "duration": duration,
                    "start_time": 0,
                    "stop_time": 0,
                }
            }
        )
        qtbot.wait(10)
        return waveform

    def test_trimmer_created_after_install(self, qtbot):
        page = MediaCueSettings()
        qtbot.addWidget(page)
        self._load_with_waveform(page, qtbot)
        assert page.trimmer is not None

    def test_typed_start_time_moves_marker(self, qtbot):
        page = MediaCueSettings()
        qtbot.addWidget(page)
        self._load_with_waveform(page, qtbot)

        page.startEdit.setTime(QTime.fromMSecsSinceStartOfDay(3_000))
        qtbot.wait(10)
        assert page.trimmer.startTime() == 3_000

    def test_marker_drag_updates_start_field(self, qtbot):
        page = MediaCueSettings()
        qtbot.addWidget(page)
        self._load_with_waveform(page, qtbot)

        page.trimmer.setStartTime(4_000)
        qtbot.wait(10)
        assert page.startEdit.time() == QTime.fromMSecsSinceStartOfDay(4_000)

    def test_start_field_tracks_stop_as_upper_bound(self, qtbot):
        page = MediaCueSettings()
        qtbot.addWidget(page)
        self._load_with_waveform(page, qtbot)

        page.stopEdit.setTime(QTime.fromMSecsSinceStartOfDay(5_000))
        qtbot.wait(10)
        assert (
            page.startEdit.maximumTime()
            == QTime.fromMSecsSinceStartOfDay(4_999)
        )

    def test_stop_field_tracks_start_as_lower_bound(self, qtbot):
        page = MediaCueSettings()
        qtbot.addWidget(page)
        self._load_with_waveform(page, qtbot)

        page.startEdit.setTime(QTime.fromMSecsSinceStartOfDay(3_000))
        qtbot.wait(10)
        assert (
            page.stopEdit.minimumTime()
            == QTime.fromMSecsSinceStartOfDay(3_001)
        )

    def test_sync_does_not_recurse(self, qtbot):
        """Typing a value must not re-enter via the marker signal."""
        page = MediaCueSettings()
        qtbot.addWidget(page)
        self._load_with_waveform(page, qtbot)

        calls = {"field": 0, "marker": 0}
        page.startEdit.timeChanged.connect(lambda *_: calls.__setitem__("field", calls["field"] + 1))
        page.trimmer.startTimeChanged.connect(lambda *_: calls.__setitem__("marker", calls["marker"] + 1))

        page.startEdit.setTime(QTime.fromMSecsSinceStartOfDay(2_500))
        qtbot.wait(10)

        # Exactly one round: field emitted once, marker emitted 0 (silent update).
        assert calls["field"] == 1
        assert calls["marker"] == 0
```

- [ ] **Step 2: Run to verify fail**

```bash
poetry run pytest tests/ui/test_media_cue_settings.py::TestWaveformTrimmerSync -v
```

Expected: `AttributeError: 'MediaCueSettings' object has no attribute '_install_waveform'`.

- [ ] **Step 3: Implement `_install_waveform` + sync wiring**

Add to `media_cue.py`:

```python
    def _install_waveform(self, waveform_or_duration, use_timeline: bool):
        """Mount the trim widget into the right column.

        Parameters
        ----------
        waveform_or_duration
            A ``Waveform`` (for audio/video cues) or an ``int`` duration
            in ms (for the timeline fallback after decode failure).
        use_timeline
            ``True`` → use ``TrimmableTimelineWidget`` (failure fallback).
            ``False`` → use ``TrimmableWaveformWidget``.
        """
        # Tear down any existing trimmer first.
        if self._waveformSlot is not None:
            self.layout().removeWidget(self._waveformSlot)
            self._waveformSlot.deleteLater()
            self._waveformSlot = None
            self.trimmer = None
        self.imagePlaceholder.hide()

        if use_timeline:
            duration = (
                waveform_or_duration.duration
                if hasattr(waveform_or_duration, "duration")
                else int(waveform_or_duration)
            )
            slot = TrimmableTimelineWidget(duration_ms=duration, parent=self)
        else:
            slot = TrimmableWaveformWidget(waveform_or_duration, parent=self)

        slot.setMinimumHeight(120)
        row, row_span = self._waveformRow
        self.layout().addWidget(slot, row, 1, row_span, 1)
        self._waveformSlot = slot
        self.trimmer = slot

        # Wire bidirectional sync. ``silent=True`` and ``blockSignals``
        # form the cycle breaker.
        self.startEdit.timeChanged.connect(self._on_start_edit_changed)
        self.stopEdit.timeChanged.connect(self._on_stop_edit_changed)
        self.trimmer.startTimeChanged.connect(self._on_trim_start_changed)
        self.trimmer.stopTimeChanged.connect(self._on_trim_stop_changed)
        self.trimmer.trimReleased.connect(self.commit_requested.emit)

    def _ms(self, qtime) -> int:
        return qtime.msecsSinceStartOfDay()

    def _on_start_edit_changed(self, qtime):
        if self.trimmer is None:
            return
        ms = self._ms(qtime)
        self.trimmer.setStartTime(ms, silent=True)
        stop_max = max(0, self.trimmer.stopTime() - 1)
        self.stopEdit.setMinimumTime(self._to_qtime(ms + 1))
        # Also update start's own upper bound from stop.
        self.startEdit.setMaximumTime(self._to_qtime(stop_max))

    def _on_stop_edit_changed(self, qtime):
        if self.trimmer is None:
            return
        ms = self._ms(qtime)
        self.trimmer.setStopTime(ms, silent=True)
        self.startEdit.setMaximumTime(self._to_qtime(max(0, ms - 1)))

    def _on_trim_start_changed(self, ms: int):
        self.startEdit.blockSignals(True)
        self.startEdit.setTime(self._to_qtime(ms))
        self.startEdit.blockSignals(False)
        self.stopEdit.setMinimumTime(self._to_qtime(ms + 1))

    def _on_trim_stop_changed(self, ms: int):
        self.stopEdit.blockSignals(True)
        self.stopEdit.setTime(self._to_qtime(ms))
        self.stopEdit.blockSignals(False)
        self.startEdit.setMaximumTime(self._to_qtime(max(0, ms - 1)))
```

Add attribute init at the end of `__init__`:

```python
        self.trimmer = None
```

Add imports at top of `media_cue.py`:

```python
from lisp.ui.widgets.waveform import (
    TrimmableTimelineWidget,
    TrimmableWaveformWidget,
)
```

- [ ] **Step 4: Run to verify pass**

```bash
poetry run pytest tests/ui/test_media_cue_settings.py -v
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add lisp/ui/settings/cue_pages/media_cue.py tests/ui/test_media_cue_settings.py
git -c commit.gpgsign=false commit -m "feat(media-cue-settings): bidirectional sync between fields and waveform

_install_waveform mounts a TrimmableWaveformWidget (or timeline
fallback) into the right column and wires the start/stop field
handlers so edits in either surface propagate to the other. Cycle
broken with silent=True on the trimmer side and blockSignals on
the QTimeEdit side."
```

---

## Task 13: Inspector wiring — construct the waveform from the live cue

**Files:**
- Modify: `lisp/ui/settings/cue_pages/media_cue.py`
- Test: `tests/ui/test_media_cue_settings.py`

Call `_install_waveform` from `loadSettings` using the existing backend factory. The settings dict's `_element_classes` (image detection) doubles here: if `is_image`, we mount a timeline fallback; otherwise we attempt to get a waveform from the backend.

The existing `loadSettings(settings)` doesn't have access to the live media object. Path forward: `MediaCueSettings` accepts a `cue` reference via a new method `setCue(cue)`, called by the inspector before `loadSettings`. The inspector framework at `lisp/ui/inspector/` — specifically where it constructs pages — needs one extra line to invoke it. Search first:

```bash
grep -rn "page.loadSettings\|MediaCueSettings\|settings_page" lisp/ui/inspector/ lisp/ui/settings/ 2>/dev/null | head -20
```

Whatever you find, add the `setCue` call adjacent to where `loadSettings` is called. If the inspector passes a list (multi-select), pass `None` for cue.

- [ ] **Step 1: Write failing test**

Append:

```python
class TestCueInstallation:
    def test_set_cue_installs_waveform_for_audio(self, qtbot, monkeypatch):
        """Wiring the live cue auto-mounts a TrimmableWaveformWidget."""
        fake_waveform = _FakeWaveform(duration_ms=10_000)

        class _FakeMedia:
            def __init__(self):
                self.duration = 10_000
                self.elements = {}

            def input_uri(self):
                return "file:///fake.wav"

        class _FakeCue:
            def __init__(self):
                self.media = _FakeMedia()

            def properties(self, **_):
                return {"media": {"duration": 10_000}}

        class _FakeBackend:
            def media_waveform(self, media):
                return fake_waveform

        monkeypatch.setattr(
            "lisp.ui.settings.cue_pages.media_cue.get_backend",
            lambda: _FakeBackend(),
        )

        page = MediaCueSettings()
        qtbot.addWidget(page)
        page.setCue(_FakeCue())
        page.loadSettings(
            {"media": {"duration": 10_000, "start_time": 0, "stop_time": 0}}
        )
        qtbot.wait(10)

        from lisp.ui.widgets.waveform import TrimmableWaveformWidget
        assert isinstance(page.trimmer, TrimmableWaveformWidget)

    def test_set_cue_shows_image_placeholder(self, qtbot, monkeypatch):
        """Image cues: no trimmer widget, placeholder caption in the slot."""
        class _FakeMedia:
            def __init__(self):
                self.duration = 5_000
                self.elements = {"ImageInput": object()}

            def input_uri(self):
                return "file:///fake.jpg"

        class _FakeCue:
            def __init__(self):
                self.media = _FakeMedia()

            def properties(self, **_):
                return {
                    "media": {
                        "duration": 5_000,
                        "ImageInput": {},
                    }
                }

        page = MediaCueSettings()
        qtbot.addWidget(page)
        page.setCue(_FakeCue())
        page.loadSettings(
            {
                "media": {
                    "duration": 5_000,
                    "ImageInput": {},
                    "start_time": 0,
                    "stop_time": 0,
                }
            }
        )
        page.show()
        qtbot.waitExposed(page)

        assert page.trimmer is None
        assert page.imagePlaceholder.isVisible()

    def test_set_cue_none_hides_waveform(self, qtbot):
        page = MediaCueSettings()
        qtbot.addWidget(page)
        page.setCue(None)  # multi-select path
        page.loadSettings({"media": {"duration": 0}})
        qtbot.wait(10)

        assert page.trimmer is None
```

- [ ] **Step 2: Run to verify fail**

```bash
poetry run pytest tests/ui/test_media_cue_settings.py::TestCueInstallation -v
```

Expected: `AttributeError: 'MediaCueSettings' object has no attribute 'setCue'`.

- [ ] **Step 3: Add `setCue` and auto-install in `loadSettings`**

Add to `media_cue.py`:

```python
from lisp.backend import get_backend
```

```python
    def setCue(self, cue):
        """Bind the live cue. Called by the inspector before loadSettings."""
        self._cue = cue

    def loadSettings(self, settings):
        media = settings.get("media", {})
        is_image = self._is_image_cue(media)
        duration = media.get("duration", 0)

        # (existing field-update logic here — unchanged)
        if "loop" in media:
            self.spinLoop.setValue(media["loop"])

        time = self._to_qtime(duration)
        self.startEdit.setMaximumTime(time)
        self.stopEdit.setMaximumTime(time)

        if "start_time" in media:
            self.startEdit.setTime(self._to_qtime(media["start_time"]))

        if "stop_time" in media:
            stop_display = self._display_stop(media["stop_time"], duration)
            self.stopEdit.setTime(self._to_qtime(stop_display))

        self.startEdit.setEnabled(not is_image)
        self.stopEdit.setEnabled(not is_image)

        # Install the trimmer if we have a live cue.
        cue = getattr(self, "_cue", None)
        if cue is None:
            self._teardown_trimmer()
            return

        if is_image:
            self._show_image_placeholder()
        else:
            waveform = get_backend().media_waveform(cue.media)
            self._install_waveform(waveform, use_timeline=False)

    def _teardown_trimmer(self):
        if self._waveformSlot is not None:
            self.layout().removeWidget(self._waveformSlot)
            self._waveformSlot.deleteLater()
            self._waveformSlot = None
            self.trimmer = None
        self.imagePlaceholder.hide()

    def _show_image_placeholder(self):
        """Swap in the 'Trimming does not apply' caption for image cues.

        Image cues go through imagefreeze, which ignores GStreamer seek
        stop positions — so start_time and stop_time are no-ops. The
        fields are disabled upstream in loadSettings; here we replace
        the waveform slot with a bare caption so nothing hints at a
        trim UI that won't work.
        """
        self._teardown_trimmer()  # strips any prior trimmer but keeps label handle
        self.imagePlaceholder.setText(
            translate(
                "MediaCueSettings",
                "Trimming does not apply to image cues.",
            )
        )
        self.imagePlaceholder.show()
```

Also add the attribute default in `__init__`:

```python
        self._cue = None
```

Now wire the inspector. Find the page-load call:

```bash
grep -rn "MediaCueSettings\|page.loadSettings\|dataProvider" lisp/ui/inspector/ lisp/ui/settings/ 2>/dev/null | head -15
```

In whatever file dispatches `loadSettings` to the media page, add a preceding `page.setCue(cue if not multi else None)`. The exact file is discovered in the search above — most likely `lisp/ui/inspector/inspector.py` or `lisp/ui/settings/cue_settings.py`. Add minimal wiring: just before the `page.loadSettings(...)` call for the media page, call `page.setCue(cue)` when the page exposes that method:

```python
        if hasattr(page, "setCue"):
            page.setCue(cue if len(cues) == 1 else None)
        page.loadSettings(settings)
```

- [ ] **Step 4: Run to verify pass**

```bash
poetry run pytest tests/ui/test_media_cue_settings.py -v
```

Expected: all pass.

- [ ] **Step 5: Manual smoke test**

```bash
poetry run linux-show-player -l debug
```

Open a session with a media cue, open its inspector. Verify:
- Waveform appears in right column.
- Stop Time field shows cue duration (not 0:00:00) when never-trimmed.
- Dragging a marker updates the field.
- Typing into the field moves the marker.
- Image cue: fields disabled, timeline fallback shown.
- Multi-select: waveform hidden.

- [ ] **Step 6: Commit**

```bash
git add lisp/ui/settings/cue_pages/media_cue.py tests/ui/test_media_cue_settings.py lisp/ui/inspector/
git -c commit.gpgsign=false commit -m "feat(media-cue-settings): mount trimmer via live cue + backend waveform

setCue() binds the live cue so loadSettings can pull the waveform
from get_backend().media_waveform(cue.media). Image cues get the
timeline fallback. Multi-select (cue=None) tears down the trimmer."
```

---

## Task 14: Waveform failure → timeline fallback

**Files:**
- Modify: `lisp/ui/settings/cue_pages/media_cue.py`
- Test: `tests/ui/test_media_cue_settings.py`

If the backend emits `failed` (decode error, audio-less video), swap to the flat-timeline widget without losing the current start/stop.

- [ ] **Step 1: Write failing test**

Append:

```python
class TestWaveformFailureFallback:
    def test_failed_signal_swaps_to_timeline(self, qtbot, monkeypatch):
        fake_waveform = _FakeWaveform(duration_ms=10_000)

        class _FakeMedia:
            def __init__(self):
                self.duration = 10_000
                self.elements = {}

            def input_uri(self):
                return "file:///fake.mp4"

        class _FakeCue:
            def __init__(self):
                self.media = _FakeMedia()

            def properties(self, **_):
                return {"media": {"duration": 10_000}}

        monkeypatch.setattr(
            "lisp.ui.settings.cue_pages.media_cue.get_backend",
            lambda: type("_B", (), {"media_waveform": lambda s, m: fake_waveform})(),
        )

        page = MediaCueSettings()
        qtbot.addWidget(page)
        page.setCue(_FakeCue())
        page.loadSettings({"media": {"duration": 10_000}})
        qtbot.wait(10)

        from lisp.ui.widgets.waveform import (
            TrimmableTimelineWidget,
            TrimmableWaveformWidget,
        )
        assert isinstance(page.trimmer, TrimmableWaveformWidget)

        fake_waveform.mark_failed()
        qtbot.wait(10)

        assert isinstance(page.trimmer, TrimmableTimelineWidget)
```

- [ ] **Step 2: Run to verify fail**

```bash
poetry run pytest tests/ui/test_media_cue_settings.py::TestWaveformFailureFallback -v
```

Expected: the trimmer stays a `TrimmableWaveformWidget`.

- [ ] **Step 3: Hook the `failed` signal in `_install_waveform`**

Modify the else branch of `_install_waveform`:

```python
        else:
            slot = TrimmableWaveformWidget(waveform_or_duration, parent=self)
            waveform_or_duration.failed.connect(
                lambda: self._swap_to_timeline(
                    waveform_or_duration.duration
                ),
                Connection.QtQueued,
            )
```

Add the import:

```python
from lisp.core.signal import Connection
```

Add method:

```python
    def _swap_to_timeline(self, duration_ms: int):
        if isinstance(self._waveformSlot, TrimmableTimelineWidget):
            return  # already swapped
        start = self.trimmer.startTime() if self.trimmer else 0
        stop = self.trimmer.stopTime() if self.trimmer else duration_ms
        self._install_waveform(duration_ms, use_timeline=True)
        self.trimmer.setStartTime(start, silent=True)
        self.trimmer.setStopTime(stop, silent=True)
```

- [ ] **Step 4: Run to verify pass**

```bash
poetry run pytest tests/ui/test_media_cue_settings.py -v
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add lisp/ui/settings/cue_pages/media_cue.py tests/ui/test_media_cue_settings.py
git -c commit.gpgsign=false commit -m "feat(media-cue-settings): fall back to timeline on waveform failure

An audio-less video (or decode error) fires Waveform.failed.
Swap the trimmer to the flat-timeline fallback so users keep a
working trim surface."
```

---

## Task 15: i18n refresh

**Files:**
- Modify: `lisp/i18n/ts/*.ts` (regenerated)

- [ ] **Step 1: Regenerate translation source files**

```bash
python i18n_update.py
```

This picks up the new translatable strings introduced by this feature:
- `translate("MediaCueSettings", "Select a single cue")` (Task 11)
- `translate("MediaCueSettings", "Trimming does not apply to image cues.")` (Task 13)

- [ ] **Step 2: Commit regenerated files**

```bash
git add lisp/i18n/ts/
git -c commit.gpgsign=false commit -m "i18n: refresh translation sources for media cue waveform"
```

---

## Task 16: Full test run + lint

- [ ] **Step 1: Run the full test suite**

```bash
poetry run pytest tests/ -v
```

Expected: all tests pass. No regressions in `tests/plugins/list_layout/test_playing_widgets.py` (the running-cue panel still uses the unchanged `WaveformSlider`).

- [ ] **Step 2: Lint**

```bash
poetry run ruff check lisp/
```

Expected: clean.

- [ ] **Step 3: Final commit for any lint fixups**

```bash
git add -u
git -c commit.gpgsign=false commit -m "chore: lint fixups for waveform trimmer" 2>/dev/null || echo "nothing to commit"
```

---

## Verification Checklist

Before declaring the plan done, confirm:

- [ ] `tests/ui/widgets/test_trimmable_waveform.py` has tests for: defaults, ready-updates-duration, setter clamps, silent flag, mouse press/drag/release, trimReleased-once-per-cycle, paint-no-crash, keyboard nudging, timeline widget.
- [ ] `tests/ui/test_media_cue_settings.py` has tests for: two-column layout, sentinel mapping, verbatim save, image-cue field-disable, multi-select placeholder, bidirectional sync, cross-clamp, cue installation (audio + image + None), failure fallback.
- [ ] Manual smoke: dragging a marker moves the numeric field; typing into the field moves the marker; Stop Time shows duration on first load of a never-trimmed cue; image cue disables fields; multi-select hides waveform.
- [ ] Running-cue panel (`lisp/plugins/list_layout/playing_widgets.py`) and existing `WaveformSlider` remain unchanged.
- [ ] No changes to `lisp/backend/waveform.py`, `gst_waveform.py`, or session file format.
