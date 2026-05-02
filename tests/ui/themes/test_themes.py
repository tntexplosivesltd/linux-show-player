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

import pytest
from PyQt5.QtGui import QColor, QPalette
from unittest.mock import MagicMock

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


class TestThemeColorsDerivations:
    """Optional fields derive sensible defaults from base colors."""

    def _theme(self, **overrides):
        kwargs = dict(
            background=QColor(30, 30, 30),
            foreground=QColor(52, 52, 52),
            text=QColor(230, 230, 230),
            highlight=QColor(65, 155, 230),
        )
        kwargs.update(overrides)
        return ThemeColors(**kwargs)

    def test_alternate_base_derives_from_foreground_darker(self):
        c = self._theme()
        assert c.resolved_alternate_base() == QColor(52, 52, 52).darker(125)

    def test_alternate_base_override_wins(self):
        c = self._theme(alternate_base=QColor(99, 99, 99))
        assert c.resolved_alternate_base() == QColor(99, 99, 99)

    def test_light_role_derives_lighter_160(self):
        c = self._theme()
        assert c.resolved_light() == QColor(52, 52, 52).lighter(160)

    def test_midlight_role_derives_lighter_125(self):
        c = self._theme()
        assert c.resolved_midlight() == QColor(52, 52, 52).lighter(125)

    def test_dark_role_derives_darker_150(self):
        c = self._theme()
        assert c.resolved_dark() == QColor(52, 52, 52).darker(150)

    def test_mid_role_derives_darker_125(self):
        c = self._theme()
        assert c.resolved_mid() == QColor(52, 52, 52).darker(125)

    def test_bright_text_default_is_pure_red(self):
        c = self._theme()
        assert c.resolved_bright_text() == QColor(255, 0, 0)

    def test_highlighted_text_default_is_black(self):
        c = self._theme()
        assert c.resolved_highlighted_text() == QColor(0, 0, 0)


class TestBaseThemeApply:
    """BaseTheme.apply maps ThemeColors to a QPalette on the QApplication."""

    def _make_dark_theme(self):
        from lisp.ui.themes.base import BaseTheme

        class _TestDark(BaseTheme):
            Colors = ThemeColors(
                background=QColor(30, 30, 30),
                foreground=QColor(52, 52, 52),
                text=QColor(230, 230, 230),
                highlight=QColor(65, 155, 230),
            )

        return _TestDark()

    def test_window_role_uses_foreground(self, qapp):
        theme = self._make_dark_theme()
        theme.apply(qapp)
        assert qapp.palette().color(QPalette.Window) == QColor(52, 52, 52)

    def test_base_role_uses_background(self, qapp):
        theme = self._make_dark_theme()
        theme.apply(qapp)
        assert qapp.palette().color(QPalette.Base) == QColor(30, 30, 30)

    def test_text_role_uses_text(self, qapp):
        theme = self._make_dark_theme()
        theme.apply(qapp)
        assert qapp.palette().color(QPalette.Text) == QColor(230, 230, 230)

    def test_highlight_role_uses_highlight(self, qapp):
        theme = self._make_dark_theme()
        theme.apply(qapp)
        assert qapp.palette().color(QPalette.Highlight) == QColor(65, 155, 230)

    def test_alternate_base_uses_derived_default(self, qapp):
        theme = self._make_dark_theme()
        theme.apply(qapp)
        assert qapp.palette().color(QPalette.AlternateBase) == \
            QColor(52, 52, 52).darker(125)

    def test_no_qss_when_qsspath_unset(self, qapp):
        theme = self._make_dark_theme()
        qapp.setStyleSheet("/* sentinel */")
        theme.apply(qapp)
        # QssPath is None, so apply should not touch the stylesheet
        assert qapp.styleSheet() == "/* sentinel */"

    def test_apply_sets_active_theme(self, qapp):
        from lisp.ui import themes
        theme = self._make_dark_theme()
        theme.apply(qapp)
        assert themes._active is theme


