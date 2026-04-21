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

"""QLab-style fixed-palette colour picker for cue backgrounds.

Sessions store colours as hex strings inside ``cue.stylesheet``. This
module owns the palette of acceptable hex values and the migration
function that snaps arbitrary legacy hex to the nearest palette entry.

Palette hues are deliberately deeper than a saturated set would be:
the list layout composites cue backgrounds at ``alpha=150`` over the
dark theme's ``#1E1E1E`` base, which lightens every colour. Picking
deeper raws compensates so the rendered row is both legible and
distinguishable from its neighbours.

The "no colour" slot is represented by an empty string, not a palette
entry, so that ``cue.stylesheet`` retains its existing semantics
(``""`` means "no background set") and sessions without a background
round-trip unchanged.
"""

import re
from typing import Optional

from PyQt5.QtCore import pyqtSignal, QSize, Qt
from PyQt5.QtGui import QColor, QPainter, QPen
from PyQt5.QtWidgets import (
    QAbstractButton,
    QHBoxLayout,
    QWidget,
)

from lisp.ui.ui_utils import translate


# Ordered for the inspector row. Consumers assume list ordering.
PALETTE = (
    ("Red",    "#C03A2A"),
    ("Orange", "#D6761E"),
    ("Yellow", "#C09A20"),
    ("Green",  "#3E8A3B"),
    ("Blue",   "#3535B8"),
    ("Purple", "#7848A6"),
    ("Grey",   "#6E6E6E"),
)


_HEX_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")


def _parse_rgb(hex_color: str) -> Optional[tuple]:
    """Return (r, g, b) ints for a ``#RRGGBB`` string, or None if invalid."""
    if not isinstance(hex_color, str) or not _HEX_RE.match(hex_color):
        return None
    return (
        int(hex_color[1:3], 16),
        int(hex_color[3:5], 16),
        int(hex_color[5:7], 16),
    )


def snap_to_palette(color) -> str:
    """Return the palette hex closest to ``color`` by RGB-Euclidean distance.

    ``""``, ``None``, or any string that doesn't parse as ``#RRGGBB``
    returns ``""`` — the "no colour" slot. An exact palette hit is
    preserved; anything else snaps to the nearest entry.

    Case is normalised to uppercase so downstream equality comparisons
    against ``PALETTE`` are direct. Simple Euclidean distance is
    sufficient for a 7-entry palette — CIE-Lab would be more perceptually
    faithful but adds a dependency for a negligible quality gain here.
    """
    rgb = _parse_rgb(color) if isinstance(color, str) else None
    if rgb is None:
        return ""

    best_hex = PALETTE[0][1]
    best_dist2 = None
    for _, entry_hex in PALETTE:
        er, eg, eb = _parse_rgb(entry_hex)
        dr, dg, db = rgb[0] - er, rgb[1] - eg, rgb[2] - eb
        dist2 = dr * dr + dg * dg + db * db
        if best_dist2 is None or dist2 < best_dist2:
            best_dist2 = dist2
            best_hex = entry_hex

    return best_hex


_SWATCH_DIAMETER = 20
_SELECTION_RING_COLOR = "#E6E6E6"   # matches QPalette.WindowText in dark theme
_UNSELECTED_RING_COLOR = "#3C3C3C"  # ~QPalette.Mid; subtle idle outline
_NONE_SLASH_COLOR = "#888888"
_NONE_FILL_COLOR = "transparent"


