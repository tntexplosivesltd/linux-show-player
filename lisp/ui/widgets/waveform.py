from math import floor, ceil

from PyQt5.QtCore import QLineF, pyqtSignal, Qt, QRectF
from PyQt5.QtGui import QPainter, QPen, QColor, QBrush
from PyQt5.QtWidgets import QWidget

from lisp.backend.waveform import Waveform
from lisp.core.signal import Connection
from lisp.core.util import strtime
from lisp.ui.widgets.dynamicfontsize import DynamicFontSizeMixin


class WaveformWidget(QWidget):
    def __init__(self, waveform: Waveform, **kwargs):
        super().__init__(**kwargs)
        self._waveform = waveform
        self._maximum = self._waveform.duration
        self._valueToPx = 0
        self._value = 0
        self._lastDrawnValue = 0

        self.backgroundColor = QColor(32, 32, 32)
        self.backgroundRadius = 6
        self.elapsedPeakColor = QColor(75, 154, 250)
        self.elapsedRmsColor = QColor(153, 199, 255)
        self.remainsPeakColor = QColor(90, 90, 90)
        self.remainsRmsColor = QColor(130, 130, 130)

        # Watch for the waveform to be ready
        self._waveform.ready.connect(self._ready, Connection.QtQueued)
        # Load the waveform
        self._waveform.load_waveform()

    def _ready(self):
        self.setMaximum(self._waveform.duration)
        self.update()

    def detach(self):
        # Drop the ready-signal connection so a late queued emission
        # after the widget is scheduled for deletion can't fire _ready()
        # on a Qt-dead instance.
        try:
            self._waveform.ready.disconnect(self._ready)
        except (TypeError, ValueError):
            pass

    def maximum(self):
        return self._maximum

    def setMaximum(self, maximum):
        self._maximum = maximum
        self._valueToPx = self._maximum / self.width()
        self.update()

    def value(self):
        return self._value

    def setValue(self, value):
        self._value = min(value, self._maximum)

        # if we are not visible we can skip this
        if not self.visibleRegion().isEmpty():
            # Repaint only if we have new pixels to draw
            if self._value >= floor(self._lastDrawnValue + self._valueToPx):
                x = int(self._lastDrawnValue / self._valueToPx)
                width = int(
                    (self._value - self._lastDrawnValue) / self._valueToPx
                )
                # Repaint only the changed area
                self.update(x - 1, 0, width + 1, self.height())
            elif self._value <= ceil(self._lastDrawnValue - self._valueToPx):
                x = int(self._value / self._valueToPx)
                width = int(
                    (self._lastDrawnValue - self._value) / self._valueToPx
                )
                # Repaint only the changed area
                self.update(x - 1, 0, width + 2, self.height())

    def resizeEvent(self, event):
        self._valueToPx = self._maximum / self.width()

    def paintEvent(self, event):
        halfHeight = self.height() / 2
        painter = QPainter()
        painter.begin(self)

        # Draw the background (it will be clipped to event.rect())
        pen = QPen(QColor(0, 0, 0, 0))
        painter.setPen(pen)
        painter.setBrush(QBrush(self.backgroundColor))
        painter.setRenderHint(QPainter.Antialiasing)
        painter.drawRoundedRect(self.rect(), 6, 6)
        painter.setRenderHint(QPainter.Antialiasing, False)

        # Draw the weveform
        pen.setWidth(1)
        painter.setPen(pen)

        if self._valueToPx and self._waveform.is_ready():
            peakSamples = self._waveform.peak_samples
            rmsSamples = self._waveform.rms_samples
            samplesToPx = len(peakSamples) / self.width()
            elapsedWidth = floor(self._value / self._valueToPx)

            peakElapsedLines = []
            peakRemainsLines = []
            rmsElapsedLines = []
            rmsRemainsLines = []
            for x in range(event.rect().x(), event.rect().right() + 1):
                # Calculate re-sample interval
                s0 = floor(x * samplesToPx)
                s1 = ceil(x * samplesToPx + samplesToPx)
                # Re-sample the values
                peak = max(peakSamples[s0:s1]) * halfHeight
                rms = (sum(rmsSamples[s0:s1]) / samplesToPx) * halfHeight

                # Create lines to draw
                peakLine = QLineF(x, halfHeight + peak, x, halfHeight - peak)
                rmsLine = QLineF(x, halfHeight + rms, x, halfHeight - rms)

                # Decide if elapsed or remaining
                if x < elapsedWidth:
                    peakElapsedLines.append(peakLine)
                    rmsElapsedLines.append(rmsLine)
                else:
                    peakRemainsLines.append(peakLine)
                    rmsRemainsLines.append(rmsLine)

            # Draw peak for elapsed
            if peakElapsedLines:
                pen.setColor(self.elapsedPeakColor)
                painter.setPen(pen)
                painter.drawLines(peakElapsedLines)

            # Draw rms for elapsed
            if rmsElapsedLines:
                pen.setColor(self.elapsedRmsColor)
                painter.setPen(pen)
                painter.drawLines(rmsElapsedLines)

            # Draw peak for remaining
            if peakRemainsLines:
                pen.setColor(self.remainsPeakColor)
                painter.setPen(pen)
                painter.drawLines(peakRemainsLines)

            # Draw rms for remaining
            if rmsRemainsLines:
                pen.setColor(self.remainsRmsColor)
                painter.setPen(pen)
                painter.drawLines(rmsRemainsLines)

            # Remember the last drawn item
            self._lastDrawnValue = self._value
        else:
            # Draw a single line in the middle
            pen.setColor(self.remainsRmsColor)
            painter.setPen(pen)
            painter.drawLine(QLineF(0, halfHeight, self.width(), halfHeight))

        painter.end()