class TestCueColorHelpers:
    """Active-theme-aware lookups for cue colors."""

    def setup_method(self):
        from lisp.ui import themes
        themes._active = None  # reset between tests

    def test_cue_color_hex_returns_empty_for_empty(self):
        from lisp.ui.themes import cue_color_hex
        assert cue_color_hex("") == ""

    def test_cue_color_hex_no_active_theme_uses_default(self):
        from lisp.ui.themes import cue_color_hex
        assert cue_color_hex("Red") == DEFAULT_CUE_PALETTE["Red"]

    def test_cue_color_hex_uses_active_theme(self, qapp):
        from lisp.ui.themes import cue_color_hex
        from lisp.ui.themes.base import BaseTheme

        custom_palette = dict(DEFAULT_CUE_PALETTE)
        custom_palette["Red"] = "#dc322f"  # solarized red

        class _Solarized(BaseTheme):
            Colors = ThemeColors(
                background=QColor(253, 246, 227),
                foreground=QColor(238, 232, 213),
                text=QColor(101, 123, 131),
                highlight=QColor(38, 139, 210),
                cue_palette=custom_palette,
            )

        _Solarized().apply(qapp)
        assert cue_color_hex("Red") == "#dc322f"

    def test_cue_palette_returns_default_when_no_active(self):
        from lisp.ui.themes import cue_palette
        assert cue_palette() == DEFAULT_CUE_PALETTE

    def test_cue_background_hex_themed_takes_precedence(self):
        from lisp.ui.themes import cue_background_hex
        cue = MagicMock()
        cue.color_name = "Red"
        cue.stylesheet = "background: #aabbcc"
        assert cue_background_hex(cue) == DEFAULT_CUE_PALETTE["Red"]

    def test_cue_background_hex_falls_back_to_legacy_hex(self):
        from lisp.ui.themes import cue_background_hex
        cue = MagicMock()
        cue.color_name = ""
        cue.stylesheet = "background: #aabbcc"
        assert cue_background_hex(cue) == "#aabbcc"

    def test_cue_background_hex_returns_empty_when_no_color(self):
        from lisp.ui.themes import cue_background_hex
        cue = MagicMock()
        cue.color_name = ""
        cue.stylesheet = ""
        assert cue_background_hex(cue) == ""

    def test_cue_color_hex_unknown_name_returns_empty(self):
        """Hand-edited sessions or schema drift can produce unknown
        names. We must degrade gracefully, not raise — paint code
        depends on this."""
        from lisp.ui.themes import cue_color_hex
        assert cue_color_hex("Magenta") == ""
        assert cue_color_hex("NotAColor") == ""


class TestLightTheme:
    EXPECTED = {
        QPalette.Window: QColor(230, 230, 230),
        QPalette.Base: QColor(245, 245, 245),
        QPalette.Text: QColor(30, 30, 30),
        QPalette.Highlight: QColor(65, 155, 230),
        QPalette.HighlightedText: QColor(255, 255, 255),
        QPalette.AlternateBase: QColor(220, 220, 220),
        QPalette.BrightText: QColor(200, 0, 0),
    }

    def test_applies_without_error(self, qapp):
        from lisp.ui.themes.light.light import Light
        Light().apply(qapp)  # no exception

    def test_palette_matches_spec(self, qapp):
        from lisp.ui.themes.light.light import Light
        Light().apply(qapp)
        for role, expected in self.EXPECTED.items():
            assert qapp.palette().color(role) == expected

    def test_applies_minimal_qss(self, qapp):
        """Light theme ships a minimal QSS (just selection rules).
        Verify the QSS is loaded — the QssPath file must exist and
        the application stylesheet must be non-empty after apply()."""
        from lisp.ui.themes.light.light import Light

        qapp.setStyleSheet("")
        Light().apply(qapp)
        assert qapp.styleSheet() != ""
        # The minimal QSS must include item-selected styling
        assert "item:selected" in qapp.styleSheet()

    def test_qss_is_minimal_not_full_restyle(self, qapp):
        """Sanity: Light's QSS is the small "force selection" file,
        not a full widget restyle like Dark's. Catch accidental dark
        QSS theft into Light."""
        from lisp.ui.themes.light.light import Light

        qapp.setStyleSheet("")
        Light().apply(qapp)
        # Heuristic: dark/theme.qss is ~16KB; Light's should be tiny.
        assert len(qapp.styleSheet()) < 6144, (
            f"Light QSS unexpectedly large ({len(qapp.styleSheet())} bytes)"
        )

    def test_sets_active(self, qapp):
        from lisp.ui import themes
        from lisp.ui.themes.light.light import Light
        light = Light()
        light.apply(qapp)
        assert themes._active is light

    def test_uses_default_cue_palette(self, qapp):
        from lisp.ui.themes import cue_color_hex
        from lisp.ui.themes.light.light import Light
        Light().apply(qapp)
        assert cue_color_hex("Red") == DEFAULT_CUE_PALETTE["Red"]


