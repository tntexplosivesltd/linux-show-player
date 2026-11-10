import json
from unittest.mock import MagicMock

import pytest

from PyQt5.QtCore import QRect
from PyQt5.QtWidgets import QMainWindow, qApp

from lisp.core.configuration import DummyConfiguration
from lisp.ui import ui_utils
from lisp.ui.ui_utils import restore_window_geometry, save_window_geometry

KEY = "mainWindow.geometry"
SCREEN_KEY = "mainWindow.screen"


class FakeScreen:
    def __init__(self, name, rect):
        self._name = name
        self._rect = rect

    def name(self):
        return self._name

    def geometry(self):
        return self._rect

    def availableGeometry(self):
        return self._rect


class FakeApp:
    """Stands in for `qApp` inside ui_utils with a fixed screen layout."""

    def __init__(self, screens, primary):
        self._screens = screens
        self._primary = primary

    def screens(self):
        return list(self._screens)

    def primaryScreen(self):
        return self._primary

    def screenAt(self, point):
        for screen in self._screens:
            if screen.geometry().contains(point):
                return screen
        return None


@pytest.fixture
def make_window(qtbot):
    def make():
        window = QMainWindow()
        qtbot.addWidget(window)
        return window

    return make


def _primary_rect():
    return qApp.primaryScreen().availableGeometry()


def _saved_conf(make_window, rect, screen_name):
    """A config holding a real Qt blob for `rect`, tagged with a screen."""
    conf = DummyConfiguration()
    window = make_window()
    window.setGeometry(rect)
    save_window_geometry(window, conf, KEY, SCREEN_KEY)
    conf.set(SCREEN_KEY, screen_name)
    return conf


# -- save --------------------------------------------------------------------


def test_save_stores_json_serialisable_blob_and_screen_name(make_window):
    conf = DummyConfiguration()
    window = make_window()
    window.setGeometry(
        QRect(_primary_rect().topLeft(), _primary_rect().size() / 2)
    )

    save_window_geometry(window, conf, KEY, SCREEN_KEY)

    value = conf.get(KEY)
    assert isinstance(value, str) and value
    assert conf.get(SCREEN_KEY) == qApp.primaryScreen().name()
    json.dumps(conf.get("mainWindow"))


def test_save_off_every_screen_stores_empty_screen_name(
    make_window, monkeypatch
):
    monkeypatch.setattr(ui_utils, "qApp", FakeApp([], None))
    conf = DummyConfiguration()

    save_window_geometry(make_window(), conf, KEY, SCREEN_KEY)

    assert conf.get(SCREEN_KEY) == ""


# -- restore with the real screen setup --------------------------------------


def test_round_trip_restores_saved_geometry(make_window):
    original = QRect(_primary_rect().topLeft(), _primary_rect().size() / 2)
    conf = _saved_conf(make_window, original, qApp.primaryScreen().name())

    restored = make_window()
    assert restore_window_geometry(restored, conf, KEY, SCREEN_KEY) is True
    # Qt may nudge the position by an estimated frame margin on X11;
    # what matters is the size and which monitor the window lands on.
    assert restored.geometry().size() == original.size()
    assert qApp.screenAt(restored.geometry().center()) == qApp.screenAt(
        original.center()
    )


def test_missing_key_falls_back_to_primary_screen(make_window):
    window = make_window()

    assert restore_window_geometry(
        window, DummyConfiguration(), KEY, SCREEN_KEY
    ) is False
    assert window.geometry() == _primary_rect()


@pytest.mark.parametrize(
    "value", ["", "%%not b64", "ünïcode", 123, None, [], {"a": 1}]
)
def test_malformed_saved_value_falls_back_to_primary_screen(
    make_window, value
):
    conf = DummyConfiguration(
        root={
            "mainWindow": {
                "geometry": value,
                "screen": qApp.primaryScreen().name(),
            }
        }
    )
    window = make_window()

    assert restore_window_geometry(window, conf, KEY, SCREEN_KEY) is False
    assert window.geometry() == _primary_rect()


@pytest.mark.parametrize("screen", [None, 42, "NO-SUCH-OUTPUT"])
def test_unknown_saved_screen_falls_back_to_primary_screen(
    make_window, screen
):
    conf = _saved_conf(
        make_window,
        QRect(_primary_rect().topLeft(), _primary_rect().size() / 2),
        screen,
    )
    window = make_window()

    assert restore_window_geometry(window, conf, KEY, SCREEN_KEY) is False
    assert window.geometry() == _primary_rect()