class _Swatch(QAbstractButton):
    """A single circular palette entry.

    The parent `CueColorPalette` manages selection exclusively, so the
    swatch itself isn't checkable — it just reports clicks and renders
    whatever `setSelected(bool)` dictates. Rendering is hand-painted
    rather than stylesheet-driven so the "None" slot's diagonal slash
    can be drawn cleanly alongside the circular fill.
    """

    def __init__(self, color_hex: str, label: str, parent=None):
        super().__init__(parent)
        self._color_hex = color_hex   # "" = None slot
        self._selected = False
        self.setFixedSize(QSize(_SWATCH_DIAMETER + 4, _SWATCH_DIAMETER + 4))
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(label)

    def colorHex(self) -> str:
        return self._color_hex

    def isSelected(self) -> bool:
        return self._selected

    def setSelected(self, selected: bool) -> None:
        if self._selected == selected:
            return
        self._selected = selected
        self.update()

    def sizeHint(self) -> QSize:
        return QSize(_SWATCH_DIAMETER + 4, _SWATCH_DIAMETER + 4)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)

        cx = self.width() / 2
        cy = self.height() / 2
        r = _SWATCH_DIAMETER / 2

        # Fill.
        if self._color_hex:
            painter.setBrush(QColor(self._color_hex))
            painter.setPen(Qt.NoPen)
            painter.drawEllipse(
                int(cx - r), int(cy - r),
                _SWATCH_DIAMETER, _SWATCH_DIAMETER,
            )
        # None: transparent circle with diagonal slash.
        else:
            painter.setBrush(QColor(_NONE_FILL_COLOR))
            painter.setPen(QPen(QColor(_NONE_SLASH_COLOR), 1, Qt.DashLine))
            painter.drawEllipse(
                int(cx - r), int(cy - r),
                _SWATCH_DIAMETER, _SWATCH_DIAMETER,
            )
            painter.setPen(QPen(QColor(_NONE_SLASH_COLOR), 2))
            offset = r * 0.6
            painter.drawLine(
                int(cx - offset), int(cy + offset),
                int(cx + offset), int(cy - offset),
            )

        # Selection ring.
        ring_color = (
            _SELECTION_RING_COLOR if self._selected else _UNSELECTED_RING_COLOR
        )
        ring_width = 2 if self._selected else 1
        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(QColor(ring_color), ring_width))
        ring_r = r + 1
        painter.drawEllipse(
            int(cx - ring_r), int(cy - ring_r),
            int(ring_r * 2), int(ring_r * 2),
        )


class CueColorPalette(QWidget):
    """QLab-style fixed-palette background-colour picker for the inspector.

    Exposes a single-row strip of 8 swatches — "None" plus the 7
    chromatic entries in :data:`PALETTE`. Holds the currently selected
    hex (``""`` for "no colour") and emits :attr:`colorPicked` only on
    user clicks. Programmatic calls to :meth:`setColor` are silent so
    the InspectorCommitEngine doesn't mistake a settings reload for
    a user edit.

    :meth:`setMixed` is the multi-selection escape hatch — when the
    inspector shows several cues with divergent colours, flipping
    mixed mode hides the selection ring entirely so no single swatch
    lies about "the" colour. User interaction or a definite
    :meth:`setColor` resolves divergence and clears the flag.
    """

    colorPicked = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)

        self._color: str = ""
        self._mixed: bool = False

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self._swatches: list = []

        # "None" first — acts as the reset affordance, removing any
        # previously set background colour from the cue.
        none_swatch = _Swatch(
            "", translate("CueColorPalette", "No color"), self
        )
        none_swatch.clicked.connect(self._on_swatch_clicked)
        layout.addWidget(none_swatch)
        self._swatches.append(none_swatch)

        for name, hex_val in PALETTE:
            swatch = _Swatch(
                hex_val, translate("CueColorPalette", name), self
            )
            swatch.clicked.connect(self._on_swatch_clicked)
            layout.addWidget(swatch)
            self._swatches.append(swatch)

        layout.addStretch(1)

        self._refresh_selection()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def color(self) -> str:
        """Currently selected hex, or ``""`` for the "No color" slot."""
        return self._color

    def setColor(self, hex_color) -> None:
        """Set the selected colour, snapping non-palette hex to the nearest.

        Silent: does not emit :attr:`colorPicked`. Clears mixed state —
        a definite value has been provided.
        """
        snapped = snap_to_palette(hex_color) if hex_color else ""
        self._color = snapped
        self._mixed = False
        self._refresh_selection()

    def isMixed(self) -> bool:
        return self._mixed

    def setMixed(self, mixed: bool) -> None:
        """Toggle divergent-values display mode. Silent."""
        self._mixed = bool(mixed)
        self._refresh_selection()

    def swatches(self) -> list:
        """Ordered swatch buttons: None slot first, then PALETTE order."""
        return list(self._swatches)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _on_swatch_clicked(self) -> None:
        swatch = self.sender()
        if not isinstance(swatch, _Swatch):
            return
        new_color = swatch.colorHex()
        self._color = new_color
        self._mixed = False
        self._refresh_selection()
        self.colorPicked.emit(new_color)

    def _refresh_selection(self) -> None:
        """Apply the current colour state to every swatch.

        In mixed mode no swatch is shown as selected — a blank row
        signals divergence without lying about any single value.
        """
        for swatch in self._swatches:
            selected = (
                not self._mixed and swatch.colorHex() == self._color
            )
            swatch.setSelected(selected)
