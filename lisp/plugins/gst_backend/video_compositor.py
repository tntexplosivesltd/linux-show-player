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


# appsrc must declare a latency window or glvideomixer cannot configure
# latency once a live appsrc joins (default max-latency 0 < the
# background's 1-frame min → endless "clock problem" warnings).
APPSRC_MAX_LATENCY = Gst.SECOND


def query_min_latency(pipeline):
    """Min latency (ns) of `pipeline` from a latency query, 0 if the
    query fails (e.g. a non-live cue pipeline before PLAYING).

    Deliberately NOT Pipeline.get_latency(): that returns the user-set
    'latency' property (CLOCK_TIME_NONE when unset), not the latency
    the pipeline actually configured.
    """
    query = Gst.Query.new_latency()
    if not pipeline.query(query):
        return 0
    _live, min_latency, _max_latency = query.parse_latency()
    return min_latency


def projection_pts(running_time, cue_base, proj_base, latency_offset):
    """Map a cue buffer's running-time onto the projection pipeline.

    A sink renders at base_time + running_time + latency. Equating the
    cue's audio render time with the projection's video render time on
    the shared clock gives:

        pts = running_time + (cue_base − proj_base) + (L_cue − L_proj)

    `latency_offset` is (L_cue − L_proj). Validated by the Phase 1
    spike to within ±1 frame, no drift, across pause/resume.
    """
    return running_time + (cue_base - proj_base) + latency_offset


def fit_rect(src_w, src_h, par_n, par_d, dst_w, dst_h):
    """Aspect-preserving fit of a source into the canvas, centred.

    Returns (xpos, ypos, width, height) for the mixer pad. The mixer
    otherwise places each input at its native pixel size at (0,0); the
    old per-cue glimagesink scaled to the window instead, so this
    restores scale-to-fit (letterbox / pillarbox). `par_n/par_d` is the
    source pixel-aspect-ratio, so anamorphic video displays correctly.
    """
    if src_w <= 0 or src_h <= 0 or par_n <= 0 or par_d <= 0:
        return 0, 0, dst_w, dst_h
    display_w = src_w * par_n / par_d
    scale = min(dst_w / display_w, dst_h / src_h)
    width = min(dst_w, round(display_w * scale))
    height = min(dst_h, round(src_h * scale))
    return (dst_w - width) // 2, (dst_h - height) // 2, width, height