# -- restore against a simulated multi-screen layout -------------------------
#
# The blob itself is restored by real Qt against whatever screens this
# machine (or the offscreen platform) has; the fake layout decides which
# of *our* screens the result lands on. Projector is primary and covers
# the origin, i.e. the worst case for "Qt resolved the wrong index".

PROJECTOR = FakeScreen("HDMI-1", QRect(0, 0, 4000, 4000))
OPERATOR = FakeScreen("DP-1", QRect(4000, 0, 1920, 1080))


@pytest.fixture
def two_screens(monkeypatch):
    monkeypatch.setattr(
        ui_utils, "qApp", FakeApp([PROJECTOR, OPERATOR], PROJECTOR)
    )


def test_restore_moves_window_back_onto_the_named_screen(
    make_window, two_screens
):
    conf = _saved_conf(make_window, QRect(100, 100, 400, 300), "DP-1")
    window = make_window()

    assert restore_window_geometry(window, conf, KEY, SCREEN_KEY) is True

    assert ui_utils.qApp.screenAt(window.geometry().center()) is OPERATOR
    assert window.geometry().size() == QRect(0, 0, 400, 300).size()


def test_restore_keeps_geometry_already_on_the_named_screen(
    make_window, two_screens
):
    conf = _saved_conf(make_window, QRect(100, 100, 400, 300), "HDMI-1")
    expected = make_window()
    expected.restoreGeometry(
        ui_utils.QByteArray.fromBase64(conf.get(KEY).encode("ascii"))
    )
    window = make_window()

    assert restore_window_geometry(window, conf, KEY, SCREEN_KEY) is True
    assert window.geometry() == expected.geometry()


def test_window_larger_than_named_screen_is_shrunk_to_fit(
    make_window, two_screens
):
    conf = _saved_conf(make_window, QRect(0, 0, 3000, 2000), "DP-1")
    window = make_window()

    assert restore_window_geometry(window, conf, KEY, SCREEN_KEY) is True
    assert OPERATOR.availableGeometry().contains(window.geometry())


def test_restore_survives_no_primary_screen(make_window, monkeypatch):
    monkeypatch.setattr(ui_utils, "qApp", FakeApp([], None))
    window = make_window()
    before = window.geometry()

    assert restore_window_geometry(
        window, DummyConfiguration(), KEY, SCREEN_KEY
    ) is False
    assert window.geometry() == before


# -- MainWindow close path ---------------------------------------------------


@pytest.fixture
def main_window(mock_app, qtbot, monkeypatch):
    from lisp.ui import mainwindow
    from lisp.ui.icons import IconTheme

    if IconTheme._GlobalTheme is None:
        IconTheme.set_theme_name("numix")
    mock_app.commands_stack.is_saved.return_value = True
    monkeypatch.setattr(mainwindow.qApp, "quit", lambda: None)
    # MainWindow is a QSingleton and other tests may already have built
    # one: set it aside so we get a fresh window bound to *our* mock_app,
    # and put it back afterwards so we don't leak ours either.
    slot = "_QSingleton__instance"
    previous = mainwindow.MainWindow.__dict__.get(slot)
    if previous is not None:
        delattr(mainwindow.MainWindow, slot)
    window = mainwindow.MainWindow(mock_app)
    qtbot.addWidget(window)
    yield window
    delattr(mainwindow.MainWindow, slot)
    if previous is not None:
        setattr(mainwindow.MainWindow, slot, previous)


def test_closing_main_window_persists_geometry_and_screen(
    main_window, mock_app, monkeypatch
):
    write = MagicMock()
    monkeypatch.setattr(mock_app.conf, "write", write)

    assert main_window.close() is True

    assert mock_app.conf.get(KEY)
    assert mock_app.conf.get(SCREEN_KEY) == qApp.primaryScreen().name()
    write.assert_called_once()


def test_closing_main_window_logs_a_failed_write(
    main_window, mock_app, monkeypatch, caplog
):
    monkeypatch.setattr(
        mock_app.conf, "write", MagicMock(side_effect=OSError("disk full"))
    )

    assert main_window.close() is True

    assert "Could not persist main window state" in caplog.text
