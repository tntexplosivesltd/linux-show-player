# This file is part of Linux Show Player
#
# Copyright 2024 Linux Show Player Contributors
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

import threading

from PyQt5.QtCore import QEvent, QObject
from PyQt5.QtWidgets import QApplication


class QtCallEvent(QEvent):
    """QEvent that carries a callable to be executed on the Qt main thread."""

    EVENT_TYPE = QEvent.Type(QEvent.registerEventType())

    def __init__(self, fn, result_event):
        super().__init__(self.EVENT_TYPE)
        self.fn = fn
        self.result_event = result_event
        self.result = None
        self.exception = None


class QtInvoker(QObject):
    """QObject that receives QtCallEvents and executes them."""

    def customEvent(self, event):
        if isinstance(event, QtCallEvent):
            try:
                event.result = event.fn()
            except Exception as e:
                event.exception = e
            finally:
                event.result_event.set()


# Module-level invoker instance.
# Must be created on the main thread via init_invoker().
_invoker = None


def init_invoker():
    """Create the QtInvoker on the main thread.

    Must be called from the main thread (e.g. during plugin __init__).
    """
    global _invoker
    _invoker = QtInvoker()
    _invoker.moveToThread(QApplication.instance().thread())


def invoke_on_main_thread(fn, timeout=10.0):
    """Run fn on the Qt main thread, block until done, return result.

    If called from the main thread, executes directly to avoid deadlock.

    :param fn: Callable to execute
    :param timeout: Maximum seconds to wait
    :returns: The return value of fn
    :raises TimeoutError: If the main thread doesn't process within timeout
    :raises Exception: Any exception raised by fn is re-raised
    """
    if _invoker is None:
        raise RuntimeError(
            "QtInvoker not initialized — call init_invoker() first"
        )

    app = QApplication.instance()
    if app is None:
        raise RuntimeError("No QApplication instance")

    # If we're already on the main thread, just call directly
    if threading.current_thread() is threading.main_thread():
        return fn()

    result_event = threading.Event()
    event = QtCallEvent(fn, result_event)
    app.postEvent(_invoker, event)

    if not result_event.wait(timeout):
        raise TimeoutError("Main thread invocation timed out")

    if event.exception is not None:
        raise event.exception

    return event.result
