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

"""Tests for cart-widget theme-aware stylesheet resolution.

Cart cues paint via Qt stylesheet. For themed cues (``color_name``
set), the resolved hex must be injected into the cue's stylesheet
``background`` key before the string is passed to ``setStyleSheet``.
Legacy custom-hex cues pass through unchanged."""

from lisp.cues.cue import Cue
from lisp.plugins.cart_layout.cue_widget import _resolve_cart_stylesheet
from lisp.ui.themes.base import DEFAULT_CUE_PALETTE
from lisp.ui.ui_utils import css_to_dict


class TestCartCueWidgetThemedColor:
    def test_themed_cue_injects_hex(self, mock_app):
        cue = Cue(mock_app)
        cue.color_name = "Red"
        cue.stylesheet = "color: #fff; font-size: 14px"
        result = _resolve_cart_stylesheet(cue)
        css = css_to_dict(result)
        assert css.get("background") == DEFAULT_CUE_PALETTE["Red"]
        # Other CSS properties preserved
        assert css.get("color") == "#fff"
        assert css.get("font-size") == "14px"

    def test_legacy_cue_uses_existing_stylesheet(self, mock_app):
        cue = Cue(mock_app)
        cue.color_name = ""
        cue.stylesheet = "background: #aabbcc"
        # Legacy hex is already in the stylesheet — pass through
        assert _resolve_cart_stylesheet(cue) == "background: #aabbcc"

    def test_no_color_no_background_key(self, mock_app):
        cue = Cue(mock_app)
        cue.color_name = ""
        cue.stylesheet = "color: #fff"
        # No themed name, no legacy bg — original stylesheet preserved
        assert _resolve_cart_stylesheet(cue) == "color: #fff"

    def test_themed_overrides_legacy_bg(self, mock_app):
        """If both color_name and stylesheet bg are set, themed wins
        (matches cue_background_hex precedence)."""
        cue = Cue(mock_app)
        cue.color_name = "Blue"
        cue.stylesheet = "background: #aabbcc"
        result = _resolve_cart_stylesheet(cue)
        css = css_to_dict(result)
        assert css.get("background") == DEFAULT_CUE_PALETTE["Blue"]

    def test_unknown_color_name_injects_empty(self, mock_app):
        """If color_name is set but not a canonical entry (e.g.,
        hand-edited session, schema drift), cue_color_hex returns ""
        and we inject an empty background. Defensive — the cue
        renders without a background colour rather than crashing."""
        cue = Cue(mock_app)
        cue.color_name = "Magenta"  # not in CUE_COLOR_NAMES
        cue.stylesheet = "color: #fff"
        result = _resolve_cart_stylesheet(cue)
        css = css_to_dict(result)
        # Empty string injected (cue_color_hex returns "" for unknowns)
        assert css.get("background") == ""
        # Other CSS preserved
        assert css.get("color") == "#fff"


class TestCueWidgetConstruction:
    """Constructing a ``CueWidget`` for a cue must not raise.

    Regression: a previous refactor that renamed ``_refreshStyle`` to
    ``_updateStyle`` missed the ``cue.changed("icon").connect(...)``
    line, leaving a dangling attribute reference. The resulting
    ``AttributeError`` was raised inside ``_setCue`` during widget
    construction, bubbled up to ``CartLayout.__cue_added``, and was
    silently swallowed by the outer signal-call exception handler —
    so the cart cell was never actually added to the layout.
    """

    def test_widget_constructs_without_crash(self, qapp, mock_app):
        from lisp.plugins.cart_layout.cue_widget import CueWidget
        from lisp.ui.icons import IconTheme

        if IconTheme._GlobalTheme is None:
            IconTheme.set_theme_name("lisp")

        cue = Cue(mock_app)
        # If any signal slot in _setCue is mis-named, this raises
        # AttributeError before the widget is fully constructed.
        widget = CueWidget(cue)
        assert widget is not None

    def test_icon_change_does_not_warn(self, qapp, mock_app, caplog):
        """The ``cue.changed("icon")`` subscription must invoke a real
        method. Emitting the signal triggers the slot synchronously
        in this test (no Qt event loop), and any AttributeError gets
        caught by ``Slot.call`` and logged as a warning. Asserting
        the warning is absent locks in the wiring."""
        import logging
        from lisp.plugins.cart_layout.cue_widget import CueWidget
        from lisp.ui.icons import IconTheme

        if IconTheme._GlobalTheme is None:
            IconTheme.set_theme_name("lisp")

        cue = Cue(mock_app)
        widget = CueWidget(cue)  # noqa: F841 — kept alive for slot

        with caplog.at_level(logging.WARNING, logger="lisp.core.signal"):
            cue.icon = "media-playback-start"

        attr_warnings = [
            r for r in caplog.records
            if "_refreshStyle" in r.getMessage()
            or "no attribute" in r.getMessage()
        ]
        assert not attr_warnings, (
            f"icon change produced AttributeError warnings: "
            f"{[r.getMessage() for r in attr_warnings]}"
        )
