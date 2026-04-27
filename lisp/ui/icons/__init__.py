# This file is part of Linux Show Player
#
# Copyright 2018 Francesco Ceruti <ceppofrancy@gmail.com>
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

import glob
import os
import re
from typing import Union
from xml.etree import ElementTree as ET

from PyQt5.QtGui import QIcon, QPixmap, QPainter
from PyQt5.QtSvg import QSvgRenderer
from PyQt5.QtCore import Qt, QByteArray

from lisp import ICON_THEMES_DIR, ICON_THEME_COMMON

# Match any 6-digit hex; the substitution function verifies grayscale
# equality (case-insensitively) and inverts only matching values.
_HEX_6_RE = re.compile(rb"#([0-9A-Fa-f]{2})([0-9A-Fa-f]{2})([0-9A-Fa-f]{2})\b")
_HEX_3_RE = re.compile(rb"#([0-9A-Fa-f])([0-9A-Fa-f])([0-9A-Fa-f])\b")

# Named grayscale CSS color values appearing as SVG attribute or CSS
# property values for fill / stroke / stop-color. Constrained to those
# properties to avoid touching text content elsewhere (titles, descs,
# ids). Captures the prefix so we can reattach it on the swap.
_NAMED_GRAYSCALE_RE = re.compile(
    rb"(?P<prefix>(?:fill|stroke|stop-color)\s*[:=]\s*['\"]?\s*)"
    rb"(?P<color>white|black)\b"
)


def _invert_grayscale_fills(svg_bytes: bytes) -> bytes:
    """Invert grayscale color values (hex and CSS named) in an SVG byte
    string; preserve chromatic colors unchanged.

    Used to adapt dark-tuned SVG assets for light themes. The inversion
    is symmetric:
    - Hex: ``#969696`` <-> ``#696969``, ``#000000`` <-> ``#ffffff``
    - Named: ``white`` <-> ``black`` (when used as fill/stroke/stop-color)

    Named-color swaps are constrained to known SVG color attributes /
    CSS color properties (fill, stroke, stop-color) to avoid mangling
    text content (titles, ids, descriptions).
    """

    def _invert_byte(value: int) -> bytes:
        inv = 255 - value
        return f"{inv:02x}{inv:02x}{inv:02x}".encode("ascii")

    def _repl_6(match):
        a, b, c = match.group(1), match.group(2), match.group(3)
        if a.lower() != b.lower() or a.lower() != c.lower():
            return match.group(0)  # not grayscale; preserve verbatim
        v = int(a, 16)
        return b"#" + _invert_byte(v)

    def _repl_3(match):
        # Expand short form (#fff = #ffffff) before inverting so the
        # output is consistently 6-digit.
        a, b, c = match.group(1), match.group(2), match.group(3)
        if a.lower() != b.lower() or a.lower() != c.lower():
            return match.group(0)  # not grayscale; preserve verbatim
        nibble = int(a, 16)
        v = nibble * 17  # 0xF -> 0xFF
        return b"#" + _invert_byte(v)

    def _repl_named(match):
        prefix = match.group("prefix")
        color = match.group("color")
        swapped = b"black" if color == b"white" else b"white"
        return prefix + swapped

    svg_bytes = _HEX_6_RE.sub(_repl_6, svg_bytes)
    svg_bytes = _HEX_3_RE.sub(_repl_3, svg_bytes)
    svg_bytes = _NAMED_GRAYSCALE_RE.sub(_repl_named, svg_bytes)
    return svg_bytes


def _active_theme_is_light() -> bool:
    """True if the currently-applied theme has dark text on a light
    background — the signal to invert dark-tuned grayscale icon fills.

    Returns False when no theme is active, when the active theme has no
    ``Colors`` (e.g., ``System``), or when text is light. Conservative
    default: don't tint."""
    from lisp.ui import themes

    active = themes._active
    if active is None or not hasattr(active, "Colors"):
        return False
    return active.Colors.text.lightness() < 128


def icon_themes_names():
    for entry in os.scandir(os.path.dirname(__file__)):
        if (
            entry.is_dir()
            and entry.name != ICON_THEME_COMMON
            and entry.name[0] != "_"
        ):
            yield entry.name


