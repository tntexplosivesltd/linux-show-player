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

"""The Video Monitor remembers where it was and whether the operator
left it open, and GstBackend reopens it at the next launch."""

from unittest.mock import MagicMock

import pytest
from PyQt5.QtCore import QRect
from PyQt5.QtWidgets import QMainWindow

from lisp.core.configuration import DummyConfiguration
from lisp.core.signal import Signal
from lisp.plugins.gst_backend import gst_video_window as gvw
from lisp.plugins.gst_backend.gst_backend import GstBackend
from lisp.plugins.gst_backend.gst_video_window import VideoMonitorWindow

# The real-__init__ backend builder, shared with the compositor tests.
# Fetched with request.getfixturevalue("build") below, so no test
# parameter shadows this import.
from tests.plugins.gst_backend.test_gst_backend_compositor import (  # noqa: F401
    build,
)


def _build_backend(request):
    backend, _app, _comp, _ = request.getfixturevalue("build")()
    return backend

OPEN = VideoMonitorWindow.OPEN_KEY
GEOMETRY = VideoMonitorWindow.GEOMETRY_KEY
SCREEN = VideoMonitorWindow.SCREEN_KEY


class _UnwritableConfig(DummyConfiguration):
    """A config whose file can't be written (full disk, read-only)."""

    def write(self):
        raise OSError(28, "No space left on device")


@pytest.fixture
def config():
    return DummyConfiguration(root={})


@pytest.fixture
def make_monitor(qtbot, config):
    def _make(parent=None, conf=config):
        window = VideoMonitorWindow(parent, config=conf)
        if parent is None:
            qtbot.addWidget(window)
        return window

    return _make


class TestVideoMonitorWindowMemory:
    def test_open_is_remembered_with_geometry(self, make_monitor, config):
        monitor = make_monitor()

        monitor.open_and_remember()

        assert monitor.isVisible()
        assert config.get(OPEN) is True
        assert config.get(GEOMETRY)

    def test_operator_close_is_remembered(self, make_monitor, config):
        monitor = make_monitor()
        monitor.open_and_remember()

        monitor.close()

        assert not monitor.isVisible()
        assert config.get(OPEN) is False

    def test_geometry_round_trips_to_the_next_launch(
        self, make_monitor, config, qtbot
    ):
        first = make_monitor()
        first.setGeometry(QRect(100, 120, 500, 300))
        first.open_and_remember()
        qtbot.waitExposed(first)
        saved = first.geometry()
        first.close()

        second = make_monitor()

        assert second.geometry().size() == saved.size()
        assert second.geometry().topLeft() == saved.topLeft()

    def test_missing_screen_keeps_default_size(self, make_monitor, config):
        """On a machine without the saved screen the monitor keeps its
        640x360 default instead of filling the primary screen."""
        first = make_monitor()
        first.resize(500, 300)
        first.open_and_remember()
        config.set(SCREEN, "NO-SUCH-OUTPUT")

        second = make_monitor()

        assert (second.width(), second.height()) == (640, 360)

    def test_main_window_close_does_not_count_as_closing(
        self, make_monitor, config, qtbot
    ):
        """LiSP exits by closing the main window; the monitor (its
        child window) must still be recorded as open."""
        main = QMainWindow()
        qtbot.addWidget(main)
        main.show()
        monitor = make_monitor(parent=main)
        monitor.open_and_remember()

        main.close()

        assert config.get(OPEN) is True

    def test_unwritable_config_does_not_break_the_window(
        self, make_monitor
    ):
        """A failed write is logged, never raised into Qt (where it
        would abort LiSP), and the monitor still shows and hides."""
        monitor = make_monitor(conf=_UnwritableConfig(root={}))

        monitor.open_and_remember()
        assert monitor.isVisible()
        monitor.close()
        assert not monitor.isVisible()

    def test_without_config_nothing_is_saved(self, qtbot):
        monitor = VideoMonitorWindow()
        qtbot.addWidget(monitor)
        monitor.open_and_remember()
        monitor.close()
        assert not monitor.was_left_open()


