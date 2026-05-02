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

"""Tests for the General settings page's live theme application.

When the user picks a different theme in the dropdown and clicks
Apply/OK, the new theme should be applied to the running QApplication
immediately — without requiring a restart. The settings dialog's
``applySettings`` calls ``page.getSettings()`` then ``conf.write()``;
the live-apply hook lives at the end of ``AppGeneral.getSettings``."""


class TestAppGeneralLiveThemeApply:

    def setup_method(self):
        from lisp.ui import themes
        themes._active = None
        themes._THEMES.clear()  # force re-discovery so all themes load

    def teardown_method(self):
        from lisp.ui import themes
        themes._active = None

    def _build_page(self, qapp):
        from lisp.ui.settings.app_pages.general import AppGeneral
        page = AppGeneral()
        # Minimal settings dict — loadSettings expects these keys.
        page.loadSettings({
            "layout": {"default": "ListLayout"},
            "theme": {"theme": "Dark", "icons": "lisp"},
            "locale": "",
        })
        return page

    def test_get_settings_applies_chosen_theme(self, qapp):
        """Selecting a different theme and calling getSettings (the
        dialog's apply path) should switch the active theme."""
        from lisp.ui import themes
        from lisp.ui.themes.dark.dark import Dark

        Dark().apply(qapp)
        assert isinstance(themes._active, Dark)

        page = self._build_page(qapp)
        page.themeCombo.setCurrentText("Light")

        page.getSettings()

        # Active theme is now Light's instance.
        from lisp.ui.themes.light.light import Light
        assert isinstance(themes._active, Light)

    def test_get_settings_emits_theme_changed(self, qapp):
        """The live-apply path must trip ``theme_changed`` so that
        cue widgets / list rows refresh — same propagation as boot."""
        from lisp.ui import themes
        from lisp.ui.themes.dark.dark import Dark

        Dark().apply(qapp)

        class _Counter:
            fires = 0

            def slot(self):
                self.fires += 1

        counter = _Counter()
        themes.theme_changed.connect(counter.slot)
        try:
            page = self._build_page(qapp)
            page.themeCombo.setCurrentText("Light")
            page.getSettings()
        finally:
            themes.theme_changed.disconnect(counter.slot)

        assert counter.fires >= 1

    def test_get_settings_idempotent_on_same_theme(self, qapp):
        """If the user opens settings, doesn't change the theme, and
        clicks OK, ``apply()`` should NOT be called again — the active
        theme is unchanged. Re-applying is a no-op functionally but
        emits the signal, causing avoidable repaints. The guard skips
        apply when the chosen theme is already active.

        Mirrors production: boot calls ``get_theme(name).apply(...)``
        (lisp/main.py:136), so ``themes._active`` is the registry's
        instance — the same one ``get_theme(name)`` returns later."""
        from lisp.ui import themes
        from lisp.ui.themes import get_theme

        dark = get_theme("Dark")
        dark.apply(qapp)
        assert themes._active is dark

        class _Counter:
            fires = 0

            def slot(self):
                self.fires += 1

        counter = _Counter()
        themes.theme_changed.connect(counter.slot)
        try:
            page = self._build_page(qapp)
            # Same theme already active — no change.
            page.themeCombo.setCurrentText("Dark")
            page.getSettings()
        finally:
            themes.theme_changed.disconnect(counter.slot)

        # Same theme → no re-apply, signal does not fire.
        assert counter.fires == 0
        # And _active remains the SAME instance (not a fresh Dark()).
        assert themes._active is dark

    def test_get_settings_returns_dict_unchanged(self, qapp):
        """The returned dict's contents must be unaffected by the
        apply hook — getSettings still serves the dialog's config
        write path."""
        page = self._build_page(qapp)
        page.themeCombo.setCurrentText("Light")

        result = page.getSettings()

        assert result["theme"]["theme"] == "Light"