class TestDarkPaletteUnchanged:
    """Lock the Dark theme palette against accidental drift.

    Asserts the Active palette group only — Inactive/Disabled groups
    inherit Qt's automatic propagation, matching the original Dark
    implementation's coverage."""

    EXPECTED = {
        QPalette.Window: QColor(52, 52, 52),
        QPalette.WindowText: QColor(230, 230, 230),
        QPalette.Base: QColor(30, 30, 30),
        QPalette.AlternateBase: QColor(52, 52, 52).darker(125),
        QPalette.ToolTipBase: QColor(52, 52, 52),
        QPalette.ToolTipText: QColor(230, 230, 230),
        QPalette.Text: QColor(230, 230, 230),
        QPalette.Button: QColor(52, 52, 52),
        QPalette.ButtonText: QColor(230, 230, 230),
        QPalette.BrightText: QColor(255, 0, 0),
        QPalette.Link: QColor(65, 155, 230),
        QPalette.Light: QColor(52, 52, 52).lighter(160),
        QPalette.Midlight: QColor(52, 52, 52).lighter(125),
        QPalette.Dark: QColor(52, 52, 52).darker(150),
        QPalette.Mid: QColor(52, 52, 52).darker(125),
        QPalette.Highlight: QColor(65, 155, 230),
        QPalette.HighlightedText: QColor(0, 0, 0),
    }

    def test_palette_roles_match_dark_baseline(self, qapp):
        from lisp.ui.themes.dark.dark import Dark
        Dark().apply(qapp)
        for role, expected in self.EXPECTED.items():
            assert qapp.palette().color(role) == expected, (
                f"role {role} = {qapp.palette().color(role).getRgb()}, "
                f"expected {expected.getRgb()}"
            )


class TestSystemTheme:
    def test_applies_without_changing_palette(self, qapp):
        from lisp.ui.themes.system.system import System
        before = QColor(qapp.palette().color(QPalette.Window))
        System().apply(qapp)
        after = qapp.palette().color(QPalette.Window)
        assert before == after

    def test_applies_without_changing_stylesheet(self, qapp):
        from lisp.ui.themes.system.system import System
        qapp.setStyleSheet("/* sentinel */")
        System().apply(qapp)
        assert qapp.styleSheet() == "/* sentinel */"

    def test_sets_active(self, qapp):
        from lisp.ui import themes
        from lisp.ui.themes.system.system import System
        s = System()
        s.apply(qapp)
        assert themes._active is s

    def test_cue_color_hex_falls_back_to_default(self, qapp):
        from lisp.ui.themes import cue_color_hex
        from lisp.ui.themes.system.system import System
        System().apply(qapp)
        assert cue_color_hex("Red") == DEFAULT_CUE_PALETTE["Red"]

    def test_discovery_finds_system(self):
        from lisp.ui import themes
        themes._THEMES.clear()  # reset cache so new theme is discovered
        from lisp.ui.themes import themes_names
        assert "System" in themes_names()


