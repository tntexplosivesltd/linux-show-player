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

"""Tests for the cue volume indicator label."""

import pytest

from lisp.plugins.list_layout.playing_widgets import (
    _format_db_text,
    VolumeIndicatorLabel,
)


class TestFormatDbText:
    """`_format_db_text` maps a linear volume value to a display string.

    Formatting contract:
        - Unity  (1.0)      -> "+0.0 dB"
        - Below 1.0         -> "-N.N dB"   (negative sign)
        - Above 1.0         -> "+N.N dB"   (explicit plus sign)
        - At/below silence  -> "-∞ dB" (uses MIN_VOLUME_DB sentinel)
    """

    @pytest.mark.parametrize(
        "linear, expected",
        [
            (1.0, "+0.0 dB"),
            (0.5, "-6.0 dB"),
            (2.0, "+6.0 dB"),
            (10.0, "+20.0 dB"),
        ],
    )
    def test_ordinary_values(self, linear, expected):
        assert _format_db_text(linear) == expected

    def test_exact_zero_renders_minus_infinity(self):
        assert _format_db_text(0.0) == "-∞ dB"

    def test_below_min_volume_renders_minus_infinity(self):
        # MIN_VOLUME is ~6.3e-08; 1e-09 is well below.
        assert _format_db_text(1e-09) == "-∞ dB"

    def test_sign_prefix_anchors_digit_width(self):
        """Values just above and below unity share digit width thanks
        to the explicit +/- prefix, so the label does not shift
        horizontally by one character as volume crosses 0 dB.
        """
        assert len(_format_db_text(1.0)) == len(_format_db_text(0.999))


class TestVolumeIndicatorLabel:
    """The label is a dumb display — it takes a linear volume and
    renders the formatted string. No cue plumbing, no GStreamer."""

    def test_set_volume_linear_formats_unity(self, qtbot):
        label = VolumeIndicatorLabel()
        qtbot.addWidget(label)

        label.setVolumeLinear(1.0)

        assert label.text() == "+0.0 dB"

    def test_set_volume_linear_formats_attenuation(self, qtbot):
        label = VolumeIndicatorLabel()
        qtbot.addWidget(label)

        label.setVolumeLinear(0.5)

        assert label.text() == "-6.0 dB"

    def test_set_volume_linear_formats_silence(self, qtbot):
        label = VolumeIndicatorLabel()
        qtbot.addWidget(label)

        label.setVolumeLinear(0.0)

        assert label.text() == "-∞ dB"

    def test_starts_hidden(self, qtbot):
        label = VolumeIndicatorLabel()
        qtbot.addWidget(label)

        assert not label.isVisible()


from unittest.mock import MagicMock  # noqa: E402

from lisp.plugins.list_layout.playing_widgets import (  # noqa: E402
    RunningMediaCueWidget,
)


class _FakeMedia:
    """Bare media stub that supports ``element(name)`` lookup."""

    def __init__(self, volume_element=None):
        self._elements = {"Volume": volume_element}

    def element(self, name):
        return self._elements.get(name)


class _FakeMediaCue:
    def __init__(self, volume_element=None):
        self.media = _FakeMedia(volume_element=volume_element)


def _bare_volume_widget(cue):
    """Bypass the real ``__init__`` (needs GStreamer) and wire only
    the attributes the methods under test touch. Mirrors the
    ``_bare_media_widget`` helper in ``test_playing_widgets.py``.
    """
    widget = RunningMediaCueWidget.__new__(RunningMediaCueWidget)
    widget.cue = cue
    widget.volumeIndicator = VolumeIndicatorLabel()
    widget._volume_indicator_requested = False
    return widget


class TestSetVolumeIndicatorVisible:
    def test_enable_with_volume_element_reveals_label(self, qtbot):
        fake_vol = MagicMock()
        fake_vol.live_volume = 1.0
        cue = _FakeMediaCue(volume_element=fake_vol)
        widget = _bare_volume_widget(cue)
        qtbot.addWidget(widget.volumeIndicator)

        widget.set_volume_indicator_visible(True)

        assert widget.volumeIndicator.isVisible()
        assert widget.volumeIndicator.text() == "+0.0 dB"

    def test_disable_hides_label(self, qtbot):
        fake_vol = MagicMock()
        fake_vol.live_volume = 1.0
        cue = _FakeMediaCue(volume_element=fake_vol)
        widget = _bare_volume_widget(cue)
        qtbot.addWidget(widget.volumeIndicator)

        widget.set_volume_indicator_visible(True)
        widget.set_volume_indicator_visible(False)

        assert not widget.volumeIndicator.isVisible()

    def test_missing_volume_element_keeps_label_hidden(self, qtbot):
        """User disabled the Volume element in media settings —
        label hides silently rather than crashing."""
        cue = _FakeMediaCue(volume_element=None)
        widget = _bare_volume_widget(cue)
        qtbot.addWidget(widget.volumeIndicator)

        widget.set_volume_indicator_visible(True)

        assert not widget.volumeIndicator.isVisible()


class TestUpdateVolumeLabel:
    def test_update_reads_live_volume_and_formats(self, qtbot):
        fake_vol = MagicMock()
        fake_vol.live_volume = 0.5  # -6.0 dB
        cue = _FakeMediaCue(volume_element=fake_vol)
        widget = _bare_volume_widget(cue)
        qtbot.addWidget(widget.volumeIndicator)
        widget._volume_indicator_requested = True

        widget._update_volume_label(0)

        assert widget.volumeIndicator.isVisible()
        assert widget.volumeIndicator.text() == "-6.0 dB"

    def test_update_hides_label_when_element_disappears(self, qtbot):
        """Element goes from present to None between ticks (e.g.
        media settings change): label hides, no exception."""
        fake_vol = MagicMock()
        fake_vol.live_volume = 1.0
        cue = _FakeMediaCue(volume_element=fake_vol)
        widget = _bare_volume_widget(cue)
        qtbot.addWidget(widget.volumeIndicator)

        widget.set_volume_indicator_visible(True)
        assert widget.volumeIndicator.isVisible()

        cue.media._elements["Volume"] = None
        widget._update_volume_label(0)

        assert not widget.volumeIndicator.isVisible()
