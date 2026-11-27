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

"""The list layout's info panel shows a cue description as written.

Descriptions are rendered as Markdown, where a single newline is a soft
break: "Teacher: X\\nBegins: Y" came out as one run-on line. Every
newline the operator typed must start a new line on screen.
"""

import pytest
from PyQt5.QtGui import QFont, QTextDocument

from lisp.plugins.list_layout.info_panel import InfoPanel

pytestmark = pytest.mark.skipif(
    not hasattr(QTextDocument, "setMarkdown"),
    reason="Markdown rendering needs Qt >= 5.14",
)

# A real Shore Dance 2026 description (Senior Q1).
DESCRIPTION = (
    "Teacher: Hannah\n"
    "Begins: Off stage\n"
    "Finishes: On Stage\n"
    "Lighting: Warm lighting, purple/pink\n"
    "Projector: Backdrop\n"
    "Music and backdrop start together on one GO."
)


def shown_lines(panel):
    # A Markdown hard break is a U+2028 line separator inside a block;
    # a paragraph is a new block (\n in toPlainText). Both are new lines.
    text = panel.cueDescription.toPlainText().replace(" ", "\n")
    return [line for line in text.split("\n") if line]


@pytest.fixture
def panel(qtbot):
    p = InfoPanel()
    qtbot.addWidget(p)
    return p


def blocks(panel):
    doc = panel.cueDescription.document()
    b, out = doc.begin(), []
    while b.isValid():
        out.append(b)
        b = b.next()
    return out


def test_each_description_line_is_shown_on_its_own_line(panel):
    panel._desc_changed(DESCRIPTION)

    assert shown_lines(panel) == DESCRIPTION.split("\n")


def test_lines_stay_in_one_paragraph_not_double_spaced(panel):
    # A Markdown hard break would make each line its own paragraph with
    # top and bottom margins: the fields would look double spaced.
    panel._desc_changed(DESCRIPTION)

    assert panel.cueDescription.document().blockCount() == 1


def test_heading_does_not_swallow_the_next_line(panel):
    panel._desc_changed("# Notes\nTeacher: Hannah\nBegins: Off stage")

    bs = blocks(panel)
    assert [b.text() for b in bs] == [
        "Notes", "Teacher: Hannah Begins: Off stage"]
    assert bs[0].blockFormat().headingLevel() == 1
    assert bs[1].blockFormat().headingLevel() == 0


def test_list_items_stay_a_list(panel):
    panel._desc_changed("Props:\n- fan\n- hat")

    bs = blocks(panel)
    assert [b.text() for b in bs] == ["Props:", "fan", "hat"]
    assert [b.textList() is not None for b in bs] == [False, True, True]


def test_fenced_code_keeps_its_lines(panel):
    panel._desc_changed("```\na\nb\n```")

    assert shown_lines(panel) == ["a", "b"]


def test_blank_line_still_separates_paragraphs(panel):
    panel._desc_changed("First line\nSecond line\n\nNew paragraph")

    assert shown_lines(panel) == ["First line", "Second line", "New paragraph"]
    assert panel.cueDescription.document().blockCount() == 2


def test_markdown_formatting_still_renders(panel):
    panel._desc_changed("**Lighting:** blue\n*Projector:* none")

    assert shown_lines(panel) == ["Lighting: blue", "Projector: none"]
    cursor = panel.cueDescription.textCursor()
    cursor.setPosition(2)
    assert cursor.charFormat().fontWeight() == QFont.Bold