class WaveformSlider(DynamicFontSizeMixin, WaveformWidget):
    """Implement an API similar to a QAbstractSlider."""

    FONT_PADDING = 1

    sliderMoved = pyqtSignal(int)
    sliderJumped = pyqtSignal(int)

    def __init__(self, waveform, **kwargs):
        super().__init__(waveform, **kwargs)
        self.setMouseTracking(True)

        self._lastPosition = -1
        self._mouseDown = False
        self._labelRight = True
        self._maxFontSize = self.font().pointSizeF()

        self.seekIndicatorColor = QColor(Qt.red)
        self.seekTimestampBG = QColor(32, 32, 32)
        self.seekTimestampFG = QColor(Qt.white)

    def _xToValue(self, x):
        return round(x * self._valueToPx)

    def leaveEvent(self, event):
        self._labelRight = True
        self._lastPosition = -1

    def mouseMoveEvent(self, event):
        self._lastPosition = event.x()
        self.update()

        if self._mouseDown:
            self.sliderMoved.emit(self._xToValue(self._lastPosition))

    def mousePressEvent(self, event):
        self._mouseDown = True

    def mouseReleaseEvent(self, event):
        self._mouseDown = False
        self.sliderJumped.emit(self._xToValue(event.x()))

    def resizeEvent(self, event):
        fontSize = self.getWidgetMaximumFontSize("0123456789")
        if fontSize > self._maxFontSize:
            fontSize = self._maxFontSize

        font = self.font()
        font.setPointSizeF(fontSize)
        self.setFont(font)

        super().resizeEvent(event)

    def paintEvent(self, event):
        # Draw the waveform
        super().paintEvent(event)

        # If needed (mouse-over) draw the seek indicator, and its timestamp
        if self._lastPosition >= 0:
            painter = QPainter()
            painter.begin(self)

            # Draw the indicator as a 1px vertical line
            pen = QPen()
            pen.setWidth(1)
            pen.setColor(self.seekIndicatorColor)
            painter.setPen(pen)
            painter.drawLine(
                self._lastPosition, 0, self._lastPosition, self.height()
            )

            # Get the timestamp of the indicator position
            text = strtime(self._xToValue(self._lastPosition))[:-3]
            textSize = self.fontMetrics().size(Qt.TextSingleLine, text)
            # Vertical offset to center the label
            vOffset = (self.height() - textSize.height()) / 2

            # Decide on which side of the indicator the label should be drawn
            left = self._lastPosition - textSize.width() - 14
            right = self._lastPosition + textSize.width() + 14
            if (self._labelRight and right < self.width()) or left < 0:
                xOffset = self._lastPosition + 6
                self._labelRight = True
            else:
                xOffset = self._lastPosition - textSize.width() - 14
                self._labelRight = False

            # Define the label rect, add 8px of width for left/right padding
            rect = QRectF(
                xOffset, vOffset, textSize.width() + 8, textSize.height()
            )

            # Draw the label rect
            pen.setColor(self.seekIndicatorColor.darker(150))
            painter.setPen(pen)
            painter.setBrush(QBrush(self.seekTimestampBG))
            painter.drawRoundedRect(rect, 2, 2)

            # Draw the timestamp
            pen.setColor(self.seekTimestampFG)
            painter.setPen(pen)
            painter.drawText(rect, Qt.AlignCenter, text)

            painter.end()


