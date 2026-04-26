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

"""Tests for theme-aware grayscale fill inversion in icon SVGs.

The bytes-level helper is unit-tested standalone. Integration with the
QIcon load path is verified via the existing icon-theme machinery using
the active theme's text color to decide direction."""

from lisp.ui.icons import _invert_grayscale_fills


class TestGrayscaleInversion:
    def test_six_digit_grayscale_inverts(self):
        result = _invert_grayscale_fills(b"<svg fill='#969696'/>")
        assert b"#696969" in result
        assert b"#969696" not in result

    def test_three_digit_grayscale_inverts(self):
        result = _invert_grayscale_fills(b"<svg fill='#fff'/>")
        # 0xFF -> 0x00; emit lowercase 6-digit form for predictability
        assert b"#000000" in result
        assert b"#fff" not in result

    def test_chromatic_six_digit_preserved(self):
        # #dc322f is solarized red — branded, must not invert
        result = _invert_grayscale_fills(b"<svg fill='#dc322f'/>")
        assert b"#dc322f" in result
        # No replacement happened
        assert b"#23cdd0" not in result  # complement of dc322f

    def test_chromatic_three_digit_preserved(self):
        # #f0a is chromatic — leave alone
        result = _invert_grayscale_fills(b"<svg fill='#f0a'/>")
        assert b"#f0a" in result

    def test_uppercase_grayscale_inverts(self):
        result = _invert_grayscale_fills(b"<svg fill='#BEBEBE'/>")
        # 0xBE -> 0x41
        assert b"#414141" in result

    def test_mixed_case_grayscale_inverts(self):
        result = _invert_grayscale_fills(b"<svg fill='#FfFfFf'/>")
        # 0xFF -> 0x00
        assert b"#000000" in result

    def test_inside_style_attribute(self):
        # Real LiSP icons embed colors in style="..." — must work there too
        original = b'<path style="fill:#969696;opacity:1"/>'
        result = _invert_grayscale_fills(original)
        assert b"fill:#696969" in result
        assert b"opacity:1" in result

    def test_multiple_grays_in_one_svg(self):
        original = b'<svg><path fill="#969696"/><path fill="#bebebe"/></svg>'
        result = _invert_grayscale_fills(original)
        assert b"#696969" in result
        assert b"#414141" in result

    def test_pure_black_inverts_to_white(self):
        result = _invert_grayscale_fills(b'<svg fill="#000000"/>')
        assert b"#ffffff" in result

    def test_no_grayscale_no_change(self):
        original = b'<svg fill="#dc322f"/><circle stroke="#859900"/>'
        result = _invert_grayscale_fills(original)
        assert result == original


class TestActiveThemeIsLight:
    """The IconTheme uses themes._active.Colors.text luminance to decide
    whether to apply the tint. Test that decision logic in isolation."""

    def setup_method(self):
        from lisp.ui import themes
        themes._active = None

    def test_no_active_theme_is_not_light(self):
        from lisp.ui.icons import _active_theme_is_light
        assert _active_theme_is_light() is False

    def test_dark_theme_is_not_light(self, qapp):
        from lisp.ui.themes.dark.dark import Dark
        from lisp.ui.icons import _active_theme_is_light
        Dark().apply(qapp)
        assert _active_theme_is_light() is False

    def test_light_theme_is_light(self, qapp):
        from lisp.ui.themes.light.light import Light
        from lisp.ui.icons import _active_theme_is_light
        Light().apply(qapp)
        assert _active_theme_is_light() is True

    def test_system_theme_is_not_light(self, qapp):
        # System has no Colors → fallback returns False (no tint applied)
        from lisp.ui.themes.system.system import System
        from lisp.ui.icons import _active_theme_is_light
        System().apply(qapp)
        assert _active_theme_is_light() is False