class TestCueAlpha:
    """The cue color alpha is theme-controlled. Dark and Light each
    pick subtle alphas that read as a category tint over their
    respective base background, rather than a saturated block."""

    def setup_method(self):
        from lisp.ui import themes
        themes._active = None  # reset between tests

    def test_themecolors_api_default_is_150(self):
        """The API-level default on ``ThemeColors`` stays at 150 for
        third-party themes that don't pick an alpha. LiSP's own
        themes (Dark/Light/Solarized) override to subtler values."""
        c = ThemeColors(
            background=QColor(30, 30, 30),
            foreground=QColor(52, 52, 52),
            text=QColor(230, 230, 230),
            highlight=QColor(65, 155, 230),
        )
        assert c.cue_alpha == 150

    def test_explicit_override_wins(self):
        c = ThemeColors(
            background=QColor(30, 30, 30),
            foreground=QColor(52, 52, 52),
            text=QColor(230, 230, 230),
            highlight=QColor(65, 155, 230),
            cue_alpha=200,
        )
        assert c.cue_alpha == 200

    def test_validation_rejects_non_int(self):
        with pytest.raises(ValueError, match="cue_alpha"):
            ThemeColors(
                background=QColor(30, 30, 30),
                foreground=QColor(52, 52, 52),
                text=QColor(230, 230, 230),
                highlight=QColor(65, 155, 230),
                cue_alpha="200",
            )

    def test_validation_rejects_out_of_range(self):
        with pytest.raises(ValueError, match="cue_alpha"):
            ThemeColors(
                background=QColor(30, 30, 30),
                foreground=QColor(52, 52, 52),
                text=QColor(230, 230, 230),
                highlight=QColor(65, 155, 230),
                cue_alpha=300,
            )

    def test_helper_no_active_theme_returns_150(self):
        from lisp.ui.themes import cue_color_alpha
        assert cue_color_alpha() == 150

    def test_light_theme_alpha(self, qapp):
        from lisp.ui.themes import cue_color_alpha
        from lisp.ui.themes.light.light import Light
        Light().apply(qapp)
        assert cue_color_alpha() == 130

    def test_dark_theme_alpha(self, qapp):
        from lisp.ui.themes import cue_color_alpha
        from lisp.ui.themes.dark.dark import Dark
        Dark().apply(qapp)
        assert cue_color_alpha() == 80


class TestStandbyIndicator:
    """The list-layout standby cue band colour is theme-controlled.

    Dark and Light inherit ``DEFAULT_STANDBY_INDICATOR`` (warm yellow
    α 180); Solarized themes override to a palette-faithful magenta.
    Themes that don't set the field fall through to the default —
    never raising or returning ``None``.
    """

    def setup_method(self):
        from lisp.ui import themes
        themes._active = None  # reset between tests

    def test_default_is_none_on_themecolors(self):
        c = ThemeColors(
            background=QColor(30, 30, 30),
            foreground=QColor(52, 52, 52),
            text=QColor(230, 230, 230),
            highlight=QColor(65, 155, 230),
        )
        assert c.standby_indicator is None

    def test_explicit_override_stored(self):
        c = ThemeColors(
            background=QColor(30, 30, 30),
            foreground=QColor(52, 52, 52),
            text=QColor(230, 230, 230),
            highlight=QColor(65, 155, 230),
            standby_indicator=QColor(211, 54, 130, 100),
        )
        assert c.standby_indicator == QColor(211, 54, 130, 100)

    def test_default_value(self):
        """``DEFAULT_STANDBY_INDICATOR`` is warm yellow at α 180 —
        bright enough to read clearly above coloured cue washes
        on both Dark and Light themes (which both fall through to
        this default)."""
        from lisp.ui.themes import DEFAULT_STANDBY_INDICATOR
        assert DEFAULT_STANDBY_INDICATOR == QColor(250, 220, 0, 180)

    def test_helper_no_active_theme_returns_default(self):
        from lisp.ui.themes import (
            DEFAULT_STANDBY_INDICATOR,
            standby_indicator,
        )
        assert standby_indicator() == DEFAULT_STANDBY_INDICATOR

    def test_helper_active_theme_without_field_returns_default(self, qapp):
        from lisp.ui.themes import (
            DEFAULT_STANDBY_INDICATOR,
            standby_indicator,
        )
        from lisp.ui.themes.dark.dark import Dark
        Dark().apply(qapp)
        assert standby_indicator() == DEFAULT_STANDBY_INDICATOR

    def test_helper_uses_active_theme_value(self, qapp):
        from lisp.ui.themes import standby_indicator
        from lisp.ui.themes.base import BaseTheme

        class _CustomTheme(BaseTheme):
            Colors = ThemeColors(
                background=QColor(0, 43, 54),
                foreground=QColor(7, 54, 66),
                text=QColor(131, 148, 150),
                highlight=QColor(42, 161, 152),
                standby_indicator=QColor(211, 54, 130, 100),
            )

        _CustomTheme().apply(qapp)
        assert standby_indicator() == QColor(211, 54, 130, 100)

    def test_light_theme_inherits_default(self, qapp):
        """Light deliberately does not override standby_indicator; it
        falls through to the warm-yellow α 180 default."""
        from lisp.ui.themes import (
            DEFAULT_STANDBY_INDICATOR,
            standby_indicator,
        )
        from lisp.ui.themes.light.light import Light
        Light().apply(qapp)
        assert standby_indicator() == DEFAULT_STANDBY_INDICATOR