class Registration:
    """Per-cue projection resources: an appsrc (+ optional glupload)
    feeding one glvideomixer request pad above the black background."""

    def __init__(self):
        self.appsrc = None
        self.upload = None
        self.mix_pad = None
        self.caps_set = False
        # (L_cue − L_proj), cached by the pump; re-queried when the
        # countdown reaches 0 (0 = query on the next buffer).
        self.latency_offset = 0
        self.latency_countdown = 0


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

    def shutdown(self):
        """Stop the projection pipeline for good. Idempotent.

        Called from GstBackend.finalize(), which runs before the session
        and the Qt windows are torn down. Left PLAYING, the GL sinks
        keep rendering into dying X windows during interpreter exit
        (MESA BadDrawable errors, intermittent segfault).
        """
        if self.pipeline is None:
            return
        self.available = False
        self._registrations.clear()
        if self._sync_handler is not None:
            self.pipeline.get_bus().disconnect(self._sync_handler)
            self._sync_handler = None
        self.pipeline.set_state(Gst.State.NULL)
        self.pipeline = None

    def register(self, sink):
        """Attach a cue to the projection pipeline. Returns a
        Registration the caller's pump pushes buffers into, or None if
        the compositor is unavailable."""
        if not self.available:
            return None
        if id(sink) in self._registrations:
            return self._registrations[id(sink)]
        reg = self._attach(sink)
        if reg is not None:
            self._registrations[id(sink)] = reg
        return reg

    def unregister(self, sink):
        """Detach a cue. Idempotent — a stop() after eos() (or vice
        versa) must not error. Must not be called from a
        projection-pipeline streaming thread (see _detach)."""
        reg = self._registrations.pop(id(sink), None)
        if reg is not None:
            self._detach(reg)

    def is_registered(self, sink):
        return id(sink) in self._registrations

    def active_others(self, sink):
        """True if any cue OTHER than `sink` is currently registered —
        the single source of truth for VideoExclusiveManager."""
        return any(k != id(sink) for k in self._registrations)

    def fit_registration(self, reg, caps):
        """Scale-to-fit a cue's mixer pad once its caps are known.

        Called by the pump on the first sample (streaming thread);
        only touches GObject properties on the pad.
        """
        struct = caps.get_structure(0)
        ok_w, src_w = struct.get_int("width")
        ok_h, src_h = struct.get_int("height")
        ok_par, par_n, par_d = struct.get_fraction("pixel-aspect-ratio")
        if not ok_par:
            par_n, par_d = 1, 1
        if not (ok_w and ok_h):
            src_w = src_h = 0
        x, y, w, h = fit_rect(
            src_w, src_h, par_n, par_d, COMP_WIDTH, COMP_HEIGHT
        )
        reg.mix_pad.set_property("xpos", x)
        reg.mix_pad.set_property("ypos", y)
        reg.mix_pad.set_property("width", w)
        reg.mix_pad.set_property("height", h)

    def _attach(self, sink):
        """Live-add appsrc (+glupload on GL) + a mixer request pad."""
        plan = plan_pipeline()
        appsrc = Gst.ElementFactory.make("appsrc", None)
        appsrc.set_property("format", Gst.Format.TIME)
        appsrc.set_property("is-live", True)
        appsrc.set_property("do-timestamp", False)
        appsrc.set_property("min-latency", 0)
        appsrc.set_property("max-latency", APPSRC_MAX_LATENCY)
        self.pipeline.add(appsrc)

        reg = Registration()
        reg.appsrc = appsrc

        tail = appsrc
        if plan["upload"] is not None:
            upload = Gst.ElementFactory.make(plan["upload"], None)
            self.pipeline.add(upload)
            appsrc.link(upload)
            reg.upload = upload
            tail = upload

        tmpl = self.mixer.get_pad_template("sink_%u")
        mix_pad = self.mixer.request_pad(tmpl, None, None)
        mix_pad.set_property("zorder", self._next_zorder)
        self._next_zorder += 1
        reg.mix_pad = mix_pad

        tail.get_static_pad("src").link(mix_pad)
        appsrc.sync_state_with_parent()
        if reg.upload is not None:
            reg.upload.sync_state_with_parent()
        return reg

    def _detach(self, reg):
        """Live-remove a cue's branch. The mixer reverts to the black
        background = 'black on stop'.

        No pad probe: we own the only upstream element (the appsrc), so
        NULLing it stops its streaming task and flushes the branch;
        after that it is inert and can be unlinked and released.
        Doing this teardown inside a blocking pad-probe callback runs it
        on a streaming thread and deadlocks glvideomixer (Phase 1
        spike). Callers must therefore not be on a projection-pipeline
        streaming thread — VideoSink.stop() runs on cue worker threads
        and eos() on the cue's bus watch (main loop).
        """
        reg.appsrc.set_state(Gst.State.NULL)
        if reg.upload is not None:
            reg.upload.set_state(Gst.State.NULL)
        tail = reg.upload if reg.upload is not None else reg.appsrc
        tail.get_static_pad("src").unlink(reg.mix_pad)
        self.mixer.release_request_pad(reg.mix_pad)
        self.pipeline.remove(reg.appsrc)
        if reg.upload is not None:
            self.pipeline.remove(reg.upload)

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
        logger.debug(
            "VideoCompositor: prepare-window-handle from %s -> %s",
            message.src.get_name(), handle,
        )
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
