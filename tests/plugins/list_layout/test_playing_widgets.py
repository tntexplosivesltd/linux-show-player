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

"""Tests for the running-cue widget's colour stripe.

The list layout's running-cues panel shows a narrow coloured stripe on
the left edge of each widget, reflecting the cue's palette background.
It's the playback-panel analogue to the list view's row tint — same
source (``cue.stylesheet``), same palette, smaller footprint.
"""

import pytest

from lisp.cues.cue import Cue
from lisp.plugins.list_layout.playing_widgets import RunningCueWidget
from lisp.ui.icons import IconTheme


@pytest.fixture(autouse=True)
def _icon_theme():
    """The control buttons pull icons at construction time. Without a
    theme, ``IconTheme.get`` explodes on the NoneType ``_GlobalTheme``.
    """
    IconTheme.set_theme_name("lisp")
    yield


class _Config(dict):
    """Minimal config double — RunningCueWidget only ``get()``s values."""


def _make_cue(mock_app, stylesheet=""):
    cue = Cue(app=mock_app)
    cue.stylesheet = stylesheet
    return cue


class TestRunningCueWidgetColorStripe:
    """The stripe is the playback-panel surface for cue colour.

    These tests cover its initial state, reactivity to stylesheet
    edits, and the empty-colour/legacy-stylesheet fallbacks.
    """

    def test_stripe_exists_on_widget(self, qtbot, mock_app):
        """Every running cue widget must expose a ``colorStripe``."""
        cue = _make_cue(mock_app)
        widget = RunningCueWidget(cue, _Config())
        qtbot.addWidget(widget)

        assert hasattr(widget, "colorStripe")
        assert widget.colorStripe is not None

    def test_stripe_initial_color_from_stylesheet(self, qtbot, mock_app):
        """Red palette background → stripe reports ``#C03A2A``."""
        cue = _make_cue(mock_app, stylesheet="background:#C03A2A;")
        widget = RunningCueWidget(cue, _Config())
        qtbot.addWidget(widget)

        assert widget.colorStripe.color() == "#C03A2A"

    def test_stripe_empty_when_no_background(self, qtbot, mock_app):
        """No ``background`` key → stripe reports empty, hidden."""
        cue = _make_cue(mock_app, stylesheet="font-size:14pt;")
        widget = RunningCueWidget(cue, _Config())
        qtbot.addWidget(widget)

        assert widget.colorStripe.color() == ""
        assert not widget.colorStripe.isVisibleTo(widget)

    def test_stripe_empty_for_missing_stylesheet(self, qtbot, mock_app):
        """Empty stylesheet → stripe reports empty, hidden."""
        cue = _make_cue(mock_app, stylesheet="")
        widget = RunningCueWidget(cue, _Config())
        qtbot.addWidget(widget)

        assert widget.colorStripe.color() == ""
        assert not widget.colorStripe.isVisibleTo(widget)

    def test_stripe_visible_when_background_set(self, qtbot, mock_app):
        """A background hex should make the stripe visible."""
        cue = _make_cue(mock_app, stylesheet="background:#3E8A3B;")
        widget = RunningCueWidget(cue, _Config())
        qtbot.addWidget(widget)

        assert widget.colorStripe.isVisibleTo(widget)

    def test_stripe_updates_on_stylesheet_change(self, qtbot, mock_app):
        """Mutating ``cue.stylesheet`` must propagate to the stripe.

        The list view already reacts to ``stylesheet`` property
        changes for its row tint; the stripe must do the same so the
        two surfaces never disagree after an inspector edit.
        """
        cue = _make_cue(mock_app, stylesheet="background:#C03A2A;")
        widget = RunningCueWidget(cue, _Config())
        qtbot.addWidget(widget)

        cue.stylesheet = "background:#3535B8;"
        qtbot.wait(10)

        assert widget.colorStripe.color() == "#3535B8"
        assert widget.colorStripe.isVisibleTo(widget)

    def test_stripe_hides_when_background_cleared(
        self, qtbot, mock_app
    ):
        """Clearing the background via a new stylesheet hides it."""
        cue = _make_cue(mock_app, stylesheet="background:#C03A2A;")
        widget = RunningCueWidget(cue, _Config())
        qtbot.addWidget(widget)

        cue.stylesheet = ""
        qtbot.wait(10)

        assert widget.colorStripe.color() == ""
        assert not widget.colorStripe.isVisibleTo(widget)

    def test_stripe_actually_paints_color(self, qtbot, mock_app):
        """The stripe must actually paint the colour — not just store it.

        Regression guard: a plain ``QWidget`` ignores ``background-color``
        stylesheets unless ``WA_StyledBackground`` is set. Without the
        attribute the stripe stays empty even when ``color()`` reports
        the right hex — so we assert both pieces are in place.
        """
        from PyQt5.QtCore import Qt

        cue = _make_cue(mock_app, stylesheet="background:#3E8A3B;")
        widget = RunningCueWidget(cue, _Config())
        qtbot.addWidget(widget)

        stripe = widget.colorStripe
        assert stripe.testAttribute(Qt.WA_StyledBackground)
        assert "#3E8A3B" in stripe.styleSheet().lower().replace(" ", "") \
            or "#3e8a3b" in stripe.styleSheet().lower().replace(" ", "")

    def test_stripe_ignores_font_size_only_updates(
        self, qtbot, mock_app
    ):
        """A stylesheet change that only affects font-size must not
        accidentally drop the stripe colour — the background key is
        still present, so the stripe must still reflect it."""
        cue = _make_cue(mock_app, stylesheet="background:#7848A6;")
        widget = RunningCueWidget(cue, _Config())
        qtbot.addWidget(widget)

        cue.stylesheet = "background:#7848A6;font-size:18pt;"
        qtbot.wait(10)

        assert widget.colorStripe.color() == "#7848A6"

    def test_stripe_stylesheet_is_scoped_to_class(
        self, qtbot, mock_app
    ):
        """The stripe's stylesheet must be scoped to ``_ColorStripe``.

        An unscoped ``background-color`` rule cascades to every
        descendant widget; the stripe has none today but a future
        child (tooltip, overlay label) would inherit the fill.
        Scoping the selector keeps the paint confined to the stripe
        itself regardless of what gets nested inside later.
        """
        cue = _make_cue(mock_app, stylesheet="background:#3E8A3B;")
        widget = RunningCueWidget(cue, _Config())
        qtbot.addWidget(widget)

        stripe_css = widget.colorStripe.styleSheet()
        assert "_ColorStripe" in stripe_css, (
            f"stripe stylesheet must be scoped, got: {stripe_css!r}"
        )

    def test_stripe_rejects_malformed_hex(self, qtbot, mock_app):
        """Invalid hex from a corrupted session must not paint.

        ``css_to_dict`` parses whatever's between ``background:`` and
        ``;`` without validating it's a real colour. A terminator-free
        payload lets arbitrary stylesheet syntax ride into
        ``self._color`` — the stripe must refuse to interpolate it
        into its own selector rather than echo it back verbatim.
        """
        # Single-colon payload with brace injection — survives
        # css_to_dict's 2-part split and lands in ``self._color``
        # verbatim. The stripe's stylesheet assignment must refuse
        # to echo it into its own selector.
        cue = _make_cue(
            mock_app,
            stylesheet="background:red } QWidget { color #fff",
        )
        widget = RunningCueWidget(cue, _Config())
        qtbot.addWidget(widget)

        stripe_css = widget.colorStripe.styleSheet()
        assert "QWidget" not in stripe_css, (
            f"foreign selector leaked through: {stripe_css!r}"
        )
