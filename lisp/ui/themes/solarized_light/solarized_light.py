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


_SOLARIZED_CUE_PALETTE_LIGHT = MappingProxyType({
    "Red":    "#dc322f",
    "Orange": "#cb4b16",
    "Yellow": "#b58900",
    "Green":  "#859900",
    "Blue":   "#268bd2",
    "Purple": "#6c71c4",  # violet
    "Grey":   "#93a1a1",  # base1
})


class SolarizedLight(BaseTheme):
    Colors = ThemeColors(
        background=QColor("#fdf6e3"),         # base3
        foreground=QColor("#eee8d5"),         # base2 — chrome
        text=QColor("#073642"),               # base02 — high-contrast teal
        highlight=QColor("#2aa198"),          # cyan
        alternate_base=QColor("#eee8d5"),     # base2 — list striping
        highlighted_text=QColor("#fdf6e3"),   # base3 — text on cyan
        bright_text=QColor("#dc322f"),        # red
        standby_indicator=QColor(211, 54, 130, 180),  # magenta α 180
        cue_palette=_SOLARIZED_CUE_PALETTE_LIGHT,
        cue_alpha=130,
    )
    QssPath = os.path.join(
        os.path.dirname(__file__), "..", "light", "theme.qss"
    )
