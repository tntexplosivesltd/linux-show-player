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

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QFont, QFontMetrics
from PyQt5.QtWidgets import (
    QAction,
    QLabel,
    QMenu,
    QVBoxLayout,
    QWidget,
)

from lisp.core.signal import Connection
from lisp.cues.cue_time import CueTime
from lisp.ui.ui_utils import translate


def format_monitor_time(milliseconds):
    """Format milliseconds as MM:SS, or HH:MM:SS when >= 1 hour.

    Milliseconds are truncated (not rounded). Negative values
    return 00:00.
    """
    ms = max(0, int(milliseconds))
    total_seconds = ms // 1000
    minutes, seconds = divmod(total_seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours > 0:
        return f"{hours:02}:{minutes:02}:{seconds:02}"
    return f"{minutes:02}:{seconds:02}"


class PlaybackMonitorWindow(QWidget):
    """Resizable window showing elapsed/remaining time.

    Displays one time value large (primary) and the other small
    (secondary).  Click anywhere to swap which is primary.
    """

    closed = pyqtSignal()

    # True  = elapsed is primary (large)
    # False = remaining is primary (large)
    _elapsed_primary = True

    def __init__(self, config, **kwargs):
        super().__init__(**kwargs)
        self._config = config
        self._tracked_cue = None
        self._cue_time = None

        self.setWindowTitle(
            translate("PlaybackMonitor", "Playback Monitor")
        )
        flags = Qt.Window
        if config.get("alwaysOnTop", True):
            flags |= Qt.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        self.setMinimumSize(300, 200)
        self.setCursor(Qt.PointingHandCursor)

        self._elapsed_primary = config.get(
            "elapsedPrimary", True
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(2)

        # Cue name (small, at top, elided)
        self._name_label = QLabel("\u2014")
        self._name_label.setAlignment(Qt.AlignCenter)
        self._name_label.setTextFormat(Qt.PlainText)
        layout.addWidget(self._name_label, 0)

        # Primary time (large)
        self._primary_label = QLabel(
            self._primary_label_text()
        )
        self._primary_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self._primary_label, 0)

        self._primary_display = QLabel("00:00")
        self._primary_display.setAlignment(Qt.AlignCenter)
        layout.addWidget(self._primary_display, 1)

        # Secondary time (small)
        self._secondary_label = QLabel(
            self._secondary_label_text()
        )
        self._secondary_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self._secondary_label, 0)

        self._secondary_display = QLabel("00:00")
        self._secondary_display.setAlignment(Qt.AlignCenter)
        layout.addWidget(self._secondary_display, 0)

        # Restore saved geometry
        x = config.get("geometry.x", -1)
        y = config.get("geometry.y", -1)
        w = config.get("geometry.width", 400)
        h = config.get("geometry.height", 300)
        self.resize(w, h)
        if x >= 0 and y >= 0:
            self.move(x, y)

        self._update_fonts()

    # -- Public API used by the plugin --------------------------

    def track_cue(self, cue):
        """Switch to tracking a new cue."""
        if self._cue_time is not None:
            self._cue_time.notify.disconnect(
                self._time_updated
            )

        self._tracked_cue = cue
        self._cue_time = CueTime(cue)
        self._cue_time.notify.connect(
            self._time_updated, Connection.QtQueued
        )
        self._name_label.setText(cue.name)

        if cue.duration <= 0:
            self._set_times("00:00", "--:--")

    def reset(self):
        """Return to idle state."""
        if self._cue_time is not None:
            self._cue_time.notify.disconnect(
                self._time_updated
            )
        self._tracked_cue = None
        self._cue_time = None
        self._name_label.setText("\u2014")
        self._set_times("00:00", "00:00")

    # -- Internal helpers ---------------------------------------

    def _primary_label_text(self):
        if self._elapsed_primary:
            return translate("PlaybackMonitor", "Elapsed")
        return translate("PlaybackMonitor", "Remaining")

    def _secondary_label_text(self):
        if self._elapsed_primary:
            return translate("PlaybackMonitor", "Remaining")
        return translate("PlaybackMonitor", "Elapsed")

    def _set_times(self, elapsed_str, remaining_str):
        if self._elapsed_primary:
            self._primary_display.setText(elapsed_str)
            self._secondary_display.setText(remaining_str)
        else:
            self._primary_display.setText(remaining_str)
            self._secondary_display.setText(elapsed_str)

    @property
    def elapsed_text(self):
        if self._elapsed_primary:
            return self._primary_display.text()
        return self._secondary_display.text()

    @property
    def remaining_text(self):
        if self._elapsed_primary:
            return self._secondary_display.text()
        return self._primary_display.text()

    def _time_updated(self, time):
        if not self.isVisible():
            return

        cue = self._tracked_cue
        if cue is None:
            return

        if (
            cue.duration > 0 and time == cue.duration
        ) or time < 0:
            time = 0

        elapsed_str = format_monitor_time(time)

        if cue.duration > 0:
            remaining = cue.duration - time
            remaining_str = format_monitor_time(
                max(0, remaining)
            )
        else:
            remaining_str = "--:--"

        self._set_times(elapsed_str, remaining_str)

    # -- Click to swap primary/secondary ------------------------

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._elapsed_primary = not self._elapsed_primary
            self._config.set(
                "elapsedPrimary", self._elapsed_primary
            )
            self._config.write()

            self._primary_label.setText(
                self._primary_label_text()
            )
            self._secondary_label.setText(
                self._secondary_label_text()
            )

            # Swap the displayed values
            old_primary = self._primary_display.text()
            old_secondary = self._secondary_display.text()
            self._primary_display.setText(old_secondary)
            self._secondary_display.setText(old_primary)

            self._update_fonts()
        else:
            super().mousePressEvent(event)

    # -- Font scaling -------------------------------------------

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_fonts()

    def _update_fonts(self):
        h = self.height()
        # name 5%, primary-label 4%, primary 55%,
        # secondary-label 3%, secondary 10%
        self._fit_font(
            self._name_label, int(h * 0.05), bold=False
        )
        self._fit_font(
            self._primary_label, int(h * 0.04), bold=False
        )
        self._fit_font(
            self._primary_display, int(h * 0.55), bold=True
        )
        self._fit_font(
            self._secondary_label,
            int(h * 0.03),
            bold=False,
        )
        self._fit_font(
            self._secondary_display,
            int(h * 0.10),
            bold=True,
        )

    @staticmethod
    def _fit_font(label, target_px, bold=False):
        """Set the largest point size that fits target_px."""
        if target_px < 8:
            return
        font = QFont()
        font.setBold(bold)
        lo, hi = 6, target_px
        while lo < hi:
            mid = (lo + hi + 1) // 2
            font.setPointSize(mid)
            if QFontMetrics(font).height() <= target_px:
                lo = mid
            else:
                hi = mid - 1
        font.setPointSize(lo)
        label.setFont(font)

    # -- Context menu -------------------------------------------

    def contextMenuEvent(self, event):
        menu = QMenu(self)

        always_on_top = QAction(
            translate("PlaybackMonitor", "Always on Top"),
            self,
        )
        always_on_top.setCheckable(True)
        always_on_top.setChecked(
            bool(
                self.windowFlags() & Qt.WindowStaysOnTopHint
            )
        )
        always_on_top.triggered.connect(
            self._toggle_always_on_top
        )
        menu.addAction(always_on_top)
        menu.exec_(event.globalPos())

    def _toggle_always_on_top(self, checked):
        pos = self.pos()
        size = self.size()
        was_visible = self.isVisible()

        flags = self.windowFlags()
        if checked:
            flags |= Qt.WindowStaysOnTopHint
        else:
            flags &= ~Qt.WindowStaysOnTopHint
        self.setWindowFlags(flags)

        self.resize(size)
        self.move(pos)
        if was_visible:
            self.show()

        self._config.set("alwaysOnTop", checked)
        self._config.write()

    def closeEvent(self, event):
        self._config.set("geometry.x", self.x())
        self._config.set("geometry.y", self.y())
        self._config.set("geometry.width", self.width())
        self._config.set("geometry.height", self.height())
        self._config.write()

        self.closed.emit()
        super().closeEvent(event)
