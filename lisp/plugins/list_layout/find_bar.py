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

from PyQt5.QtCore import QEvent, Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QToolButton,
    QWidget,
)

from lisp.ui.ui_utils import translate
from lisp.ui.widgets.cue_color_palette import CueColorPalette


class FindBar(QWidget):
    """Presentation-only find & jump bar for the list layout.

    Emits intent signals; holds no cue knowledge. The controller
    (:class:`ListLayout`) computes matches and drives navigation.
    """

    queryChanged = pyqtSignal(str)
    colorChanged = pyqtSignal(str)
    findNext = pyqtSignal()
    findPrev = pyqtSignal()
    closed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)

        self.queryEdit = QLineEdit(self)
        self.queryEdit.textChanged.connect(self.queryChanged)
        self.queryEdit.installEventFilter(self)
        layout.addWidget(self.queryEdit, 1)

        self.colorPalette = CueColorPalette(self)
        self.colorPalette.colorPicked.connect(self.colorChanged)
        layout.addWidget(self.colorPalette)

        self.prevButton = QToolButton(self)
        self.prevButton.setText("◀")  # ◀
        self.prevButton.setFocusPolicy(Qt.NoFocus)
        self.prevButton.clicked.connect(self.findPrev)
        layout.addWidget(self.prevButton)

        self.nextButton = QToolButton(self)
        self.nextButton.setText("▶")  # ▶
        self.nextButton.setFocusPolicy(Qt.NoFocus)
        self.nextButton.clicked.connect(self.findNext)
        layout.addWidget(self.nextButton)

        self.counterLabel = QLabel(self)
        self.counterLabel.setMinimumWidth(48)
        layout.addWidget(self.counterLabel)

        self.closeButton = QToolButton(self)
        self.closeButton.setText("✕")  # ✕
        self.closeButton.setFocusPolicy(Qt.NoFocus)
        self.closeButton.clicked.connect(self.closed)
        layout.addWidget(self.closeButton)

        self.retranslate()
        self.hide()

    def retranslate(self):
        self.queryEdit.setPlaceholderText(
            translate("ListLayout", "Find cue by name or number")
        )

    def query(self):
        return self.queryEdit.text()

    def color(self):
        return self.colorPalette.color()

    def focusQuery(self):
        self.queryEdit.setFocus()
        self.queryEdit.selectAll()

    def setMatchCounter(self, current, total):
        if total == 0:
            # Distinguish an active-but-fruitless search from an idle bar:
            # a search is active whenever there's query text OR a colour
            # filter. Active + zero matches shows "0/0" and tints the field
            # invalid (covering colour-only searches, where the text box is
            # empty); an idle bar stays blank and untinted.
            active = bool(self.query() or self.color())
            self.counterLabel.setText("0/0" if active else "")
            self._set_invalid(active)
        else:
            self.counterLabel.setText(f"{current}/{total}")
            self._set_invalid(False)

    def _set_invalid(self, invalid):
        if invalid:
            self.queryEdit.setStyleSheet(
                "QLineEdit { background: rgba(192, 58, 42, 0.35); }"
            )
        else:
            self.queryEdit.setStyleSheet("")

    def eventFilter(self, obj, event):
        if obj is self.queryEdit and event.type() == QEvent.KeyPress:
            key = event.key()
            if key == Qt.Key_Escape:
                self.closed.emit()
                return True
            if key in (Qt.Key_Return, Qt.Key_Enter):
                if event.modifiers() & Qt.ShiftModifier:
                    self.findPrev.emit()
                else:
                    self.findNext.emit()
                return True
        return super().eventFilter(obj, event)
