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

import logging

from lisp.core.plugin import Plugin
from lisp.plugins.test_harness.dispatcher import Dispatcher
from lisp.plugins.test_harness.handlers import register_all
from lisp.plugins.test_harness.qt_invoke import init_invoker
from lisp.plugins.test_harness.server import ServerThread
from lisp.plugins.test_harness.signal_manager import SignalManager

logger = logging.getLogger(__name__)


class TestHarness(Plugin):
    Name = "Test Harness"
    Description = (
        "JSON-RPC server for automated testing and "
        "AI-driven end-to-end testing"
    )
    Authors = ("Linux Show Player Contributors",)
    CorePlugin = False
    Depends = ()
    OptDepends = ()

    def __init__(self, app):
        super().__init__(app)

        # Must be called on the main thread before server starts
        init_invoker()

        host = TestHarness.Config["host"]
        port = TestHarness.Config["port"]
        max_buffer = TestHarness.Config["maxEventBuffer"]

        self.signal_manager = SignalManager(app, max_buffer=max_buffer)
        self.dispatcher = Dispatcher()
        register_all(self.dispatcher, app, self.signal_manager)

        self.server_thread = ServerThread(host, port, self.dispatcher)
        self.server_thread.start()

        logger.info("Test harness listening on %s:%d", host, port)

    def finalize(self):
        self.signal_manager.unsubscribe_all()
        self.server_thread.stop()
        logger.info("Test harness stopped")
        super().finalize()
