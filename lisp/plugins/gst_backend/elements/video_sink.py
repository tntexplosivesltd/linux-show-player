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
from lisp.plugins.gst_backend.gi_repository import Gst
from lisp.plugins.gst_backend.gst_element import GstMediaElement

# Cycle-safe: video_compositor imports only gi_repository.
from lisp.plugins.gst_backend.video_compositor import (
    projection_pts,
    query_min_latency,
)

logger = logging.getLogger(__name__)

# The appsink releases each frame this long before its render time, so
# it can cross into the projection pipeline (glupload + mixer) before
# its deadline. It also bounds how much video sits queued in the
# appsrc: at most PUMP_LEAD is stranded by a pause/seek/stop.
PUMP_LEAD = 100 * Gst.MSECOND

# Re-query both pipelines' latency every N buffers (~1s at 30fps).
# Latency only changes when elements join/leave, so per-buffer queries
# would be wasted traversals.
LATENCY_REFRESH_BUFFERS = 30


def _compositor():
    """Fetch the VideoCompositor singleton lazily.

    Imported inside the call (not at module top) to avoid the
    gst_backend ↔ video_sink import cycle — video_sink is loaded via
    elements.load() from inside GstBackend.__init__, so a top-level
    import of gst_backend would re-enter a half-initialised module.
    """
    from lisp.plugins.gst_backend.gst_backend import GstBackend

    return GstBackend.video_compositor()