class IconTheme:
    _SEARCH_PATTERN = "{}/**/{}.*"
    _BLANK_ICON = QIcon()
    _CUE_TYPE_VARIATIONS = {
        "-cart": {"stroke": "black", "fill": "black", "opacity": "0.1"},
        "-running": {"stroke": "#0D0", "fill": "#0D0", "opacity": "1"},
        "-pause": {"stroke": "#F90", "fill": "#F90", "opacity": "1"},
        "-error": {"stroke": "#D11", "fill": "#D11", "opacity": "1"},
        "-hibernating": {
            "stroke": "#5AF", "fill": "#5AF", "opacity": "1",
        },
    }
    _GlobalCache = {}
    _GlobalTheme = None
    
    def __init__(self, *names):
        self._lookup_dirs = [os.path.join(ICON_THEMES_DIR, d) for d in names]

    def __iter__(self):
        yield from self._lookup_dirs

    @staticmethod
    def get(icon_name) -> Union[QIcon, None]:
        icon = IconTheme._GlobalCache.get(icon_name, None)

        if icon is None:
            icon = IconTheme._BLANK_ICON
            for dir_ in IconTheme._GlobalTheme:
                search_name = IconTheme._strip_cue_suffix(icon_name)
                if search_name != icon_name:
                    suffix = icon_name[len(search_name):]
                    pattern = IconTheme._SEARCH_PATTERN.format(dir_, search_name)
                    for icon in glob.iglob(pattern, recursive=True):
                        icon = IconTheme._load_modified_icon(icon, suffix)
                        break
                pattern = IconTheme._SEARCH_PATTERN.format(dir_, icon_name)
                for icon in glob.iglob(pattern, recursive=True):
                    icon = IconTheme._load_themed_icon(icon)
                    break

            IconTheme._GlobalCache[icon_name] = icon

        return icon

    @staticmethod
    def set_theme_name(theme_name):
        IconTheme._GlobalCache.clear()
        IconTheme._GlobalTheme = IconTheme(theme_name, ICON_THEME_COMMON)

        QIcon.setThemeSearchPaths([ICON_THEMES_DIR])
        QIcon.setThemeName(theme_name)

    @staticmethod
    def _strip_cue_suffix(icon_name: str) -> str:
        for suffix in IconTheme._CUE_TYPE_VARIATIONS:
            if icon_name.endswith(suffix):
                return icon_name[: -len(suffix)]
        return icon_name

    @staticmethod
    def _load_modified_icon(svg_path: str, suffix: str) -> QIcon:
        try:
            with open(svg_path, "rb") as f:
                xml_bytes = f.read()

            # Invert grayscale fills BEFORE applying the variation's root
            # attrs, so the variation's deliberate named colors (e.g.,
            # "black" for the -cart overlay) aren't accidentally swapped to
            # "white" on light theme. Per-path grayscales in the SVG (e.g.,
            # legacy #969696) still get inverted as intended.
            if _active_theme_is_light():
                xml_bytes = _invert_grayscale_fills(xml_bytes)

            root = ET.fromstring(xml_bytes)
            variations = IconTheme._CUE_TYPE_VARIATIONS[suffix]
            for attr, val in variations.items():
                root.set(attr, val)

            modified_svg = ET.tostring(root, encoding="utf-8", xml_declaration=True)

            renderer = QSvgRenderer(QByteArray(modified_svg))
            size = renderer.defaultSize()

            pixmap = QPixmap(size)
            pixmap.fill(Qt.transparent)

            painter = QPainter(pixmap)
            renderer.render(painter)
            painter.end()

            return QIcon(pixmap)
        except Exception:
            return IconTheme._BLANK_ICON

    @staticmethod
    def _load_themed_icon(svg_path: str) -> QIcon:
        """Load an icon from disk, applying theme-aware grayscale tinting
        if the active theme is light. Non-SVG files (PNG etc.) are loaded
        directly; only SVG paths are processed."""
        if not _active_theme_is_light() or not svg_path.endswith(".svg"):
            return QIcon(svg_path)

        try:
            with open(svg_path, "rb") as f:
                xml_bytes = f.read()
            xml_bytes = _invert_grayscale_fills(xml_bytes)

            renderer = QSvgRenderer(QByteArray(xml_bytes))
            size = renderer.defaultSize()
            if not size.isValid() or size.width() == 0:
                # Empty or malformed SVG; return raw QIcon as fallback
                return QIcon(svg_path)

            pixmap = QPixmap(size)
            pixmap.fill(Qt.transparent)
            painter = QPainter(pixmap)
            renderer.render(painter)
            painter.end()
            return QIcon(pixmap)
        except Exception:
            # IO error, parse failure, render failure — fall back to raw
            # load. Matches _load_modified_icon's robustness contract;
            # pre-tint behavior was a bare QIcon(svg_path) which never
            # raised, so we preserve that.
            return QIcon(svg_path)
