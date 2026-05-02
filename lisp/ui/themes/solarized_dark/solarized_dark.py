# This file is part of Linux Show Player
#
# Copyright 2026
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

import os
from types import MappingProxyType

from PyQt5.QtGui import QColor

from lisp.ui.themes.base import BaseTheme, ThemeColors


# Cue accents are identical across Solarized Light and Dark — Solarized
# is calibrated so the eight accents read at equal perceived lightness
# against either base. Only the chrome (bg/fg/text) and Grey differ.
_SOLARIZED_CUE_PALETTE_DARK = MappingProxyType({
    "Red":    "#dc322f",
    "Orange": "#cb4b16",
    "Yellow": "#b58900",
    "Green":  "#859900",
    "Blue":   "#268bd2",
    "Purple": "#6c71c4",  # violet — closest to LiSP's Purple slot
    "Grey":   "#586e75",  # base01
})


class SolarizedDark(BaseTheme):
    Colors = ThemeColors(
        background=QColor("#002b36"),         # base03
        foreground=QColor("#073642"),         # base02 — chrome
        text=QColor("#eee8d5"),               # base2 — high-contrast cream
        highlight=QColor("#2aa198"),          # cyan
        alternate_base=QColor("#073642"),     # base02 — list striping
        highlighted_text=QColor("#fdf6e3"),   # base3 — text on cyan
        bright_text=QColor("#dc322f"),        # red
        standby_indicator=QColor(211, 54, 130, 180),  # magenta α 180
        cue_palette=_SOLARIZED_CUE_PALETTE_DARK,
        cue_alpha=80,
    )
    # Phase 1 ships palette-only fidelity by reusing the dark QSS.
    # A targeted retuning pass for off-palette hex values is planned
    # as a separate follow-up.
    QssPath = os.path.join(
        os.path.dirname(__file__), "..", "dark", "theme.qss"
    )
