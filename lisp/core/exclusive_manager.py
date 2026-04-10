# This file is part of Linux Show Player
#
# Copyright 2024 Francesco Ceruti <ceppofrancy@gmail.com>
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
import threading

from lisp.cues.cue import CueState
from lisp.ui.widgets.notification import NotificationLevel

logger = logging.getLogger(__name__)


class ExclusiveManager:
    """Enforces exclusive cue playback.

    When a cue with exclusive=True is running, all other cues are
    blocked from starting until the exclusive cue stops.
    """

    def __init__(self, app):
        self._app = app
        self._cue_model = app.cue_model
        self._lock = threading.Lock()

    def is_start_blocked(self, cue):
        """Return True if the cue should be blocked from starting.

        A cue is blocked if any exclusive cue is currently running.
        """
        with self._lock:
            cues = list(self._cue_model)

        for other in cues:
            if other is cue:
                continue
            if other.exclusive and other.state & CueState.IsRunning:
                message = (
                    f'Blocked by exclusive cue '
                    f'#{other.index + 1} "{other.name}"'
                )
                logger.info(message)
                self._app.notify.emit(
                    message, NotificationLevel.Info
                )
                return True

        return False
