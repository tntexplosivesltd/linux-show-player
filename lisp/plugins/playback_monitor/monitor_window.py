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
from PyQt5.QtGui import QFont
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

    Milliseconds are truncated (not rounded). Negative values return
    00:00.
    """
    ms = max(0, int(milliseconds))
    total_seconds = ms // 1000
    minutes, seconds = divmod(total_seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours > 0:
        return f"{hours:02}:{minutes:02}:{seconds:02}"
    return f"{minutes:02}:{seconds:02}"


class PlaybackMonitorWindow(QWidget):
    closed = pyqtSignal()

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

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)

        # Cue name (small, at top)
        self._name_label = QLabel("\u2014")
        self._name_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self._name_label, 0)

        # "Elapsed" sub-label
        self._elapsed_label = QLabel(
            translate("PlaybackMonitor", "Elapsed")
        )
        self._elapsed_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self._elapsed_label, 0)

        # Elapsed time display
        self._elapsed_display = QLabel("00:00")
        self._elapsed_display.setAlignment(Qt.AlignCenter)
        layout.addWidget(self._elapsed_display, 1)

        # "Remaining" sub-label
        self._remaining_label = QLabel(
            translate("PlaybackMonitor", "Remaining")
        )
        self._remaining_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self._remaining_label, 0)

        # Remaining time display
        self._remaining_display = QLabel("00:00")
        self._remaining_display.setAlignment(Qt.AlignCenter)
        layout.addWidget(self._remaining_display, 1)

        # Restore saved geometry
        x = config.get("geometry.x", -1)
        y = config.get("geometry.y", -1)
        w = config.get("geometry.width", 400)
        h = config.get("geometry.height", 300)
        self.resize(w, h)
        if x >= 0 and y >= 0:
            self.move(x, y)

        self._update_fonts()

    def track_cue(self, cue):
        """Switch to tracking a new cue."""
        if self._cue_time is not None:
            self._cue_time.notify.disconnect(self._time_updated)

        self._tracked_cue = cue
        self._cue_time = CueTime(cue)
        self._cue_time.notify.connect(
            self._time_updated, Connection.QtQueued
        )
        self._name_label.setText(cue.name)

    def reset(self):
        """Return to idle state."""
        if self._cue_time is not None:
            self._cue_time.notify.disconnect(self._time_updated)
        self._tracked_cue = None
        self._cue_time = None
        self._name_label.setText("\u2014")
        self._elapsed_display.setText("00:00")
        self._remaining_display.setText("00:00")

    def _time_updated(self, time):
        if not self.isVisible():
            return

        # If time equals duration or is negative, treat as zero
        cue = self._tracked_cue
        if cue is None:
            return

        if (
            cue.duration > 0 and time == cue.duration
        ) or time < 0:
            time = 0

        self._elapsed_display.setText(
            format_monitor_time(time)
        )

        if cue.duration > 0:
            remaining = cue.duration - time
            self._remaining_display.setText(
                format_monitor_time(max(0, remaining))
            )
        else:
            self._remaining_display.setText("--:--")

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_fonts()

    def _update_fonts(self):
        h = self.height()

        name_size = max(10, int(h * 0.06))
        time_size = max(20, int(h * 0.25))
        label_size = max(8, int(h * 0.04))

        name_font = QFont()
        name_font.setPointSize(name_size)
        self._name_label.setFont(name_font)

        time_font = QFont()
        time_font.setPointSize(time_size)
        time_font.setBold(True)
        self._elapsed_display.setFont(time_font)
        self._remaining_display.setFont(time_font)

        label_font = QFont()
        label_font.setPointSize(label_size)
        self._elapsed_label.setFont(label_font)
        self._remaining_label.setFont(label_font)

    def contextMenuEvent(self, event):
        menu = QMenu(self)

        always_on_top = QAction(
            translate("PlaybackMonitor", "Always on Top"),
            self,
        )
        always_on_top.setCheckable(True)
        always_on_top.setChecked(
            bool(self.windowFlags() & Qt.WindowStaysOnTopHint)
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

        # setWindowFlags hides the widget, so restore state
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