_toggle = GstBackend._GstBackend__toggle_monitor_window
_reopen = GstBackend._GstBackend__reopen_monitor


class TestGstBackendMonitorWiring:
    @pytest.fixture
    def backend(self, request):
        return _build_backend(request)

    @pytest.fixture
    def monitor(self, backend, make_monitor, monkeypatch):
        monitor = make_monitor()
        monkeypatch.setattr(GstBackend, "_monitor_window", monitor)
        return monitor

    def test_menu_toggle_opens_and_closes(self, backend, monitor, config):

        _toggle(backend)
        assert monitor.isVisible() and config.get(OPEN) is True
        assert backend._GstBackend__monitor_shown

        _toggle(backend)
        assert not monitor.isVisible() and config.get(OPEN) is False

    def test_monitor_built_with_the_backend_config(self, backend):
        gvw.VideoMonitorWindow.assert_called_once_with(
            backend.app.window, config=GstBackend.Config
        )

    def test_reopen_is_wired_to_the_first_session(self, backend):
        backend.app.session_created.connect.assert_any_call(
            backend._GstBackend__reopen_monitor
        )

    def test_real_signal_reopens_once(self, backend, monitor, config):
        """With a real Signal: the first session reopens it; hidden
        again with the config still "open", a second session (File >
        New) does not, because the slot disconnected itself."""
        config.set(OPEN, True)
        sessions = Signal()
        sessions.connect(backend._GstBackend__reopen_monitor)
        backend.app.session_created = sessions

        sessions.emit(object())
        assert monitor.isVisible()
        monitor.hide()

        sessions.emit(object())
        assert not monitor.isVisible()

    def test_reopens_on_first_session_if_left_open(
        self, backend, monitor, config
    ):
        config.set(OPEN, True)

        _reopen(backend)

        assert monitor.isVisible()
        assert backend._GstBackend__monitor_shown
        backend.app.session_created.disconnect.assert_called_once_with(
            backend._GstBackend__reopen_monitor
        )

    def test_stays_closed_if_left_closed(self, backend, monitor, config):
        config.set(OPEN, False)

        _reopen(backend)

        assert not monitor.isVisible()
        backend.app.session_created.disconnect.assert_called_once()


class TestGstBackendShutdown:
    def test_exit_keeps_it_open_and_saves_where_it_is(
        self, request, make_monitor, config, monkeypatch
    ):
        backend = _build_backend(request)
        monitor = make_monitor()
        monkeypatch.setattr(GstBackend, "_monitor_window", monitor)
        _toggle(backend)
        monitor.move(monitor.x() + 40, monitor.y() + 30)
        moved = monitor.saveGeometry()

        backend.finalize()

        assert config.get(OPEN) is True
        assert config.get(GEOMETRY) == bytes(moved.toBase64()).decode()

    def test_compositor_shuts_down_before_the_save(
        self, request, monkeypatch
    ):
        backend = _build_backend(request)
        order = []
        GstBackend.video_compositor().shutdown.side_effect = (
            lambda: order.append("shutdown")
        )
        monitor = MagicMock()
        monitor.isVisible.return_value = False
        monitor.save_geometry.side_effect = lambda: order.append("save")
        monkeypatch.setattr(GstBackend, "_monitor_window", monitor)
        _toggle(backend)

        backend.finalize()

        assert order == ["shutdown", "save"]


class TestGstBackendFinalizeSavesGeometry:
    def _monitor(self):
        monitor = MagicMock()
        monitor.isVisible.return_value = False
        return monitor

    def test_saves_geometry_after_the_monitor_was_shown(
        self, request, monkeypatch
    ):
        backend = _build_backend(request)
        monitor = self._monitor()
        monkeypatch.setattr(GstBackend, "_monitor_window", monitor)
        _toggle(backend)

        backend.finalize()

        monitor.save_geometry.assert_called_once_with()

    def test_skips_geometry_if_never_shown(self, request, monkeypatch):
        backend = _build_backend(request)
        monitor = self._monitor()
        monkeypatch.setattr(GstBackend, "_monitor_window", monitor)

        backend.finalize()

        monitor.save_geometry.assert_not_called()
