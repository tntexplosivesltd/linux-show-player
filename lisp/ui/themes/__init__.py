from os import path
from typing import Mapping

from PyQt5.QtGui import QColor

from lisp.core.loading import load_classes
from lisp.ui.themes.base import DEFAULT_CUE_PALETTE
from lisp.ui.ui_utils import css_to_dict

# Default standby cue band — warm yellow at α 100. Yellow's natural
# luminance carries the band even at low alpha, so Dark/Light don't
# need a higher value here; themes whose standby_indicator hue is
# darker (e.g. Solarized magenta) override to a brighter alpha to
# compensate. Byte-equal to the value previously hardcoded in
# ``CueListView.ITEM_CURRENT_BG`` before the helper refactor.
DEFAULT_STANDBY_INDICATOR = QColor(250, 220, 0, 100)

_THEMES = {}
_active = None


def load_themes():
    if not _THEMES:
        for name, theme in load_classes(__package__, path.dirname(__file__)):
            _THEMES[name] = theme()


def themes_names():
    load_themes()
    return list(_THEMES.keys())


def get_theme(theme_name):
    load_themes()
    return _THEMES[theme_name]


def cue_color_hex(name: str) -> str:
    """Resolve a canonical cue color name to the active theme's hex.

    Returns ``""`` for an empty name OR for any name not in
    ``CUE_COLOR_NAMES`` (defensive against hand-edited sessions,
    future palette extensions, or third-party theme drift). Paint
    code depends on this never raising.

    Falls back to ``DEFAULT_CUE_PALETTE`` when no theme is active or
    the active theme has no ``Colors``.
    """
    if not name:
        return ""
    if _active is not None and hasattr(_active, "Colors"):
        palette = _active.Colors.cue_palette
    else:
        palette = DEFAULT_CUE_PALETTE
    return palette.get(name, DEFAULT_CUE_PALETTE.get(name, ""))


def cue_color_alpha() -> int:
    """Return the active theme's cue color alpha (0-255).

    Falls back to 100 (LiSP's default subtle-tint alpha) when no
    theme is active or the active theme has no ``Colors``.
    """
    if _active is not None and hasattr(_active, "Colors"):
        return _active.Colors.cue_alpha
    return 100


def cue_palette() -> Mapping[str, str]:
    """Return the active theme's full ``{name: hex}`` palette mapping."""
    if _active is not None and hasattr(_active, "Colors"):
        return _active.Colors.cue_palette
    return DEFAULT_CUE_PALETTE


def standby_indicator() -> QColor:
    """Return the active theme's standby cue band colour.

    Falls back to ``DEFAULT_STANDBY_INDICATOR`` when no theme is
    active, the active theme has no ``Colors``, or the theme's
    ``standby_indicator`` field is ``None``.
    """
    if _active is not None and hasattr(_active, "Colors"):
        c = _active.Colors.standby_indicator
        if c is not None:
            return c
    return DEFAULT_STANDBY_INDICATOR


def cue_background_hex(cue) -> str:
    """Return the hex to paint for ``cue``, or ``""`` for none.

    Themed name takes precedence over legacy ``stylesheet["background"]``.
    """
    color_name = getattr(cue, "color_name", "")
    if color_name:
        return cue_color_hex(color_name)
    return css_to_dict(getattr(cue, "stylesheet", "") or "").get(
        "background", ""
    )
