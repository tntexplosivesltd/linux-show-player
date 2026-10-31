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

from lisp.plugins.gst_backend.gi_repository import Gst

logger = logging.getLogger(__name__)

# Projection format. Kept modest; the later mixing spec may make this
# configurable. Background layer + both sinks negotiate against this.
COMP_WIDTH = 1920
COMP_HEIGHT = 1080
COMP_FPS = 30


def _have_factory(name):
    """True if a GStreamer element factory of this name exists."""
    return Gst.ElementFactory.find(name) is not None


def plan_pipeline():
    """Decide the projection pipeline's element factories.

    Primary path is GL (glupload → glvideomixer → glimagesink), which
    keeps compositing on the GPU and pairs natively with glimagesink.
    When GL is unavailable, fall back to a system-memory pipeline
    (compositor → xvimagesink/autovideosink) with no glupload on the
    inputs. Mirrors the factory-probe pattern in video_sink.py.
    """
    if (
        _have_factory("glupload")
        and _have_factory("glvideomixer")
        and _have_factory("glimagesink")
    ):
        return {
            "gl": True,
            "upload": "glupload",
            "mixer": "glvideomixer",
            "sink": "glimagesink",
        }

    if _have_factory("xvimagesink"):
        sink = "xvimagesink"
    else:
        sink = "autovideosink"
    return {"gl": False, "upload": None, "mixer": "compositor", "sink": sink}


class VideoCompositor:
    """Owns the single persistent projection pipeline.

    One always-PLAYING pipeline with a permanent black background
    layer, a glvideomixer, a tee, and two glimagesinks (projection +
    monitor). Because the mixer always produces frames the sinks are
    warm from process start and never cold-present — this is what
    dissolves the video→video first-transition flicker (Symptom B) and
    the image→video wedge (Symptom A): there is no per-cue sink and no
    hand-off. Both sinks' XIDs are bound ONCE, here, for the process
    lifetime.
    """

    def __init__(self, output_window, monitor_window):
        self._output_window = output_window
        self._monitor_window = monitor_window
        # Resolve the native handles now, on the constructing (main)
        # thread: winId() creates the native window, and the
        # prepare-window-handle callback that consumes them runs on a
        # GStreamer streaming thread where Qt must not be touched.
        self._output_handle = output_window.window_handle()
        self._monitor_handle = monitor_window.window_handle()
        self.pipeline = None
        self.mixer = None
        self._clock = None
        self._proj_sink = None
        self._mon_sink = None
        self._sync_handler = None
        # Monotonic zorder allocator: each registered cue sits above
        # the background (zorder 0) and above earlier registrations.
        self._next_zorder = 1
        # id(sink) -> registration handle; the exclusive-manager truth.
        self._registrations = {}

        self.available = self._build()
        if not self.available:
            logger.warning(
                "VideoCompositor: projection pipeline unavailable; "
                "video cues will play audio only"
            )

    def clock(self):
        """The shared clock every cue pipeline must adopt so pumped
        video stays in sync with the cue's own audio."""
        return self._clock

    def _build(self):
        plan = plan_pipeline()
        logger.debug("VideoCompositor: build plan %s", plan)

        self.pipeline = Gst.Pipeline.new("projection")
        # Single shared clock. Cue pipelines call pipeline.use_clock(
        # compositor.clock()); the pump (video_sink.py) maps cue
        # running-time onto projection running-time with
        # projection_pts(): base-time difference + latency difference
        # (this pipeline is live, ~86ms measured, so the latency term
        # matters — see the Phase 1 spike).
        self._clock = Gst.SystemClock.obtain()
        self.pipeline.use_clock(self._clock)

        bg = Gst.ElementFactory.make("videotestsrc", None)
        if bg is None:
            return False
        bg.set_property("pattern", 2)  # black
        bg.set_property("is-live", True)
        caps = Gst.ElementFactory.make("capsfilter", None)
        caps.set_property(
            "caps",
            Gst.Caps.from_string(
                f"video/x-raw,width={COMP_WIDTH},height={COMP_HEIGHT},"
                f"framerate={COMP_FPS}/1"
            ),
        )

        self.mixer = Gst.ElementFactory.make(plan["mixer"], "mix")
        tee = Gst.ElementFactory.make("tee", None)
        proj_q = Gst.ElementFactory.make("queue", None)
        self._proj_sink = Gst.ElementFactory.make(plan["sink"], None)
        # Monitor branch is leaky so a hidden/slow monitor sink can
        # never back-pressure the projection branch.
        mon_q = Gst.ElementFactory.make("queue", None)
        mon_q.set_property("leaky", 2)  # downstream (drop-oldest)
        self._mon_sink = Gst.ElementFactory.make(plan["sink"], None)

        bg_upload = None
        elems = [bg, caps]
        if plan["upload"] is not None:
            bg_upload = Gst.ElementFactory.make(plan["upload"], None)
            elems.append(bg_upload)
        elems += [
            self.mixer, tee, proj_q, self._proj_sink, mon_q, self._mon_sink
        ]
        for e in elems:
            if e is None:
                logger.warning("VideoCompositor: element creation failed")
                return False
            self.pipeline.add(e)

        # Link background chain into the mixer (lands on sink_0/zorder 0).
        if not bg.link(caps):
            return False
        if bg_upload is not None:
            if not caps.link(bg_upload) or not bg_upload.link(self.mixer):
                return False
        elif not caps.link(self.mixer):
            return False
        # mixer → tee → {projection, monitor}
        if not (
            self.mixer.link(tee)
            and tee.link(proj_q)
            and proj_q.link(self._proj_sink)
            and tee.link(mon_q)
            and mon_q.link(self._mon_sink)
        ):
            return False

        # The Wayland seam: the ONE place a Wayland port adapts. Today
        # this handles prepare-window-handle (X11 VideoOverlay); a
        # Wayland port extends it with need-context (share wl_display).
        bus = self.pipeline.get_bus()
        bus.enable_sync_message_emission()
        self._sync_handler = bus.connect(
            "sync-message::element", self.__on_sync_message
        )

        ret = self.pipeline.set_state(Gst.State.PLAYING)
        if ret == Gst.StateChangeReturn.FAILURE:
            logger.warning("VideoCompositor: set_state(PLAYING) FAILURE")
            self.pipeline.set_state(Gst.State.NULL)
            return False
        state_ret, *_ = self.pipeline.get_state(Gst.SECOND)
        if state_ret == Gst.StateChangeReturn.FAILURE:
            logger.warning("VideoCompositor: pipeline did not reach PLAYING")
            self.pipeline.set_state(Gst.State.NULL)
            return False
        return True

    def __on_sync_message(self, bus, message):
        """Bind each sink's XID once, for the process lifetime.

        THE WAYLAND SEAM. Runs on a GStreamer streaming thread before
        each sink opens its own window. Routes the projection sink to
        the output window and the monitor sink to the monitor window,
        using handles resolved on the main thread in __init__.
        Extend here with need-context handling for a Wayland port.
        """
        struct = message.get_structure()
        if struct is None or struct.get_name() != "prepare-window-handle":
            return
        handle = self.__owner_handle(message.src)
        if handle:
            message.src.set_window_handle(handle)

    def __owner_handle(self, element):
        """Walk up from element to the top-level sink it belongs to.
        Bin-based sinks post prepare-window-handle from an internal
        child, not the bin we stored."""
        while element is not None:
            if element == self._proj_sink:
                return self._output_handle
            if element == self._mon_sink:
                return self._monitor_handle
            element = element.get_parent()
        return None