class _SolarizedExpectations:
    """Shared expected hex values for both Solarized themes.

    Cue accents are identical across Solarized Light and Dark — the
    only differences are chrome (bg/fg/text/alternate_base) and the
    Grey cue colour (base01 vs base1).
    """

    CUE_ACCENTS = {
        "Red":    "#dc322f",
        "Orange": "#cb4b16",
        "Yellow": "#b58900",
        "Green":  "#859900",
        "Blue":   "#268bd2",
        "Purple": "#6c71c4",
    }
    HIGHLIGHT_CYAN = QColor("#2aa198")
    STANDBY_MAGENTA = QColor(211, 54, 130, 180)


class TestSolarizedDarkTheme(_SolarizedExpectations):
    """Solarized Dark — base03/base02 chrome, Solarized accent cues,
    cyan selection, magenta standby indicator. Reuses dark/theme.qss."""

    def setup_method(self):
        from lisp.ui import themes
        themes._active = None

    def test_applies_without_error(self, qapp):
        from lisp.ui.themes.solarized_dark.solarized_dark import (
            SolarizedDark,
        )
        SolarizedDark().apply(qapp)

    def test_palette_uses_solarized_base_tones(self, qapp):
        from lisp.ui.themes.solarized_dark.solarized_dark import (
            SolarizedDark,
        )
        SolarizedDark().apply(qapp)
        p = qapp.palette()
        assert p.color(QPalette.Base) == QColor("#002b36")        # base03
        assert p.color(QPalette.Window) == QColor("#073642")      # base02
        # Text uses base2 (cream) for high-contrast readability over
        # saturated cue-colour washes; Solarized's official base0 text
        # tier is calibrated for plain backgrounds and reads poorly on
        # the cue-list rows.
        assert p.color(QPalette.Text) == QColor("#eee8d5")        # base2
        assert p.color(QPalette.AlternateBase) == QColor("#073642")
        assert p.color(QPalette.Highlight) == self.HIGHLIGHT_CYAN
        # HighlightedText and BrightText are explicit overrides on
        # ``ThemeColors``; if they were accidentally dropped the
        # Qt fallbacks (black / pure red) would silently take effect.
        assert p.color(QPalette.HighlightedText) == QColor("#fdf6e3")
        assert p.color(QPalette.BrightText) == QColor("#dc322f")

    def test_cue_palette_uses_solarized_accents(self, qapp):
        from lisp.ui.themes import cue_color_hex
        from lisp.ui.themes.solarized_dark.solarized_dark import (
            SolarizedDark,
        )
        SolarizedDark().apply(qapp)
        for name, expected in self.CUE_ACCENTS.items():
            assert cue_color_hex(name) == expected, (
                f"{name} expected {expected}, got {cue_color_hex(name)}"
            )
        assert cue_color_hex("Grey") == "#586e75"  # base01

    def test_cue_alpha_is_subtle(self, qapp):
        """Solarized intentionally uses a lower cue_alpha than the
        legacy Dark theme (150) so cue colours read as a gentle tint
        rather than a saturated block over Solarized's muted base03."""
        from lisp.ui.themes import cue_color_alpha
        from lisp.ui.themes.solarized_dark.solarized_dark import (
            SolarizedDark,
        )
        SolarizedDark().apply(qapp)
        assert cue_color_alpha() == 80

    def test_standby_indicator_is_magenta(self, qapp):
        from lisp.ui.themes import standby_indicator
        from lisp.ui.themes.solarized_dark.solarized_dark import (
            SolarizedDark,
        )
        SolarizedDark().apply(qapp)
        assert standby_indicator() == self.STANDBY_MAGENTA

    def test_reuses_dark_theme_qss(self, qapp):
        """Phase 1 ships palette-only fidelity. The Solarized Dark
        theme reuses the existing dark/theme.qss."""
        from lisp.ui.themes.solarized_dark.solarized_dark import (
            SolarizedDark,
        )
        qapp.setStyleSheet("")
        SolarizedDark().apply(qapp)
        # Dark's QSS is the heavy ~16KB chrome stylesheet
        assert len(qapp.styleSheet()) > 8192, (
            f"SolarizedDark QSS unexpectedly small "
            f"({len(qapp.styleSheet())} bytes); expected dark/theme.qss"
        )

    def test_discoverable(self):
        from lisp.ui import themes
        themes._THEMES.clear()
        from lisp.ui.themes import themes_names
        assert "SolarizedDark" in themes_names()


