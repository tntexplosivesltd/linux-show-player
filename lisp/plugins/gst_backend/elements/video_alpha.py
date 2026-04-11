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

from PyQt5.QtCore import QT_TRANSLATE_NOOP

from lisp.backend.media_element import ElementType, MediaType
from lisp.core.fader import Fader
from lisp.plugins.gst_backend.gi_repository import Gst
from lisp.core.properties import Property
from lisp.plugins.gst_backend.gst_element import GstMediaElement

logger = logging.getLogger(__name__)


class VideoAlpha(GstMediaElement):
    """Video opacity control for fade-to-black.

    Uses a ``compositor`` element with a single input.  The
    sink pad's ``alpha`` property controls opacity:
    1.0 = fully visible, 0.0 = transparent (black background
    shows through).

    A ``videoconvert`` after the compositor re-negotiates caps
    on each loop iteration, fixing the looping glitch found in
    PR #349.
    """

    ElementType = ElementType.Plugin
    MediaType = MediaType.Video
    Name = QT_TRANSLATE_NOOP(
        "MediaElementName", "Video Opacity"
    )

    # Saved alpha level — restored on stop, persisted in sessions.
    alpha = Property(default=1.0)

    def __init__(self, pipeline):
        super().__init__(pipeline)

        self.gst_compositor = Gst.ElementFactory.make(
            "compositor", None
        )
        # Black background — visible when alpha < 1.0
        self.gst_compositor.set_property("background", 1)

        self.gst_videoconvert = Gst.ElementFactory.make(
            "videoconvert", None
        )

        self.pipeline.add(self.gst_compositor)
        self.pipeline.add(self.gst_videoconvert)

        # Request a sink pad from the compositor.
        # compositor uses request pads (sink_%u), not static.
        tmpl = self.gst_compositor.get_pad_template(
            "sink_%u"
        )
        self._sink_pad = (
            self.gst_compositor.request_pad(
                tmpl, None, None
            )
        )

        self.gst_compositor.link(self.gst_videoconvert)

        # Keep alpha in sync when the saved property changes
        self.changed("alpha").connect(self.__alpha_changed)

    @property
    def live_alpha(self):
        """Current pad alpha — used by the fader."""
        if self._sink_pad is not None:
            return self._sink_pad.get_property("alpha")
        return self._alpha

    @live_alpha.setter
    def live_alpha(self, value):
        if self._sink_pad is not None:
            self._sink_pad.set_property("alpha", value)

    def get_fader(self, property_name):
        if property_name == "live_alpha":
            return Fader(self, "live_alpha")
        return super().get_fader(property_name)

    def sink(self):
        # Not in the linear audio chain — wired via post_link.
        return None

    def src(self):
        # Not in the linear audio chain — wired via post_link.
        return None

    def video_sink(self):
        """Video input — used by post_link to wire the video
        branch."""
        return self.gst_compositor

    def video_src(self):
        """Video output — feeds the next video element or
        VideoSink's queue."""
        return self.gst_videoconvert

    def stop(self):
        self.live_alpha = self.alpha

    def dispose(self):
        self.pipeline.remove(self.gst_compositor)
        self.pipeline.remove(self.gst_videoconvert)

    def __alpha_changed(self, value):
        self.live_alpha = value
