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

"""Unit tests for the Preload checkbox in MediaCueSettings (Task 18).

These tests exercise the checkbox widget, its loadSettings/getSettings
round-trip, and visibility logic for audio vs. video vs. image cues.
They do not require a live GStreamer backend: _cue is left as None so
loadSettings() exits early before calling get_backend().
"""

import pytest

from lisp.ui.settings.cue_pages.media_cue import MediaCueSettings


class TestPreloadCheckboxDefault:
    def test_default_unchecked(self, qtbot):
        """Checkbox must be unchecked when no preload key in settings."""
        page = MediaCueSettings()
        qtbot.addWidget(page)
        page.loadSettings({"media": {}})

        assert not page.preloadCheckBox.isChecked()

    def test_default_unchecked_when_key_absent(self, qtbot):
        """Absent preload key in settings dict ⇒ unchecked."""
        page = MediaCueSettings()
        qtbot.addWidget(page)
        page.loadSettings({})

        assert not page.preloadCheckBox.isChecked()


class TestPreloadLoadSettings:
    def test_loads_true(self, qtbot):
        """loadSettings with preload=True checks the box."""
        page = MediaCueSettings()
        qtbot.addWidget(page)
        page.loadSettings({"preload": True, "media": {}})

        assert page.preloadCheckBox.isChecked()

    def test_loads_false(self, qtbot):
        """loadSettings with preload=False unchecks the box."""
        page = MediaCueSettings()
        qtbot.addWidget(page)
        # First set to True to ensure we're actually resetting.
        page.preloadCheckBox.setChecked(True)
        page.loadSettings({"preload": False, "media": {}})

        assert not page.preloadCheckBox.isChecked()

    def test_reads_from_top_level_not_media(self, qtbot):
        """preload must be read from the top-level dict, not media.*."""
        page = MediaCueSettings()
        qtbot.addWidget(page)
        # Deliberately nest under media (wrong location) — should be ignored.
        page.loadSettings({"media": {"preload": True}})

        assert not page.preloadCheckBox.isChecked()


class TestPreloadGetSettings:
    def test_returns_preload_at_top_level(self, qtbot):
        """getSettings() must include 'preload' at the top level."""
        page = MediaCueSettings()
        qtbot.addWidget(page)
        page.loadSettings({"media": {}})
        page.preloadCheckBox.setChecked(True)

        result = page.getSettings()
        assert "preload" in result
        assert result["preload"] is True

    def test_preload_not_nested_under_media(self, qtbot):
        """preload must NOT appear under result['media']."""
        page = MediaCueSettings()
        qtbot.addWidget(page)
        page.loadSettings({"media": {}})
        page.preloadCheckBox.setChecked(True)

        result = page.getSettings()
        assert "preload" not in result.get("media", {})

    def test_roundtrip_true(self, qtbot):
        """Load True → getSettings returns True."""
        page = MediaCueSettings()
        qtbot.addWidget(page)
        page.loadSettings({"preload": True, "media": {}})

        assert page.getSettings()["preload"] is True

    def test_roundtrip_false(self, qtbot):
        """Load False → getSettings returns False."""
        page = MediaCueSettings()
        qtbot.addWidget(page)
        page.loadSettings({"preload": False, "media": {}})

        assert page.getSettings()["preload"] is False

    def test_default_roundtrip(self, qtbot):
        """No preload key in input → getSettings returns False."""
        page = MediaCueSettings()
        qtbot.addWidget(page)
        page.loadSettings({"media": {}})

        assert page.getSettings()["preload"] is False


class TestPreloadVisibility:
    """Visibility is tested via isHidden() for un-shown widgets.

    Qt's isVisible() is always False for un-shown top-level widgets
    regardless of setVisible() calls. isHidden() reflects the explicit
    hide flag set by setVisible(False), which is what we care about here.
    """

    def test_not_hidden_for_audio_cue(self, qtbot):
        """UriInput (audio) cues must not hide the preload checkbox."""
        page = MediaCueSettings()
        qtbot.addWidget(page)
        page.loadSettings({"media": {"UriInput": {}}})

        assert not page.preloadCheckBox.isHidden()

    def test_hidden_for_image_cue(self, qtbot):
        """ImageInput cues must hide the preload checkbox."""
        page = MediaCueSettings()
        qtbot.addWidget(page)
        page.loadSettings({"media": {"ImageInput": {}}})

        assert page.preloadCheckBox.isHidden()

    def test_hidden_for_image_cue_via_element_classes(self, qtbot):
        """_element_classes fallback must also hide for ImageInput."""
        page = MediaCueSettings()
        qtbot.addWidget(page)
        page.loadSettings(
            {"media": {"_element_classes": ["ImageInput"]}}
        )

        assert page.preloadCheckBox.isHidden()

    def test_hidden_for_av_cue(self, qtbot):
        """UriAvInput (A/V) cues must hide the preload checkbox."""
        page = MediaCueSettings()
        qtbot.addWidget(page)
        page.loadSettings({"media": {"UriAvInput": {}}})

        assert page.preloadCheckBox.isHidden()

    def test_hidden_for_av_cue_via_element_classes(self, qtbot):
        """_element_classes fallback must also hide for UriAvInput."""
        page = MediaCueSettings()
        qtbot.addWidget(page)
        page.loadSettings(
            {"media": {"_element_classes": ["UriAvInput"]}}
        )

        assert page.preloadCheckBox.isHidden()

    def test_not_hidden_when_no_input_type_specified(self, qtbot):
        """Empty media dict (unknown type) must not hide the checkbox."""
        page = MediaCueSettings()
        qtbot.addWidget(page)
        page.loadSettings({"media": {}})

        assert not page.preloadCheckBox.isHidden()

    def test_visibility_toggles_between_cue_types(self, qtbot):
        """Navigating audio→video→audio must update visibility correctly."""
        page = MediaCueSettings()
        qtbot.addWidget(page)

        page.loadSettings({"media": {"UriInput": {}}})
        assert not page.preloadCheckBox.isHidden()

        page.loadSettings({"media": {"UriAvInput": {}}})
        assert page.preloadCheckBox.isHidden()

        page.loadSettings({"media": {"UriInput": {}}})
        assert not page.preloadCheckBox.isHidden()
