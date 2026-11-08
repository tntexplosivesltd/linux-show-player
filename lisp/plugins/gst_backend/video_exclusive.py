# This file is part of Linux Show Player
#
# Copyright 2025 Thomas Sherlock
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
import weakref

from lisp.ui.widgets.notification import NotificationLevel

logger = logging.getLogger(__name__)


class ActiveVideoSinks:
    """The VideoSinks whose cue is playing or paused — what video
    exclusivity is decided on.

    Fed by the VideoSink lifecycle (play → stop/eos/dispose), NOT by
    the compositor's render branches: a cue whose video cannot be
    projected (compositor unavailable, attach failed, or the projection
    shut down by an error) still plays its audio, and another video cue
    must still not play over it. Called from cue worker threads, the
    main thread and cue bus watches, hence the lock. Weak, so a sink
    that is never stopped or disposed does not leak.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._sinks = weakref.WeakSet()

    def add(self, sink):
        with self._lock:
            self._sinks.add(sink)

    def discard(self, sink):
        with self._lock:
            self._sinks.discard(sink)

    def others(self, sink):
        """True if any sink OTHER than `sink` is active."""
        with self._lock:
            return any(s is not sink for s in self._sinks)

    def clear(self):
        with self._lock:
            self._sinks.clear()


active_video_sinks = ActiveVideoSinks()


class VideoExclusiveManager:
    """Blocks video/image cues from overlapping.

    Only one video/image cue can be active at a time: blocked while
    any OTHER VideoSink is active (see ActiveVideoSinks).
    """

    def __init__(self, app):
        self._app = app

    def is_start_blocked(self, cue):
        """Return True if the cue should be blocked from starting.

        A video/image cue is blocked if another video/image cue is
        active (playing or paused), whether or not its video reaches
        the projection — except when the asking cue is that active cue
        (self-resume: CueAction.Resume / Fade & Resume of a paused
        video).
        """
        sink = self._video_sink(cue)
        if sink is None:
            return False

        if not active_video_sinks.others(sink):
            return False

        message = "Blocked: another video/image cue is playing"
        logger.info(message)
        self._app.notify.emit(message, NotificationLevel.Info)
        return True

    @staticmethod
    def _video_sink(cue):
        if not hasattr(cue, "media"):
            return None
        return cue.media.element("VideoSink")
