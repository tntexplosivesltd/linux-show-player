# This file is part of Linux Show Player
#
# Copyright 2016 Francesco Ceruti <ceppofrancy@gmail.com>
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

import re

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QTextDocument
from PyQt5.QtWidgets import QWidget, QTextEdit, QLineEdit, QVBoxLayout

from lisp.ui.ui_utils import translate

# A line that starts a Markdown block of its own: heading, list item,
# quote, table row or code fence.
_MD_BLOCK_START = re.compile(r"[ \t]*(?:#|[-+*][ \t]|\d+[.)][ \t]|>|\||```|~~~)")
_MD_FENCE = re.compile(r"[ \t]*(?:```|~~~)")


def keep_line_breaks(text):
    """Make every line the operator typed show as its own line.

    In Markdown a single newline is a soft break, so "Teacher: X" and
    "Begins: Y" on separate lines ran together into one. Between two
    plain text lines the newline becomes U+2028, which Qt draws as a
    line break inside the paragraph (a Markdown hard break would become
    a new paragraph with its margins, i.e. double spacing). Blank lines,
    block starts (headings, lists, quotes, tables) and fenced code are
    left to the Markdown parser.
    """
    lines = text.replace("\r\n", "\n").split("\n")
    out = lines[:1]
    in_fence = bool(lines) and bool(_MD_FENCE.match(lines[0]))
    for prev, line in zip(lines, lines[1:]):
        plain = (
            not in_fence
            and prev.strip()
            and line.strip()
            and not prev.lstrip().startswith("#")
            and not _MD_BLOCK_START.match(line)
        )
        out.append((" " if plain else "\n") + line)
        if _MD_FENCE.match(line):
            in_fence = not in_fence
    return "".join(out)


class InfoPanel(QWidget):
    def __init__(self, *args):
        super().__init__(*args)
        self.setLayout(QVBoxLayout())
        self.layout().setContentsMargins(0, 0, 0, 0)

        self._cue = None

        # cue name
        self.cueName = QLineEdit(self)
        self.cueName.setFocusPolicy(Qt.NoFocus)
        self.cueName.setReadOnly(True)
        self.layout().addWidget(self.cueName)

        # cue description
        self.cueDescription = QTextEdit(self)
        self.cueDescription.setObjectName("InfoPanelDescription")
        self.cueDescription.setFocusPolicy(Qt.NoFocus)
        self.cueDescription.setReadOnly(True)
        self.layout().addWidget(self.cueDescription)

        self.retranslateUi()

    def retranslateUi(self):
        self.cueName.setPlaceholderText(
            translate("ListLayoutInfoPanel", "Cue name")
        )

    @property
    def cue(self):
        return self._cue

    @cue.setter
    def cue(self, item):
        if self._cue is not None:
            self._cue.changed("name").disconnect(self._name_changed)
            self._cue.changed("cue_number").disconnect(self._number_changed)
            self._cue.changed("description").disconnect(self._desc_changed)

        self._cue = item

        if self._cue is not None:
            self._cue.changed("name").connect(self._name_changed)
            self._cue.changed("cue_number").connect(self._number_changed)
            self._cue.changed("description").connect(self._desc_changed)

            self._refresh_name()
            self._desc_changed(self._cue.description)
        else:
            self.cueName.clear()
            self.cueDescription.clear()

    def _name_changed(self, name):
        self._refresh_name()

    def _number_changed(self, number):
        self._refresh_name()

    def _refresh_name(self):
        # Prefer the static cue_number when set; fall back to the
        # 1-based row position so old or unnumbered sessions still
        # display something sensible.
        prefix = self._cue.cue_number or str(self._cue.index + 1)
        self.cueName.setText(prefix + " → " + self._cue.name)

    def _desc_changed(self, description):
        if hasattr(QTextDocument, "setMarkdown"):
            self.cueDescription.document().setMarkdown(
                keep_line_breaks(description)
            )
        else:
            self.cueDescription.setText(description)

        self.cueDescription.setProperty("empty", len(description) == 0)
        self.cueDescription.style().polish(self.cueDescription)