class _TrimMarkerInteractionMixin:
    """Shared mouse + keyboard handling for trimmable widgets.

    Expects the host to provide: ``_start_ms``, ``_stop_ms``,
    ``_active_marker``, ``setStartTime``, ``setStopTime``,
    ``trimReleased`` (pyqtSignal), ``_ms_per_px``, and ``_x_for``.
    """

    _NUDGE_STEP_MS = 100
    _NUDGE_COARSE_MS = 1_000

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

        step = (
            self._NUDGE_COARSE_MS
            if event.modifiers() & Qt.ShiftModifier
            else self._NUDGE_STEP_MS
        )
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


class TrimmableWaveformWidget(_TrimMarkerInteractionMixin, WaveformWidget):
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
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)

    def _ready(self):
        super()._ready()
        # Snap stop to the now-known duration, but only if the user
        # hasn't moved it past the previous default.
        if self._stop_ms == 0 or self._stop_ms > self._waveform.duration:
            self._stop_ms = self._waveform.duration
            self.stopTimeChanged.emit(self._stop_ms)
            self.update()

    def startTime(self) -> int:
        return self._start_ms

    def stopTime(self) -> int:
        return self._stop_ms

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

    _HIT_THRESHOLD_PX = 8

    def _ms_per_px(self) -> float:
        return self._valueToPx or 1.0

    def _x_for(self, ms: int) -> int:
        return int(ms / self._ms_per_px())

    def paintEvent(self, event):
        super().paintEvent(event)

        painter = QPainter()
        painter.begin(self)
        x_start = self._x_for(self._start_ms)
        x_stop = self._x_for(self._stop_ms)

        if x_stop > x_start:
            region_brush = QBrush(QColor(75, 154, 250, 40))
            painter.setPen(QPen(QColor(0, 0, 0, 0)))
            painter.setBrush(region_brush)
            painter.drawRect(
                x_start, 0, x_stop - x_start, self.height()
            )

        marker_pen = QPen(QColor(75, 154, 250))
        marker_pen.setWidth(2)
        painter.setPen(marker_pen)
        painter.drawLine(x_start, 0, x_start, self.height())
        painter.drawLine(x_stop, 0, x_stop, self.height())

        painter.end()


class TrimmableTimelineWidget(_TrimMarkerInteractionMixin, QWidget):
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
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)

        self.backgroundColor = QColor(32, 32, 32)
        self.lineColor = QColor(130, 130, 130)
        self.markerColor = QColor(75, 154, 250)
        self.regionColor = QColor(75, 154, 250, 40)

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
