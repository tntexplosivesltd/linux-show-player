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

from lisp.ui.widgets.notification import NotificationLevel

logger = logging.getLogger(__name__)


class VideoExclusiveManager:
    """Blocks video/image cues from overlapping.

    Only one video/image cue can be active at a time. Backed by a single
    query against VideoCompositor ("is any cue OTHER than this one
    currently registered?") — no per-sink pipeline-state introspection.
    """

    def __init__(self, app):
        self._app = app

    def is_start_blocked(self, cue):
        """Return True if the cue should be blocked from starting.

        A video/image cue is blocked if another video/image cue is
        registered with the compositor (playing or paused) — except
        when the asking cue owns that registration (self-resume).
        """
        sink = self._video_sink(cue)
        if sink is None:
            return False

        # Lazy import: gst_backend imports this module at top level, so
        # a top-level `import GstBackend` here would be a cycle.
        from lisp.plugins.gst_backend.gst_backend import GstBackend

        compositor = GstBackend.video_compositor()
        if compositor is None:
            return False

        # active_others excludes this cue's own sink, so a self-resume
        # (CueAction.Resume / Fade & Resume of a paused video) is never
        # blocked by its own registration.
        if not compositor.active_others(sink):
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
