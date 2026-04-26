import pytest
from PyQt5.QtGui import QColor

from lisp.ui.themes.base import (
    CUE_COLOR_NAMES,
    DEFAULT_CUE_PALETTE,
    ThemeColors,
)


class TestThemeColorsValidation:
    def _base_kwargs(self):
        return dict(
            background=QColor(30, 30, 30),
            foreground=QColor(52, 52, 52),
            text=QColor(230, 230, 230),
            highlight=QColor(65, 155, 230),
        )

    def test_constructs_with_required_fields_only(self):
        c = ThemeColors(**self._base_kwargs())
        assert c.background == QColor(30, 30, 30)
        assert c.cue_palette == DEFAULT_CUE_PALETTE

    def test_canonical_names_are_seven(self):
        assert len(CUE_COLOR_NAMES) == 7
        assert set(CUE_COLOR_NAMES) == {
            "Red", "Orange", "Yellow",
            "Green", "Blue", "Purple", "Grey",
        }

    def test_default_palette_covers_all_names(self):
        assert set(DEFAULT_CUE_PALETTE.keys()) == set(CUE_COLOR_NAMES)

    def test_palette_missing_name_raises(self):
        bad = dict(DEFAULT_CUE_PALETTE)
        del bad["Yellow"]
        with pytest.raises(ValueError, match="cue_palette"):
            ThemeColors(**self._base_kwargs(), cue_palette=bad)

    def test_palette_extra_name_raises(self):
        bad = dict(DEFAULT_CUE_PALETTE)
        bad["Magenta"] = "#ff00ff"
        with pytest.raises(ValueError, match="cue_palette"):
            ThemeColors(**self._base_kwargs(), cue_palette=bad)

    def test_palette_malformed_hex_raises(self):
        bad = dict(DEFAULT_CUE_PALETTE)
        bad["Red"] = "red"  # CSS name, not a hex
        with pytest.raises(ValueError, match="hex"):
            ThemeColors(**self._base_kwargs(), cue_palette=bad)

    def test_palette_short_hex_raises(self):
        bad = dict(DEFAULT_CUE_PALETTE)
        bad["Red"] = "#abc"
        with pytest.raises(ValueError, match="hex"):
            ThemeColors(**self._base_kwargs(), cue_palette=bad)
