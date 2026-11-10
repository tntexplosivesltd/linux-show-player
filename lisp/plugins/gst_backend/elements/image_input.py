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

# Cycle-safe: video_compositor imports only gi_repository.
from lisp.plugins.gst_backend.video_compositor import (
    COMP_HEIGHT,
    COMP_WIDTH,
    fit_rect,
)

logger = logging.getLogger(__name__)

# videoscale method (by nick) for the one-off downscale: a still can be
# 3-4x the projector, where bilinear aliases fine detail. It runs once
# per image, so the best filter is affordable: decode+scale+convert of
# a 6000x3375 PNG measured ~380-440 ms with lanczos or bilinear alike
# (decoding it alone ~380 ms).
PRESCALE_METHOD = "lanczos"


def prescale_size(src_w, src_h, par_n, par_d, canvas_w, canvas_h):
    """The size a still is scaled to before imagefreeze, or None to
    leave it as decoded.

    imagefreeze repeats its input every frame, and each repeat is
    copied into the projection and uploaded to the GPU. A still larger
    than the canvas is scaled down to fit inside it, square pixels,
    once, so every repeat is canvas-sized, not e.g. an 81 MB 6000x3375
    frame (which dropped the whole projection to ~1 fps). Never
    upscaled: the GPU mixer does that for free. Rounded down to even,
    which chroma-subsampled formats (I420) need.
    """
    if src_w <= 0 or src_h <= 0 or par_n <= 0 or par_d <= 0:
        return None
    display_w = src_w * par_n / par_d
    if display_w <= canvas_w and src_h <= canvas_h:
        return None
    _, _, width, height = fit_rect(
        src_w, src_h, par_n, par_d, canvas_w, canvas_h
    )
    return max(2, width & ~1), max(2, height & ~1)


def _canvas_size():
    """The projection canvas, or the default before there is one.

    Imported inside the call (not at module top) to avoid the
    gst_backend <-> elements import cycle (see video_sink._compositor).
    """
    from lisp.plugins.gst_backend.gst_backend import GstBackend

    compositor = GstBackend.video_compositor()
    if compositor is None:
        return COMP_WIDTH, COMP_HEIGHT
    return compositor.canvas_size()


class ImageInput(GstSrcElement):
    """Still image source using imagefreeze for continuous video.

    Pipeline: uridecodebin -> videoscale -> capsfilter -> videoconvert
              -> imagefreeze

    imagefreeze is last: what comes before it runs once per image,
    what comes after it on every repeated frame. So a still is scaled
    down to the projection canvas (prescale_size) and converted once,
    before it is frozen.

    imagefreeze converts a single decoded frame into a continuous video
    stream, allowing still images to flow through the same video
    pipeline as actual video files.

    Since imagefreeze produces an infinite stream and does not respect
    GStreamer seek stop positions, a timer sends EOS to the pipeline
    when the configured duration elapses.

    Note: `MediaCue.start_time` has no effect on image cues — a still
    frame has no seekable position. Image display duration is controlled
    exclusively by this element's `duration` property (via the EOS timer).
    """

    MediaType = MediaType.Video
    Name = QT_TRANSLATE_NOOP("MediaElementName", "Image Input")

    uri = GstURIProperty("decoder", "uri")

    def __init__(self, pipeline):
        super().__init__(pipeline)

        self.decoder = Gst.ElementFactory.make("uridecodebin", None)
        self.video_scale = Gst.ElementFactory.make("videoscale", None)
        Gst.util_set_object_arg(
            self.video_scale, "method", PRESCALE_METHOD
        )
        # Set per image in __on_pad_added (prescale_size).
        self.scale_filter = Gst.ElementFactory.make("capsfilter", None)
        self.video_convert = Gst.ElementFactory.make(
            "videoconvert", None
        )
        self.freeze = Gst.ElementFactory.make("imagefreeze", None)
        # One-off work on a big frame: use every core.
        for element in (self.video_scale, self.video_convert):
            element.set_property("n-threads", 0)

        self._pad_handler = self.decoder.connect(
            "pad-added", self.__on_pad_added
        )
        self._linked = False

        self.pipeline.add(self.decoder)
        self.pipeline.add(self.video_scale)
        self.pipeline.add(self.scale_filter)
        self.pipeline.add(self.video_convert)
        self.pipeline.add(self.freeze)

        self.video_scale.link(self.scale_filter)
        self.scale_filter.link(self.video_convert)
        self.video_convert.link(self.freeze)

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
        return self.freeze

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
            try:
                self.__set_prescale(caps)
            except Exception:
                # Slow beats blank: show it as decoded.
                logger.exception("ImageInput: prescale failed")
                self.scale_filter.set_property("caps", Gst.Caps.new_any())
            sink_pad = self.video_scale.get_static_pad("sink")
            result = pad.link(sink_pad)
            if result == Gst.PadLinkReturn.OK:
                self._linked = True
            else:
                logger.warning(
                    "ImageInput: failed to link video pad: %s",
                    result,
                )

    def __set_prescale(self, caps):
        """Streaming thread, before the decoded pad is linked: pin the
        scale filter to this image's prescale_size() (ANY = as is)."""
        struct = caps.get_structure(0)
        ok_w, width = struct.get_int("width")
        ok_h, height = struct.get_int("height")
        ok_par, par_n, par_d = struct.get_fraction("pixel-aspect-ratio")
        if not ok_par:
            par_n, par_d = 1, 1
        size = None
        if ok_w and ok_h:
            size = prescale_size(width, height, par_n, par_d, *_canvas_size())
        if size is None:
            self.scale_filter.set_property("caps", Gst.Caps.new_any())
            return
        logger.debug(
            "ImageInput: prescaling %dx%d to %dx%d", width, height, *size
        )
        self.scale_filter.set_property(
            "caps",
            Gst.Caps.from_string(
                f"video/x-raw,width={size[0]},height={size[1]},"
                "pixel-aspect-ratio=1/1"
            ),
        )
