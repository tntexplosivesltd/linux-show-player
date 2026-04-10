# This file is part of Linux Show Player
#
# Copyright 2024 Francesco Ceruti <ceppofrancy@gmail.com>
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

from enum import Enum

from PyQt5.QtCore import (
    QEvent,
    QPoint,
    QPropertyAnimation,
    QEasingCurve,
    QTimer,
    Qt,
)
from PyQt5.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QVBoxLayout,
)


class NotificationLevel(Enum):
    Info = "info"
    Warning = "warning"


# Auto-dismiss durations in milliseconds
_DURATIONS = {
    NotificationLevel.Info: 4000,
    NotificationLevel.Warning: 6000,
}

# Progress bar update interval
_TICK_MS = 50

# Slide animation duration
_ANIM_MS = 250


class NotificationToast(QFrame):
    """Non-modal toast overlay for operator notifications.

    Positioned top-center over its parent widget. Supports two severity
    levels (Info, Warning) with auto-dismiss timers and deduplication.
    """

    def __init__(self, parent):
        super().__init__(parent)
        self.setObjectName("NotificationToast")
        self.hide()
        self.raise_()

        self._current_message = ""
        self._current_count = 0
        self._current_level = NotificationLevel.Info
        self._remaining_ms = 0
        self._duration_ms = 0

        # --- Layout ---
        self._outer_layout = QVBoxLayout(self)
        self._outer_layout.setContentsMargins(12, 8, 12, 4)
        self._outer_layout.setSpacing(6)

        self._content_layout = QHBoxLayout()
        self._content_layout.setContentsMargins(0, 0, 0, 0)
        self._content_layout.setSpacing(8)
        self._outer_layout.addLayout(self._content_layout)

        self._icon_label = QLabel(self)
        self._icon_label.setAlignment(Qt.AlignVCenter)
        self._content_layout.addWidget(self._icon_label)

        self._message_label = QLabel(self)
        self._message_label.setAlignment(
            Qt.AlignVCenter | Qt.AlignLeft
        )
        self._message_label.setWordWrap(True)
        self._content_layout.addWidget(self._message_label, 1)

        self._progress = QProgressBar(self)
        self._progress.setObjectName("NotificationToastProgress")
        self._progress.setTextVisible(False)
        self._progress.setFixedHeight(2)
        self._progress.setRange(0, 1000)
        self._outer_layout.addWidget(self._progress)

        # --- Timers ---
        self._dismiss_timer = QTimer(self)
        self._dismiss_timer.setInterval(_TICK_MS)
        self._dismiss_timer.timeout.connect(self._tick)

        # --- Animation ---
        self._anim = QPropertyAnimation(self, b"pos")
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._anim.setDuration(_ANIM_MS)

        # --- Event filter for parent resize ---
        if parent is not None:
            parent.installEventFilter(self)

    # -- Public API --

    def show_notification(self, message, level=NotificationLevel.Info):
        """Show or update a toast notification."""
        if self.isVisible() and message == self._current_message:
            # Deduplicate: same message, bump count and reset timer
            self._current_count += 1
            self._update_label()
            self._reset_timer()
            return

        # New or different message
        self._current_message = message
        self._current_count = 1
        self._current_level = level

        self._apply_level(level)
        self._update_label()
        self._reset_timer()

        # Let the layout settle, then constrain width
        self.setMaximumWidth(self._max_width())
        self.setMinimumWidth(0)
        self.adjustSize()

        if self.isVisible():
            # Already showing a different message — just reposition
            self._reposition()
        else:
            self._slide_in()

    # -- Dismiss --

    def dismiss(self):
        """Dismiss the toast (slide out)."""
        self._dismiss_timer.stop()
        self._slide_out()

    def mousePressEvent(self, event):
        self.dismiss()

    # -- Timer --

    def _reset_timer(self):
        self._duration_ms = _DURATIONS.get(
            self._current_level, 4000
        )
        self._remaining_ms = self._duration_ms
        self._progress.setValue(1000)
        self._dismiss_timer.start()

    def _tick(self):
        self._remaining_ms -= _TICK_MS
        if self._remaining_ms <= 0:
            self.dismiss()
            return

        ratio = self._remaining_ms / self._duration_ms
        self._progress.setValue(int(ratio * 1000))

    # -- Styling --

    def _apply_level(self, level):
        self.setProperty("level", level.value)
        self.style().unpolish(self)
        self.style().polish(self)

        self._progress.setProperty("level", level.value)
        self._progress.style().unpolish(self._progress)
        self._progress.style().polish(self._progress)

        if level == NotificationLevel.Warning:
            self._icon_label.setText("\u26a0")
        else:
            self._icon_label.setText("\u2139")

    def _update_label(self):
        text = self._current_message
        if self._current_count > 1:
            text += f"  (x{self._current_count})"
        self._message_label.setText(text)

    # -- Positioning --

    def _max_width(self):
        if self.parent():
            return int(self.parent().width() * 0.7)
        return 420

    def _reposition(self):
        if self.parent() is None:
            return
        x = (self.parent().width() - self.width()) // 2
        self.move(x, self.y())

    def _shown_pos(self):
        """Target position when fully visible (top-center, 8px margin)."""
        if self.parent() is None:
            return QPoint(0, 8)
        x = (self.parent().width() - self.width()) // 2
        return QPoint(x, 8)

    def _hidden_pos(self):
        """Position above the visible area."""
        if self.parent() is None:
            return QPoint(0, -self.height())
        x = (self.parent().width() - self.width()) // 2
        return QPoint(x, -self.height())

    # -- Animation --

    def _slide_in(self):
        # Stop any running animation
        self._anim.stop()

        # Show first so the layout resolves the final size
        self.show()
        self.raise_()
        self.adjustSize()

        self.move(self._hidden_pos())
        self._anim.setStartValue(self._hidden_pos())
        self._anim.setEndValue(self._shown_pos())
        self._anim.start()

    def _slide_out(self):
        self._anim.stop()

        self._anim.setStartValue(self.pos())
        self._anim.setEndValue(self._hidden_pos())
        self._anim.finished.connect(self._on_slide_out_finished)
        self._anim.start()

    def _on_slide_out_finished(self):
        self._anim.finished.disconnect(self._on_slide_out_finished)
        self.hide()
        self._current_message = ""
        self._current_count = 0

    # -- Event filter --

    def eventFilter(self, obj, event):
        if obj is self.parent() and event.type() == QEvent.Resize:
            if self.isVisible():
                self._reposition()
        return False
