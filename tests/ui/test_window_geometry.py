import json

import pytest

from PyQt5.QtCore import QRect
from PyQt5.QtWidgets import QMainWindow, qApp

from lisp.core.configuration import DummyConfiguration
from lisp.ui.ui_utils import restore_window_geometry, save_window_geometry

KEY = "mainWindow.geometry"


def _primary_rect():
    return qApp.primaryScreen().availableGeometry()


def test_restore_without_saved_value_uses_primary_screen():
    conf = DummyConfiguration()
    window = QMainWindow()

    assert restore_window_geometry(window, conf, KEY) is False
    assert window.geometry() == _primary_rect()


def test_save_stores_json_serialisable_string():
    conf = DummyConfiguration()
    window = QMainWindow()
    window.setGeometry(QRect(50, 60, 700, 500))

    save_window_geometry(window, conf, KEY)

    value = conf.get(KEY)
    assert isinstance(value, str) and value
    json.dumps(value)


def test_round_trip_restores_saved_geometry():
    conf = DummyConfiguration()
    original = QRect(_primary_rect().topLeft(), _primary_rect().size() / 2)
    window = QMainWindow()
    window.setGeometry(original)
    save_window_geometry(window, conf, KEY)

    restored = QMainWindow()
    assert restore_window_geometry(restored, conf, KEY) is True
    # Qt may nudge the position by an estimated frame margin on X11;
    # what matters is the size and which monitor the window lands on.
    assert restored.geometry().size() == original.size()
    assert qApp.screenAt(restored.geometry().center()) == qApp.screenAt(
        original.center()
    )


def test_corrupt_saved_value_falls_back_to_primary_screen():
    conf = DummyConfiguration(root={"mainWindow": {"geometry": "%%not b64"}})
    window = QMainWindow()

    assert restore_window_geometry(window, conf, KEY) is False
    assert window.geometry() == _primary_rect()


def test_restores_onto_the_saved_non_primary_screen():
    others = [s for s in qApp.screens() if s != qApp.primaryScreen()]
    if not others:
        pytest.skip("needs a second screen")
    target = others[0].availableGeometry()
    conf = DummyConfiguration()
    window = QMainWindow()
    window.setGeometry(QRect(target.topLeft(), target.size() / 2))
    save_window_geometry(window, conf, KEY)

    restored = QMainWindow()
    restore_window_geometry(restored, conf, KEY)

    assert qApp.screenAt(restored.geometry().center()) == others[0]
