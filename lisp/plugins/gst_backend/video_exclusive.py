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

from lisp.cues.cue import CueState
from lisp.plugins.gst_backend.gi_repository import Gst
from lisp.ui.widgets.notification import NotificationLevel

logger = logging.getLogger(__name__)


class VideoExclusiveManager:
    """Blocks video/image cues from overlapping.

    Only one video/image cue can be active at a time.  When a
    second video/image cue tries to start, it is blocked —
    following the same pattern as ExclusiveManager.
    """

    def __init__(self, app):
        self._app = app

    def is_start_blocked(self, cue):
        """Return True if the cue should be blocked from starting.

        A video/image cue is blocked if another video/image cue
        is currently playing.
        """
        if not self._is_video_cue(cue):
            return False

        from lisp.plugins.gst_backend.elements.video_sink import (
            VideoSink,
        )

        prev = VideoSink._previous_sink
        if prev is None:
            return False

        # Check the previous sink's pipeline state
        _, state, _ = prev.pipeline.get_state(0)
        if state not in (Gst.State.PLAYING, Gst.State.PAUSED):
            return False

        message = "Blocked: another video/image cue is playing"
        logger.info(message)
        self._app.notify.emit(
            message, NotificationLevel.Info
        )
        return True

    @staticmethod
    def _is_video_cue(cue):
        if not hasattr(cue, "media"):
            return False
        return cue.media.element("VideoSink") is not None
