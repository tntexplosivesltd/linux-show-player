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

import re
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping, Optional

from PyQt5.QtGui import QColor


CUE_COLOR_NAMES = (
    "Red", "Orange", "Yellow",
    "Green", "Blue", "Purple", "Grey",
)

DEFAULT_CUE_PALETTE: Mapping[str, str] = MappingProxyType({
    "Red":    "#C03A2A",
    "Orange": "#D6761E",
    "Yellow": "#C09A20",
    "Green":  "#3E8A3B",
    "Blue":   "#3535B8",
    "Purple": "#7848A6",
    "Grey":   "#6E6E6E",
})


_HEX_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")


@dataclass(frozen=True)
class ThemeColors:
    background: QColor
    foreground: QColor
    text: QColor
    highlight: QColor
    bright_text: Optional[QColor] = None
    highlighted_text: Optional[QColor] = None
    alternate_base: Optional[QColor] = None
    light: Optional[QColor] = None
    midlight: Optional[QColor] = None
    dark: Optional[QColor] = None
    mid: Optional[QColor] = None
    cue_palette: Mapping[str, str] = field(
        default_factory=lambda: DEFAULT_CUE_PALETTE
    )

    def __post_init__(self):
        keys = set(self.cue_palette.keys())
        expected = set(CUE_COLOR_NAMES)
        if keys != expected:
            missing = expected - keys
            extra = keys - expected
            raise ValueError(
                f"cue_palette must have exactly these keys: "
                f"{sorted(expected)}. Missing: {sorted(missing)}. "
                f"Extra: {sorted(extra)}."
            )
        for name, value in self.cue_palette.items():
            if not isinstance(value, str) or not _HEX_RE.match(value):
                raise ValueError(
                    f"cue_palette[{name!r}] must be a #RRGGBB hex "
                    f"string, got {value!r}"
                )

    def resolved_alternate_base(self) -> QColor:
        return self.alternate_base or self.foreground.darker(125)

    def resolved_light(self) -> QColor:
        return self.light or self.foreground.lighter(160)

    def resolved_midlight(self) -> QColor:
        return self.midlight or self.foreground.lighter(125)

    def resolved_dark(self) -> QColor:
        return self.dark or self.foreground.darker(150)

    def resolved_mid(self) -> QColor:
        return self.mid or self.foreground.darker(125)

    def resolved_bright_text(self) -> QColor:
        return self.bright_text or QColor(255, 0, 0)

    def resolved_highlighted_text(self) -> QColor:
        return self.highlighted_text or QColor(0, 0, 0)
