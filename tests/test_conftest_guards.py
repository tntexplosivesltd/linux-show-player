"""The test-suite guards in tests/conftest.py actually fire.

_guard_application_threads refuses to construct the Application
singleton off the main thread (that built Qt widgets on a worker
thread and crashed unrelated tests later); see its docstring.
Main-thread construction passing through is covered by the UI tests
that build the real Application.
"""

import threading

from lisp.application import Application
from tests import conftest


def test_application_built_off_the_main_thread_is_refused_and_recorded():
    # __init__ directly, on a fresh object: Application() would return
    # the singleton if an earlier test built it on the main thread.
    errors = []

    def worker():
        try:
            Application.__init__(object.__new__(Application))
        except RuntimeError as e:
            errors.append(e)

    before = len(conftest._APP_OFF_THREAD)
    thread = threading.Thread(target=worker, name="guard-probe")
    thread.start()
    thread.join(10)

    assert errors and "off the main thread" in str(errors[0])
    recorded = conftest._APP_OFF_THREAD[before:]
    # Consume it, or the autouse checker would fail this test.
    del conftest._APP_OFF_THREAD[before:]
    assert [name for name, _ in recorded] == ["guard-probe"]
    assert "worker" in recorded[0][1]  # the stack of the attempt

