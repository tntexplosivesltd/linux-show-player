import threading
import traceback

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


# Off-main-thread attempts to construct Application, as (thread, stack).
_APP_OFF_THREAD = []


@pytest.fixture(scope="session", autouse=True)
def _guard_application_threads(qapp_session):
    """Refuse to construct the Application singleton off the main thread,
    for the whole session (a worker started by one test can run after
    it ends). Takes qapp_session: importing lisp.application needs the
    QApplication.

    Application() builds the whole MainWindow. Called first from a
    worker thread (e.g. a UriInput duration probe resolving a
    SessionURI), it built Qt widgets off the GUI thread. That corrupted
    Qt, and an unrelated later test crashed in paintEvent (SIGSEGV /
    SIGILL, intermittent). Main-thread construction is let through:
    some UI tests rely on it (against the mock_app rule), and it does
    not corrupt Qt.

    Limit: only the FIRST construction runs __init__. Once a
    main-thread test has built the singleton, Application() returns it
    from any thread and this guard is silent, so a missing SessionURI
    bypass is caught only in tests that run before that (test order
    matters). Off-thread reuse is not flagged on purpose: LiSP's own
    duration probe reuses the Application from a worker thread.
    """
    from lisp.application import Application

    real_init = Application.__init__

    def guarded(self, *args, **kwargs):
        if threading.current_thread() is threading.main_thread():
            return real_init(self, *args, **kwargs)
        _APP_OFF_THREAD.append((
            threading.current_thread().name,
            "".join(traceback.format_stack(limit=14)[:-1]),
        ))
        raise RuntimeError(
            "the Application singleton must not be constructed off the "
            "main thread (use mock_app, or patch "
            "lisp.application.Application or the SessionURI path helpers)"
        )

    Application.__init__ = guarded
    yield
    Application.__init__ = real_init


@pytest.fixture(autouse=True)
def no_application_off_main_thread():
    """Fail the test during which an off-main-thread construction was
    attempted, with each attempt's thread and stack (the worker thread
    itself may swallow the RuntimeError)."""
    before = len(_APP_OFF_THREAD)
    yield
    new = _APP_OFF_THREAD[before:]
    if new:
        pytest.fail(
            "Application constructed off the main thread:\n"
            + "\n".join(
                f"--- on thread {name}:\n{stack}" for name, stack in new
            ),
            pytrace=False,
        )


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
