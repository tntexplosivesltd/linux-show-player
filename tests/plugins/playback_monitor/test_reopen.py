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


@pytest.fixture
def make_plugin(qtbot, monkeypatch):
    plugins = []

    def _make(open_at_exit=None):
        root = {"elapsedPrimary": True}
        if open_at_exit is not None:
            root[OPEN] = open_at_exit
        config = DummyConfiguration(root=root)
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
    monkeypatch.setattr(PlaybackMonitor, "State", PlaybackMonitor.State)
    yield _make
    for plugin in plugins:
        if plugin._window is not None:
            plugin._window.deleteLater()


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


@pytest.mark.parametrize("open_at_exit", [False, None])
def test_stays_closed_if_not_left_open(make_plugin, open_at_exit):
    """Closed at exit, or a config from before this setting existed."""
    plugin, app, _config = make_plugin(open_at_exit=open_at_exit)

    app.session_created.emit(object())

    assert plugin._window is None
