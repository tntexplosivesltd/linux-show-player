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

"""Reusable inspector helper for surfacing invalid-target state.

Each cue settings page that has a target picker embeds a
`TargetWarningRow` directly under the picker. The page calls
`update_state(picker_widget, kind)` whenever the picked value
changes (init / select / loadSettings). The widget hides itself
when the target is valid; otherwise it shows an amber warning icon
and an explanatory line, and applies a red outline to the picker.
"""

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QHBoxLayout, QLabel, QWidget

from lisp.ui.icons import IconTheme
from lisp.ui.ui_utils import translate

# QSS targeting QPushButton (the typical picker control). The selector
# applies to the widget instance the row is invoked against.
_OUTLINE_QSS = "QPushButton { border: 1px solid #c0392b; }"


class TargetWarningRow(QWidget):
    """A small horizontal row [icon] [text], hidden when valid.

    Settings pages embed this just below their target picker, and
    call `update_state(target_widget, kind)` whenever the picker's
    state changes. `kind` is one of:
      - "ok"        : valid; row is hidden, picker outline cleared
      - "empty"     : target_id is empty
      - "dangling"  : target_id set but cue not in model
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 2, 0, 0)
        layout.setSpacing(6)

        self._icon = QLabel(self)
        self._icon.setPixmap(
            IconTheme.get("dialog-warning").pixmap(16, 16)
        )
        self._text = QLabel(self)
        self._text.setAlignment(Qt.AlignVCenter)

        layout.addWidget(self._icon)
        layout.addWidget(self._text, stretch=1)
        self.setVisible(False)

    def update_state(self, picker_widget, kind):
        if kind == "ok":
            self.setVisible(False)
            if picker_widget is not None:
                picker_widget.setStyleSheet("")
            return
        if kind == "empty":
            self._text.setText(
                translate("TargetingCue", "Target cue is not set")
            )
        else:  # "dangling"
            self._text.setText(
                translate("TargetingCue", "Target cue no longer exists")
            )
        self.setVisible(True)
        if picker_widget is not None:
            picker_widget.setStyleSheet(_OUTLINE_QSS)
