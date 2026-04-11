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
import time
import threading

from PyQt5.QtCore import QT_TRANSLATE_NOOP

from lisp.backend.media_element import MediaType
from lisp.core.session_uri import SessionURI
from lisp.plugins.gst_backend.gi_repository import Gst
from lisp.plugins.gst_backend.gst_element import GstSrcElement
from lisp.plugins.gst_backend.gst_properties import GstURIProperty

logger = logging.getLogger(__name__)


class ImageInput(GstSrcElement):
    """Still image source using imagefreeze for continuous video.

    Pipeline: uridecodebin -> imagefreeze -> videoconvert -> videoscale

    imagefreeze converts a single decoded frame into a continuous video
    stream, allowing still images to flow through the same video
    pipeline as actual video files.

    Since imagefreeze produces an infinite stream and does not respect
    GStreamer seek stop positions, a timer sends EOS to the pipeline
    when the configured duration elapses.
    """

    MediaType = MediaType.Video
    Name = QT_TRANSLATE_NOOP("MediaElementName", "Image Input")

    uri = GstURIProperty("decoder", "uri")

    def __init__(self, pipeline):
        super().__init__(pipeline)

        self.decoder = Gst.ElementFactory.make("uridecodebin", None)
        self.freeze = Gst.ElementFactory.make("imagefreeze", None)
        self.video_convert = Gst.ElementFactory.make(
            "videoconvert", None
        )
        self.video_scale = Gst.ElementFactory.make("videoscale", None)

        self._pad_handler = self.decoder.connect(
            "pad-added", self.__on_pad_added
        )
        self._linked = False

        self.pipeline.add(self.decoder)
        self.pipeline.add(self.freeze)
        self.pipeline.add(self.video_convert)
        self.pipeline.add(self.video_scale)

        self.freeze.link(self.video_convert)
        self.video_convert.link(self.video_scale)

        # Default display duration: 5 seconds.
        self.duration = 5000

        # EOS timer state (imagefreeze needs explicit EOS)
        self._eos_timer = None
        self._remaining_ms = 0
        self._play_start = 0.0

    def input_uri(self) -> SessionURI:
        return SessionURI(self.uri)

    def dispose(self):
        self._cancel_timer()
        self.decoder.disconnect(self._pad_handler)

    def src(self):
        """No audio -- images don't produce audio."""
        return None

    def video_src(self):
        """Video source -- feeds the video branch via post_link."""
        return self.video_scale

    def play(self):
        """Start EOS timer. Called by GstMedia before pipeline plays."""
        if self._remaining_ms <= 0:
            self._remaining_ms = self.duration
        self._start_timer()

    def pause(self):
        """Pause EOS timer, recording elapsed time."""
        self._cancel_timer()
        elapsed = (time.monotonic() - self._play_start) * 1000
        self._remaining_ms = max(0, self._remaining_ms - elapsed)

    def stop(self):
        """Cancel EOS timer and reset for next play.

        Also resets the linked flag so uridecodebin's new
        dynamic pads can re-link on the next PAUSED transition.
        """
        self._cancel_timer()
        self._remaining_ms = 0
        self._linked = False

    def _start_timer(self):
        self._cancel_timer()
        if self._remaining_ms > 0:
            self._play_start = time.monotonic()
            self._eos_timer = threading.Timer(
                self._remaining_ms / 1000.0,
                self._on_timer_expired,
            )
            self._eos_timer.daemon = True
            self._eos_timer.start()

    def _cancel_timer(self):
        if self._eos_timer is not None:
            self._eos_timer.cancel()
            self._eos_timer = None

    def _on_timer_expired(self):
        self._eos_timer = None
        logger.debug(
            "ImageInput: display duration reached, posting EOS"
        )
        # Post EOS directly on the bus rather than send_event(),
        # because imagefreeze continuously pushes buffers and
        # swallows downstream EOS events.  The message source
        # must be the pipeline so GstMedia.__on_message matches.
        #
        # Guard against the pipeline being finalized between
        # the timer firing and this callback executing.
        pipeline = self.pipeline
        if pipeline is None:
            return
        bus = pipeline.get_bus()
        if bus is not None:
            bus.post(Gst.Message.new_eos(pipeline))

    def __on_pad_added(self, decodebin, pad):
        caps = pad.get_current_caps()
        if caps is None:
            return

        struct_name = caps.get_structure(0).get_name()
        if struct_name.startswith("video/"):
            if self._linked:
                logger.debug(
                    "ImageInput: ignoring extra video pad"
                )
                return
            sink_pad = self.freeze.get_static_pad("sink")
            result = pad.link(sink_pad)
            if result == Gst.PadLinkReturn.OK:
                self._linked = True
            else:
                logger.warning(
                    "ImageInput: failed to link video pad: %s",
                    result,
                )
