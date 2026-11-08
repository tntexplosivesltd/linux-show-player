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
    APPSRC_MAX_QUEUE_TIME,
    projection_input_caps,
    projection_pts,
    query_min_latency,
)


def cue_latency_due(buffers_seen):
    """True when the pump should re-query the cue pipeline's latency
    for its `buffers_seen`-th buffer (0-based) — see
    LATENCY_WARMUP_BUFFERS."""
    return (
        buffers_seen < LATENCY_WARMUP_BUFFERS
        or buffers_seen % LATENCY_REFRESH_BUFFERS == 0
    )

logger = logging.getLogger(__name__)

# The appsink releases each frame this long before its render time, so
# it can cross into the projection pipeline (glupload + mixer) before
# its deadline. It also bounds how much video sits queued in the
# appsrc: at most PUMP_LEAD is stranded by a pause/seek/stop.
PUMP_LEAD = 100 * Gst.MSECOND

# The cue pipeline's latency is re-queried on every buffer for the
# first LATENCY_WARMUP_BUFFERS (~2s at 30fps), while the pipeline may
# still be settling, then every LATENCY_REFRESH_BUFFERS (~1s). (Measured
# on the host it is already stable from the first buffer; the first
# A/V pair's extra ~50ms in the av_sync E2E is not from this term.)
# The projection's latency comes from the compositor's shared cache
# (VideoCompositor.latency()).
LATENCY_WARMUP_BUFFERS = 60

# A timed frame stamped further than this ahead of the projection's
# clock is dropped (see the pump). Same bound as the appsrc queue.
MAX_AHEAD = APPSRC_MAX_QUEUE_TIME
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
        # Only formats the projection takes: the cue's videoconvert
        # converts anything else here, not in the shared pipeline.
        self.video_appsink.set_property("caps", projection_input_caps())
        self.pipeline.add(self.video_queue)
        self.pipeline.add(self.video_appsink)
        self.video_queue.link(self.video_appsink)

        self._audio_removed = False
        self._video_removed = False

        # Projection registration + pump state.
        self._registration = None
        # Cached in play() so the pump never does the lazy import on
        # its streaming thread.
        self._compositor = None
        self._sample_handler = self.video_appsink.connect(
            "new-sample", self.__on_new_sample
        )
        # A paused seek (or pause()'s own flush-seek) re-prerolls the
        # cue: the frame arrives as a preroll, not a sample.
        self._preroll_handler = self.video_appsink.connect(
            "new-preroll", self.__on_new_preroll
        )

    def play(self):
        """Register with the compositor; the pump starts with the
        first frame (the preroll, then samples once PLAYING)."""
        self._compositor = _compositor()
        if self._compositor is None:
            return
        self._registration = self._compositor.register(self)

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
        """Streaming thread (PLAYING): pump the next timed frame."""
        sample = appsink.pull_sample()
        if sample is not None:
            self.__pump(sample, preroll=False)
        return Gst.FlowReturn.OK

    def __on_new_preroll(self, appsink):
        """Streaming thread (PAUSED/preroll): show this frame now."""
        sample = appsink.pull_preroll()
        if sample is not None:
            self.__pump(sample, preroll=True)
        return Gst.FlowReturn.OK

    def __pump(self, sample, preroll):
        """Copy a cue frame into this cue's appsrc on the projection
        pipeline, re-timestamped onto the projection's running time.

        Runs on a cue streaming thread. Touches only GStreamer objects —
        never Qt. A timed sample is mapped with projection_pts():
        out.pts = running_time + (cue_base − proj_base) +
        (L_cue − L_proj), both pipelines on the compositor's shared
        clock. A preroll frame has no meaningful running time (the cue
        is paused), so it is stamped "now" on the projection.
        """
        reg = self._registration
        compositor = self._compositor
        if reg is None or compositor is None:
            # Not registered (prearm preroll, or torn down) — drop.
            return
        # Read once: shutdown() may clear it concurrently.
        projection = compositor.pipeline
        if projection is None:
            return
        buf = sample.get_buffer()
        if buf is None:
            return

        caps = sample.get_caps()
        if caps is not None and (
            reg.caps is None or not caps.is_equal(reg.caps)
        ):
            # First frame, or a mid-stream change (resolution/aspect).
            reg.appsrc.set_property("caps", caps)
            compositor.fit_registration(reg, caps)

        now = compositor.clock().get_time() - projection.get_base_time()
        if preroll:
            if not reg.pushed:
                # The initial preroll of a starting cue: the same frame
                # arrives as the first timed sample a moment later.
                # Pushing it early too leaves the cue's first timed
                # sample mis-stamped seconds ahead, which parks the
                # mixer pad and freezes the video (host E2E).
                return
            # Re-preroll = the cue flushed (a seek, or pause()'s own
            # flush-seek). Drop the up-to-PUMP_LEAD of frames queued
            # for the old position, then show this frame now.
            reg.appsrc.send_event(Gst.Event.new_flush_start())
            reg.appsrc.send_event(Gst.Event.new_flush_stop(False))
            pts = now
        else:
            running_time = sample.get_segment().to_running_time(
                Gst.Format.TIME, buf.pts
            )
            if running_time == Gst.CLOCK_TIME_NONE:
                # Outside the segment (or no PTS): nothing to map.
                return
            if cue_latency_due(reg.latency_buffers):
                reg.cue_latency = query_min_latency(self.pipeline)
            reg.latency_buffers += 1
            pts = projection_pts(
                running_time,
                self.pipeline.get_base_time(),
                projection.get_base_time(),
                reg.cue_latency - compositor.latency(),
            )
            if pts > now + MAX_AHEAD:
                # A healthy frame is at most ~PUMP_LEAD ahead. One
                # stamped further out (the first sample after a pulled
                # preroll can carry a stale mapping) would park the
                # mixer pad until then and freeze everything behind it.
                logger.debug(
                    "VideoSink: dropping frame %.0fms ahead",
                    (pts - now) / Gst.MSECOND,
                )
                return

        out = buf.copy()
        out.pts = pts
        out.dts = Gst.CLOCK_TIME_NONE
        ret = reg.appsrc.push_buffer(out)
        if ret != Gst.FlowReturn.OK and not reg.push_warned:
            # FLUSHING is expected for a branch the compositor dropped.
            reg.push_warned = True
            logger.warning("VideoSink: projection push returned %s", ret)
        if not reg.pushed:
            reg.pushed = True
            # Lets a lingering predecessor hand off (no black gap).
            compositor.frame_ready(reg)

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
        if self._preroll_handler is not None:
            self.video_appsink.disconnect(self._preroll_handler)
            self._preroll_handler = None
        if not self._video_removed:
            self.pipeline.remove(self.video_queue)
            self.pipeline.remove(self.video_appsink)
            self._video_removed = True
        if not self._audio_removed:
            self.pipeline.remove(self.audio_sink)
            self._audio_removed = True
