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

Swatches are keyed by canonical name (one of :data:`CUE_COLOR_NAMES`
from :mod:`lisp.ui.themes.base`, or ``""`` for the "no colour" slot).
Hex values are resolved from the active theme at paint time so that
switching themes re-colours swatches without rebuilding the widget.

Legacy cues that carry a ``stylesheet["background"]`` hex rather than a
``color_name`` can be surfaced via :meth:`CueColorPalette.setCustomHex`;
the widget shows "no swatch selected" until the user picks a palette
entry, at which point the cue graduates to the themed name system.
"""

import re

from PyQt5.QtCore import pyqtSignal, Qt
from PyQt5.QtGui import QColor, QPainter, QPalette, QPen
from PyQt5.QtWidgets import (
    QAbstractButton,
    QApplication,
    QHBoxLayout,
    QWidget,
)

from lisp.ui import themes
from lisp.ui.themes.base import CUE_COLOR_NAMES
from lisp.ui.ui_utils import translate


_HEX_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")
_SWATCH_DIAMETER = 20
_NONE_SLASH_COLOR = "#888888"
_NONE_FILL_COLOR = "transparent"


class _Swatch(QAbstractButton):
    """A single circular palette entry, keyed by canonical name.

    The "no color" swatch uses ``name=""``. All other swatches use one
    of ``CUE_COLOR_NAMES``. The hex is resolved from the active theme
    at paint time so that switching themes re-colours swatches.

    The parent ``CueColorPalette`` manages selection exclusively;
    the swatch just reports clicks and renders whatever
    :meth:`setSelectedSwatch` dictates. Rendering is hand-painted
    rather than stylesheet-driven so the "None" slot's diagonal slash
    can be drawn cleanly alongside the circular fill.
    """

    clicked = pyqtSignal(str)  # emits the swatch's canonical name

    def __init__(self, name: str, label: str, parent=None):
        super().__init__(parent)
        self._name = name
        self._selected = False
        self.setFixedSize(_SWATCH_DIAMETER + 4, _SWATCH_DIAMETER + 4)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(label)
        # Wire QAbstractButton's internal clicked to our str-emitting one.
        super().clicked.connect(self._on_clicked)

    def name(self) -> str:
        """Canonical colour name, or ``""`` for the "no colour" slot."""
        return self._name

    def isSelectedSwatch(self) -> bool:
        return self._selected

    def setSelectedSwatch(self, value: bool) -> None:
        if self._selected != value:
            self._selected = value
            self.update()

    def _on_clicked(self):
        self.clicked.emit(self._name)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)

        cx = self.width() / 2
        cy = self.height() / 2
        r = _SWATCH_DIAMETER / 2

        if self._name == "":
            # "No color": transparent circle with a diagonal slash.
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
        else:
            hex_color = themes.cue_color_hex(self._name)
            painter.setBrush(QColor(hex_color))
            painter.setPen(Qt.NoPen)
            painter.drawEllipse(
                int(cx - r), int(cy - r),
                _SWATCH_DIAMETER, _SWATCH_DIAMETER,
            )

        # Selection ring derived from the active QPalette so it reads
        # on both light and dark themes.
        app_palette = QApplication.palette()
        if self._selected:
            ring = app_palette.color(QPalette.WindowText)
            painter.setPen(QPen(ring, 2))
        else:
            ring = app_palette.color(QPalette.Mid)
            painter.setPen(QPen(ring, 1))
        painter.setBrush(Qt.NoBrush)
        ring_r = r + 1
        painter.drawEllipse(
            int(cx - ring_r), int(cy - ring_r),
            int(ring_r * 2), int(ring_r * 2),
        )


class CueColorPalette(QWidget):
    """Theme-aware fixed-palette cue colour picker.

    Exposes a single-row strip of 8 swatches — "None" plus the 7
    chromatic entries in :data:`CUE_COLOR_NAMES`. Holds the currently
    selected canonical name (``""`` for "no colour") and emits
    :attr:`colorPicked` only on user clicks. Programmatic calls to
    :meth:`setColor` are silent so the InspectorCommitEngine doesn't
    mistake a settings reload for a user edit.

    :meth:`setMixed` is the multi-selection escape hatch — when the
    inspector shows several cues with divergent colours, flipping mixed
    mode hides the selection ring entirely so no single swatch lies
    about "the" colour. User interaction or a definite :meth:`setColor`
    resolves divergence and clears the flag.

    :meth:`setCustomHex` handles cues that carry a legacy
    ``stylesheet["background"]`` hex rather than a ``color_name``. No
    swatch is highlighted; the first user pick graduates the cue to the
    themed name system.
    """

    colorPicked = pyqtSignal(str)  # canonical name or ""

    def __init__(self, parent=None):
        super().__init__(parent)

        self._color: str = ""
        self._mixed: bool = False
        self._custom_hex: str = ""

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

        for name in CUE_COLOR_NAMES:
            swatch = _Swatch(
                name, translate("CueColorPalette", name), self
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
        """Currently selected canonical name, or ``""`` for no colour."""
        return self._color

    def customHex(self) -> str:
        """Legacy custom hex, if the cue's colour isn't a canonical name."""
        return self._custom_hex

    def isMixed(self) -> bool:
        return self._mixed

    def swatches(self) -> list:
        """Ordered swatch buttons: None slot first, then CUE_COLOR_NAMES."""
        return list(self._swatches)

    def setColor(self, name: str) -> None:
        """Programmatic set — silent (no signal emission).

        ``name`` must be a canonical name from ``CUE_COLOR_NAMES`` or
        ``""``. Unknown names are coerced to ``""``. Clears mixed state
        and any custom-hex annotation — a definite value has been
        provided.
        """
        if name and name not in CUE_COLOR_NAMES:
            name = ""
        self._color = name
        self._custom_hex = ""
        self._mixed = False
        self._refresh_selection()

    def setCustomHex(self, hex_color: str) -> None:
        """Show "no swatch selected" with a custom-hex annotation.

        For cues that have a legacy ``stylesheet["background"]`` hex
        but no ``color_name`` — they're not a canonical entry, so no
        swatch lights up. Picking any swatch graduates them to themed
        mode (signals ``colorPicked`` with the canonical name, and
        clears the custom hex).

        Invalid hex (non-``#RRGGBB`` strings) clears the annotation.
        """
        if isinstance(hex_color, str) and _HEX_RE.match(hex_color):
            self._custom_hex = hex_color.upper()
        else:
            self._custom_hex = ""
        self._color = ""
        self._mixed = False
        self._refresh_selection()

    def setMixed(self, mixed: bool) -> None:
        """Toggle divergent-values display mode. Silent."""
        self._mixed = bool(mixed)
        self._refresh_selection()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _on_swatch_clicked(self, name: str) -> None:
        self._color = name
        self._custom_hex = ""
        self._mixed = False
        self._refresh_selection()
        self.colorPicked.emit(name)

    def _refresh_selection(self) -> None:
        """Apply the current colour state to every swatch.

        In mixed mode, or when a custom hex is active, no swatch is
        shown as selected — a blank row signals divergence or a legacy
        value without lying about any single canonical entry.
        """
        for swatch in self._swatches:
            if self._mixed or self._custom_hex:
                swatch.setSelectedSwatch(False)
            else:
                swatch.setSelectedSwatch(swatch.name() == self._color)