class TestSolarizedLightTheme(_SolarizedExpectations):
    """Solarized Light — base3/base2 chrome, Solarized accent cues,
    cyan selection, magenta standby indicator. Reuses light/theme.qss."""

    def setup_method(self):
        from lisp.ui import themes
        themes._active = None

    def test_applies_without_error(self, qapp):
        from lisp.ui.themes.solarized_light.solarized_light import (
            SolarizedLight,
        )
        SolarizedLight().apply(qapp)

    def test_palette_uses_solarized_base_tones(self, qapp):
        from lisp.ui.themes.solarized_light.solarized_light import (
            SolarizedLight,
        )
        SolarizedLight().apply(qapp)
        p = qapp.palette()
        assert p.color(QPalette.Base) == QColor("#fdf6e3")        # base3
        assert p.color(QPalette.Window) == QColor("#eee8d5")      # base2
        # Text uses base02 (deep teal) for high-contrast readability
        # over saturated cue-colour washes — same rationale as the
        # Dark theme's base2 text choice (see TestSolarizedDarkTheme).
        assert p.color(QPalette.Text) == QColor("#073642")        # base02
        assert p.color(QPalette.AlternateBase) == QColor("#eee8d5")
        assert p.color(QPalette.Highlight) == self.HIGHLIGHT_CYAN
        assert p.color(QPalette.HighlightedText) == QColor("#fdf6e3")
        assert p.color(QPalette.BrightText) == QColor("#dc322f")

    def test_cue_palette_uses_solarized_accents(self, qapp):
        from lisp.ui.themes import cue_color_hex
        from lisp.ui.themes.solarized_light.solarized_light import (
            SolarizedLight,
        )
        SolarizedLight().apply(qapp)
        for name, expected in self.CUE_ACCENTS.items():
            assert cue_color_hex(name) == expected
        assert cue_color_hex("Grey") == "#93a1a1"  # base1

    def test_cue_alpha_is_subtle(self, qapp):
        """Solarized intentionally uses a lower cue_alpha than the
        legacy Light theme (220) so cue colours read as a gentle tint
        over Solarized's warm base3 cream rather than dominating the
        row."""
        from lisp.ui.themes import cue_color_alpha
        from lisp.ui.themes.solarized_light.solarized_light import (
            SolarizedLight,
        )
        SolarizedLight().apply(qapp)
        assert cue_color_alpha() == 130

    def test_standby_indicator_is_magenta(self, qapp):
        from lisp.ui.themes import standby_indicator
        from lisp.ui.themes.solarized_light.solarized_light import (
            SolarizedLight,
        )
        SolarizedLight().apply(qapp)
        assert standby_indicator() == self.STANDBY_MAGENTA

    def test_reuses_light_theme_qss(self, qapp):
        """Phase 1 ships palette-only fidelity. The Solarized Light
        theme reuses the existing light/theme.qss (small, just the
        item:selected force-styling)."""
        from lisp.ui.themes.solarized_light.solarized_light import (
            SolarizedLight,
        )
        qapp.setStyleSheet("")
        SolarizedLight().apply(qapp)
        # Light's QSS is small but non-empty
        assert qapp.styleSheet() != ""
        assert "item:selected" in qapp.styleSheet()

    def test_discoverable(self):
        from lisp.ui import themes
        themes._THEMES.clear()
        from lisp.ui.themes import themes_names
        assert "SolarizedLight" in themes_names()


class TestThemeDiscoveryAggregate:
    """Lock the full theme roster in one test so a merge accident
    that drops one of the existing themes can't slip past the
    per-theme discovery checks (each of which only asserts its own
    presence)."""

    def test_all_known_themes_discoverable(self):
        from lisp.ui import themes
        themes._THEMES.clear()
        from lisp.ui.themes import themes_names
        assert set(themes_names()) >= {
            "Dark", "Light", "System",
            "SolarizedDark", "SolarizedLight",
        }
