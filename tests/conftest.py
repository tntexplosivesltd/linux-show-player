import pytest
from unittest.mock import MagicMock

from lisp.core.configuration import DummyConfiguration


@pytest.fixture(scope="session", autouse=True)
def qapp_session(qapp):
    """QApplication must exist before any lisp module import.

    Many modules call translate() at class level, which calls
    QApplication.translate(). Without a QApplication, imports crash.
    """
    return qapp


@pytest.fixture
def mock_app():
    """Lightweight mock of Application for unit tests.

    Never instantiate the real Singleton Application in tests.
    """
    app = MagicMock()
    app.conf = DummyConfiguration(root={
        "cue": {
            "interruptFade": 0,
            "interruptFadeType": "Linear",
            "fadeAction": 0,
            "fadeActionType": "Linear",
        }
    })
    return app
