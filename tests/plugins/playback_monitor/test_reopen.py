# This file is part of Linux Show Player
#
# Copyright 2017 Francesco Ceruti <ceppofrancy@gmail.com>
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

"""The Playback Monitor reopens at launch if the operator left it open."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from lisp.core.configuration import DummyConfiguration
from lisp.core.signal import Signal
from lisp.plugins.playback_monitor import playback_monitor as pm
from lisp.plugins.playback_monitor.playback_monitor import PlaybackMonitor

OPEN = PlaybackMonitor.OPEN_KEY


class _UnwritableConfig(DummyConfiguration):
    """A config whose file can't be written (full disk, read-only)."""

    def write(self):
        raise OSError(28, "No space left on device")


@pytest.fixture
def make_plugin(qtbot, monkeypatch):
    plugins = []

    def _make(open_at_exit=None, config_cls=DummyConfiguration):
        root = {"elapsedPrimary": True}
        if open_at_exit is not None:
            root[OPEN] = open_at_exit
        config = config_cls(root=root)
        monkeypatch.setattr(PlaybackMonitor, "Config", config)
        app = SimpleNamespace(
            window=SimpleNamespace(menuTools=MagicMock()),
            cue_model=SimpleNamespace(
                item_added=Signal(),
                item_removed=Signal(),
                model_reset=Signal(),
            ),
            session_before_finalize=Signal(),
            session_created=Signal(),
        )
        plugin = PlaybackMonitor(app)
        plugins.append(plugin)
        return plugin, app, config

    monkeypatch.setattr(pm, "QAction", MagicMock())
    # Plugin.__init__ rebinds the class-level State; monkeypatch
    # restores the original value after the test.
    monkeypatch.setattr(PlaybackMonitor, "State", PlaybackMonitor.State)
    # Register each monitor window with qtbot so it is closed and
    # deleted deterministically after the test.
    real_ctor = pm.PlaybackMonitorWindow

    def tracked_window(*args, **kwargs):
        window = real_ctor(*args, **kwargs)
        qtbot.addWidget(window)
        return window

    monkeypatch.setattr(pm, "PlaybackMonitorWindow", tracked_window)
    yield _make


def _visible(plugin):
    return plugin._window is not None and plugin._window.isVisible()


def test_menu_toggle_records_open_and_closed(make_plugin):
    plugin, _app, config = make_plugin()

    plugin._toggle_window()
    assert _visible(plugin) and config.get(OPEN) is True

    plugin._toggle_window()
    assert not _visible(plugin) and config.get(OPEN) is False

    plugin._toggle_window()
    assert _visible(plugin) and config.get(OPEN) is True


def test_title_bar_close_records_closed(make_plugin):
    plugin, _app, config = make_plugin()
    plugin._toggle_window()

    plugin._window.close()

    assert config.get(OPEN) is False


def test_unwritable_config_does_not_break_opening(make_plugin):
    """The plugin's own "open" write is logged, never raised into
    Qt (where it would abort LiSP), and the window still opens.

    Closing is not covered here: PlaybackMonitorWindow.closeEvent's
    own geometry write is unguarded too, which predates this feature
    (tracked separately)."""
    plugin, _app, config = make_plugin(config_cls=_UnwritableConfig)

    plugin._toggle_window()
    assert _visible(plugin)
    plugin._window.hide()
    plugin._window_closed()  # the close path's own write

    # Teardown closes the window, whose closeEvent write is unguarded.
    config.write = lambda: None


def test_exit_keeps_it_recorded_open(make_plugin):
    """finalize() closes the window as LiSP exits; that is not the
    operator closing it, so the next launch must reopen it."""
    plugin, _app, config = make_plugin()
    plugin._toggle_window()

    plugin.finalize()

    assert config.get(OPEN) is True
    assert config.get("geometry.width") is not None


def test_reopens_at_launch_and_respects_a_later_close(make_plugin):
    """Reopened with the first session; once the operator closes it,
    a later new session (File > New) leaves it closed."""
    plugin, app, config = make_plugin(open_at_exit=True)
    assert plugin._window is None

    app.session_created.emit(object())
    assert _visible(plugin)

    # The operator closes it; a later new session must not reopen it.
    plugin._window.close()
    app.session_created.emit(object())
    assert not _visible(plugin)


def test_only_the_first_session_reopens(make_plugin):
    """Hidden without recording a close (config still "open"), a
    second session must still not reopen it: the slot is gone."""
    plugin, app, config = make_plugin(open_at_exit=True)
    app.session_created.emit(object())
    plugin._window.hide()
    assert config.get(OPEN) is True

    app.session_created.emit(object())

    assert not _visible(plugin)


@pytest.mark.parametrize("open_at_exit", [False, None])
def test_stays_closed_if_not_left_open(make_plugin, open_at_exit):
    """Closed at exit, or a config from before this setting existed."""
    plugin, app, _config = make_plugin(open_at_exit=open_at_exit)

    app.session_created.emit(object())

    assert plugin._window is None