class VideoSink(GstMediaElement):
    ElementType = ElementType.Output
    MediaType = MediaType.AudioAndVideo
    Name = QT_TRANSLATE_NOOP("MediaElementName", "A/V System Out")

    def __init__(self, pipeline):
        super().__init__(pipeline)

        # Audio path unchanged: autoaudiosink in the cue pipeline,
        # removed in post_link() when the source has no audio.
        self.audio_sink = Gst.ElementFactory.make("autoaudiosink", None)
        self.pipeline.add(self.audio_sink)

        # Video path now ends in an appsink. Its new-sample callback
        # pumps each decoded buffer across the pipeline boundary into
        # this cue's appsrc on the persistent projection pipeline. The
        # appsink is bounded + drop-oldest so a stalled projection sink
        # can never wedge this cue's decode thread or its audio.
        # sync=True paces the pump to the clock: with sync=False the
        # cue decodes as fast as it can and parks seconds of future
        # frames in the appsrc, so video plays on through a pause.
        # ts-offset releases each frame PUMP_LEAD early so it still
        # makes its projection deadline.
        self.video_queue = Gst.ElementFactory.make("queue", None)
        self.video_appsink = Gst.ElementFactory.make("appsink", None)
        self.video_appsink.set_property("emit-signals", True)
        self.video_appsink.set_property("sync", True)
        self.video_appsink.set_property("ts-offset", -PUMP_LEAD)
        self.video_appsink.set_property("max-buffers", 2)
        self.video_appsink.set_property("drop", True)
        self.pipeline.add(self.video_queue)
        self.pipeline.add(self.video_appsink)
        self.video_queue.link(self.video_appsink)

        self._audio_removed = False
        self._video_removed = False

        # Projection registration + pump state.
        self._registration = None
        self._sample_handler = self.video_appsink.connect(
            "new-sample", self.__on_new_sample
        )

    def play(self):
        """Register with the compositor; the pump starts with the
        first sample once the pipeline reaches PLAYING."""
        compositor = _compositor()
        if compositor is None:
            return
        self._registration = compositor.register(self)

    def stop(self):
        self.__unregister()

    def eos(self):
        self.__unregister()

    def __unregister(self):
        # Drop our handle first so an in-flight new-sample on the
        # streaming thread stops pushing before the appsrc goes away.
        self._registration = None
        compositor = _compositor()
        if compositor is not None:
            compositor.unregister(self)

    def __on_new_sample(self, appsink):
        """Pull each sample and push the SAME buffer into this cue's
        appsrc on the projection pipeline, preserving PTS and offsetting
        it onto the projection running-time.

        Runs on a GStreamer streaming thread. Touches only GStreamer
        objects — never Qt. The offset formula (validated by the Phase-1
        spike, see projection_pts): out.pts = running_time +
        (cue_base − proj_base) + (L_cue − L_proj), with both pipelines
        on the compositor's shared clock. The latency term is cached on
        the registration and re-queried every LATENCY_REFRESH_BUFFERS.
        """
        sample = appsink.emit("pull-sample")
        if sample is None:
            return Gst.FlowReturn.OK

        reg = self._registration
        if reg is None or reg.appsrc is None:
            # Not registered (or torn down mid-stream) — drop.
            return Gst.FlowReturn.OK

        compositor = _compositor()
        if compositor is None or compositor.pipeline is None:
            return Gst.FlowReturn.OK

        buf = sample.get_buffer()
        if not reg.caps_set:
            reg.appsrc.set_property("caps", sample.get_caps())
            reg.caps_set = True

        if reg.latency_countdown <= 0:
            reg.latency_offset = query_min_latency(
                self.pipeline
            ) - query_min_latency(compositor.pipeline)
            reg.latency_countdown = LATENCY_REFRESH_BUFFERS
        reg.latency_countdown -= 1

        segment = sample.get_segment()
        running_time = segment.to_running_time(Gst.Format.TIME, buf.pts)
        out = buf.copy()
        out.pts = projection_pts(
            running_time,
            self.pipeline.get_base_time(),
            compositor.pipeline.get_base_time(),
            reg.latency_offset,
        )
        out.dts = Gst.CLOCK_TIME_NONE
        reg.appsrc.emit("push-buffer", out)
        return Gst.FlowReturn.OK

    def sink(self):
        """Audio sink -- connected by the linear chain."""
        return self.audio_sink

    def post_link(self, all_elements):
        """Wire the video branch and remove unused sinks.

        Builds the video chain by finding:
        1. The input element that provides video_src()
        2. Any plugin elements that provide video_sink()
           and video_src() (e.g. VideoAlpha)
        3. Linking: input -> plugins -> self.video_queue

        Also detects whether audio is present and removes
        the audio sink if not (prevents pipeline hang).
        """
        input_video_src = None
        video_plugins = []
        has_audio_src = False

        for element in all_elements:
            if element is self:
                continue
            # Find the video source (UriAvInput/ImageInput)
            if input_video_src is None:
                vs = element.video_src()
                if vs is not None and not hasattr(element, "video_sink"):
                    input_video_src = vs
            # Collect video plugins (have both video_sink
            # and video_src, e.g. VideoAlpha)
            if (
                hasattr(element, "video_sink")
                and element.video_sink() is not None
                and element.video_src() is not None
            ):
                video_plugins.append(element)
            if element.src() is not None:
                has_audio_src = True

        if input_video_src is not None:
            # Build chain: input -> plugins -> video_queue
            prev_src = input_video_src
            for plugin in video_plugins:
                if not prev_src.link(plugin.video_sink()):
                    logger.warning(
                        "VideoSink: failed to link %s",
                        type(plugin).__name__,
                    )
                prev_src = plugin.video_src()

            if not prev_src.link(self.video_queue):
                logger.warning(
                    "VideoSink: failed to link video source to video queue"
                )
        else:
            logger.debug("VideoSink: no video source found in pipeline")

        if not has_audio_src:
            logger.info("VideoSink: no audio source, removing audio sink")
            self.pipeline.remove(self.audio_sink)
            self._audio_removed = True

    def dispose(self):
        # Release the projection resources before teardown.
        self.__unregister()
        if self._sample_handler is not None:
            self.video_appsink.disconnect(self._sample_handler)
            self._sample_handler = None
        if not self._video_removed:
            self.pipeline.remove(self.video_queue)
            self.pipeline.remove(self.video_appsink)
            self._video_removed = True
        if not self._audio_removed:
            self.pipeline.remove(self.audio_sink)
            self._audio_removed = True
