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
import time

from lisp.core.signal import Signal
from lisp.plugins.gst_backend.gi_repository import GLib, GstApp, Gst

logger = logging.getLogger(__name__)

# Default canvas, used until the output window's render area is known.
# The live canvas follows that area — see canvas_size_for() /
# set_canvas_size().
COMP_WIDTH = 1920
COMP_HEIGHT = 1080
COMP_FPS = 30
MIN_CANVAS = 64

# Handoff linger. A stopped/ended cue's mixer pad is kept (the mixer
# repeats its last frame) instead of being released at once, so a
# playlist's next cue — which only starts after this one ends, and needs
# a few hundred ms to preroll — takes over without a black gap. The old
# per-cue sinks got this for free (the stale frame stayed on the X
# surface); the shared canvas must do it explicitly.
# - No successor within LINGER_MS → release (standalone stop → black,
#   matching the old deferred clear).
# - Successor's first frame pushed → release HANDOFF_RELEASE_MS later
#   (> the pump's 100ms lead, so it is on screen first).
# - Successor's video ends before any frame (no video stream) → release
#   at once, see video_ended().
# - LINGER_CAP_MS is the backstop if a successor never shows a frame
#   (e.g. every frame dropped as mis-stamped).
LINGER_MS = 100
HANDOFF_RELEASE_MS = 250
LINGER_CAP_MS = 3000

# Recovery after a shared-pipeline failure: rebuild on the main loop
# after each delay in turn, then give up (audio only until restart). A
# failure more than REBUILD_STABLE_MS after a good rebuild is a new
# incident and starts the backoff over, so a long show cannot use up
# its retries on unrelated hiccups hours apart. A failure within
# REBUILD_STABLE_MS of a good rebuild is blamed on the cues registered
# at that moment: they stay audio only until they stop (quarantine), so
# one cue that breaks a shared element cannot use up every attempt.
REBUILD_BACKOFF_MS = (1000, 5000, 30000)
REBUILD_STABLE_MS = 60000

# The black background source is tiny; its mixer pad is scaled to the
# canvas, so resizing the canvas never renegotiates the source.
BG_SIZE = 16


# appsrc must declare a latency window or glvideomixer cannot configure
# latency once a live appsrc joins (default max-latency 0 < the
# background's 1-frame min → endless "clock problem" warnings).
APPSRC_MAX_LATENCY = Gst.SECOND

# Bound on each cue's appsrc queue, by time. The pump runs PUMP_LEAD
# (100ms) ahead, so a healthy queue holds ~100ms whatever the frame
# rate; a stalled projection would otherwise grow it without limit.
# Leaky-downstream drops the oldest frame past this. Not the default
# max-bytes (200kB is smaller than one 1080p frame).
APPSRC_MAX_QUEUE_TIME = 500 * Gst.MSECOND

# Backstop for frames whose PTS does not advance (a malformed file):
# they span ~0 time, so max-time never leaks them, and a stalled mixer
# would queue raw frames (~8MB each at 1080p RGBA) without limit. Far
# above a healthy queue (MAX_QUEUE_TIME at 60fps is 30 frames), so it
# only bites on broken timestamps; leaky-downstream drops the oldest.
APPSRC_MAX_QUEUE_BUFFERS = 64

# The projection pipeline's latency is cached for every cue's pump and
# re-queried after this long, or sooner once invalidated (a cue branch
# attached/detached, or a LATENCY message on the projection bus).
LATENCY_CACHE_NS = 250 * Gst.MSECOND


# Raw formats a cue may hand the projection: what both plans (glupload !
# glcolorconvert, and the software compositor) take on GStreamer 1.24
# and 1.28, restricted to 8-bit. Their templates advertise far more,
# but 10/16-bit uploads depend on the GL driver (v210 does not even
# link on 1.24), so anything else is converted by the cue's own
# videoconvert, on the cue's thread: a format the shared pipeline then
# fails to negotiate would hurt every cue. No size cap: videoscale
# meets one by changing the pixel aspect (8K -> anamorphic 4096x4096).
PROJECTION_FORMATS = (
    "I420", "YV12", "NV12", "NV21", "Y42B", "Y444", "YUY2", "UYVY",
    "AYUV", "RGBA", "BGRA", "RGBx", "BGRx", "ARGB", "ABGR", "xRGB",
    "xBGR", "RGB", "BGR",
)


def projection_input_caps():
    """Caps for a cue's appsink: system memory, PROJECTION_FORMATS."""
    formats = ", ".join(PROJECTION_FORMATS)
    return Gst.Caps.from_string(
        f"video/x-raw(memory:SystemMemory),format={{ {formats} }}"
    )


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


def canvas_size_for(width, height, dpr):
    """Canvas size for an output render area, in physical pixels.

    The canvas follows the projection window's render widget, so the
    canvas→window scale is 1:1 and a cue's fit-to-canvas is its
    fit-to-window: fullscreen on a projector that is the screen; in a
    windowed (single-screen) setup it is the window, not the screen
    (a screen-sized canvas letterboxed a 4:3 clip twice there).
    Rounded down to even dimensions for chroma-subsampled formats.
    Below MIN_CANVAS (e.g. a never-shown widget reporting 100x30) the
    default canvas is used until the real size arrives.
    """
    width = int(width * dpr) & ~1
    height = int(height * dpr) & ~1
    if width < MIN_CANVAS or height < MIN_CANVAS:
        return COMP_WIDTH, COMP_HEIGHT
    return width, height


def _canvas_caps(width, height, gl):
    # Name the exact memory type. (ANY) features negotiate once but
    # break the live re-pin on GStreamer 1.24: glvideomixer's internal
    # glcolorconvert cannot fixate them, the mixer goes not-negotiated
    # and the whole projection pipeline errors out (1.28 copes).
    memory = "memory:GLMemory" if gl else "memory:SystemMemory"
    return Gst.Caps.from_string(
        f"video/x-raw({memory}),width={width},height={height}"
    )


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
    """Per-cue projection resources: an appsrc (+ the GL upload bin)
    feeding one mixer request pad above the black background."""

    def __init__(self):
        self.appsrc = None
        self.upload = None
        self.mix_pad = None
        # The cue's current video caps (set by fit_registration): the
        # pump re-sets the appsrc caps and re-fits when they change,
        # and a canvas resize re-fits from them.
        self.caps = None
        # Set by frame_ready() once the pump pushed the first frame.
        self.frame_seen = False
        # Set by video_ended(): the branch ended without a frame, so a
        # predecessor's handoff must not wait for one.
        self.no_video = False
        # Pump state (cue streaming thread only).
        self.pushed = False  # at least one frame pushed
        self.cue_latency = 0  # L_cue, see VideoSink's refresh policy
        self.latency_buffers = 0  # buffers since registration
        self.push_warned = False  # a failed push was logged


def _have_factory(name):
    """True if a GStreamer element factory of this name exists."""
    return Gst.ElementFactory.find(name) is not None


def _make_upload(description):
    """One input's upload chain as a single bin with ghost pads, so a
    registration adds, NULLs and removes it as one element."""
    return Gst.parse_bin_from_description(description, True)


def _configure_appsrc(appsrc):
    """A cue's projection input: live, pre-timestamped by the pump,
    and bounded by time (APPSRC_MAX_QUEUE_TIME), with a buffer-count
    backstop (APPSRC_MAX_QUEUE_BUFFERS)."""
    appsrc.set_property("format", Gst.Format.TIME)
    appsrc.set_property("is-live", True)
    appsrc.set_property("do-timestamp", False)
    appsrc.set_property("min-latency", 0)
    appsrc.set_property("max-latency", APPSRC_MAX_LATENCY)
    appsrc.set_property("max-bytes", 0)
    appsrc.set_property("max-buffers", APPSRC_MAX_QUEUE_BUFFERS)
    appsrc.set_property("max-time", APPSRC_MAX_QUEUE_TIME)
    appsrc.set_property("leaky-type", GstApp.AppLeakyType.DOWNSTREAM)


def plan_pipeline():
    """Decide the projection pipeline's element factories.

    Primary path is GL (glupload ! glcolorconvert → glvideomixerelement
    → glimagesink), which keeps compositing on the GPU and pairs
    natively with glimagesink. When GL is unavailable, fall back to a
    system-memory pipeline (compositor → xvimagesink/autovideosink)
    with no upload on the inputs. Mirrors the factory-probe pattern in
    video_sink.py.

    The mixer is glvideomixerELEMENT, not the glvideomixer convenience
    bin: the bin's release_pad over-unrefs on GStreamer 1.24 (the
    first cue release frees the mixer; the next attach segfaults). The
    bin only adds a per-pad upload + convert, which "upload" provides.
    """
    if all(
        _have_factory(name)
        for name in (
            "glupload",
            "glcolorconvert",
            "glvideomixerelement",
            "glimagesink",
        )
    ):
        return {
            "gl": True,
            # A bin description (see _make_upload), one per input.
            "upload": "glupload ! glcolorconvert",
            "mixer": "glvideomixerelement",
            "sink": "glimagesink",
        }

    if _have_factory("xvimagesink"):
        sink = "xvimagesink"
    else:
        sink = "autovideosink"
    return {"gl": False, "upload": None, "mixer": "compositor", "sink": sink}


class VideoCompositor:
    """Owns the single persistent projection pipeline.

    One always-PLAYING pipeline: a permanent black background layer, a
    mixer (glvideomixerelement, or compositor without GL), a canvas
    capsfilter, a tee, and two video sinks (projection + monitor).
    Because the mixer always produces frames the sinks are warm from
    process start and never cold-present — this is what dissolves the
    video→video first-transition flicker (Symptom B) and the
    image→video wedge (Symptom A): there is no per-cue sink, so no
    sink/surface hand-off. Both sinks' XIDs are bound ONCE, here, for
    the process lifetime.

    Cues join as mixer inputs (register → appsrc branch, pumped by
    VideoSink) and leave after a short linger, so a playlist's next cue
    takes over the canvas without a black gap (see LINGER_*). Threading
    rules: docs/threading.md, "VideoCompositor — the projection pump".
    """

    def __init__(
        self,
        output_window,
        monitor_window,
        canvas_size=(COMP_WIDTH, COMP_HEIGHT),
    ):
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
        self._canvas = tuple(canvas_size)
        self._canvas_filter = None
        self._bg_pad = None
        # GL vs system-memory path; set from the build plan.
        self._gl = True
        # Monotonic zorder allocator: each registered cue sits above
        # the background (zorder 0) and above earlier registrations.
        self._next_zorder = 1
        # sink -> registration handle (render branches only; video
        # exclusivity is tracked by video_exclusive.ActiveVideoSinks).
        # Keyed on the sink object itself (not id()): an id can be
        # reused by a new object once the old one is collected.
        self._registrations = {}
        # Unregistered but still on screen (handoff linger).
        self._lingering = []
        # Sinks blamed for a repeat shared failure (see _fail): no
        # branch until they unregister (their cue stops).
        self._quarantined = set()
        # Pending linger/handoff GLib timeout ids, removed at shutdown.
        self._timers = set()
        # Guards the collections above: touched from the main loop,
        # cue worker threads (stop) and the pump's streaming thread.
        self._lock = threading.Lock()
        # Serialises a fit (read the canvas, write the four pad
        # properties) against a canvas change: the pump fits a first
        # frame on its streaming thread while the main thread resizes.
        # Separate from _lock, so a slow pad write never holds up the
        # registration bookkeeping.
        self._fit_lock = threading.Lock()
        # Thread-safe; callbacks run on the main loop, which is where
        # _detach must run (never on a projection streaming thread).
        self._schedule = GLib.timeout_add
        self._unschedule = GLib.source_remove
        # The build plan (factories, GL or not), fixed for the process.
        self._plan = None
        self._bus_handler = None
        # Cached projection min latency (ns) and when it was queried;
        # None = re-query on the next latency() call.
        self._latency = None
        self._latency_at = 0
        # Emitted on the main loop. failed: a runtime error killed the
        # projection pipeline and a rebuild is scheduled. restored: a
        # rebuild succeeded; registrations were dropped with the old
        # pipeline, so active cues must re-register. gave_up: no
        # rebuild is left to try (the last one failed, or the pipeline
        # failed again with every attempt used) and video stays off;
        # a failure emits failed or gave_up, never both. GstBackend
        # handles all three.
        self.failed = Signal()
        self.restored = Signal()
        self.gave_up = Signal()
        # shutdown() was called: never rebuild again.
        self._closed = False
        # Rebuilds scheduled in the current failure streak, and when
        # the last one succeeded (time.monotonic()).
        self._rebuild_attempt = 0
        self._rebuilt_at = None

        self.available = self._try_build()
        if not self.available:
            logger.warning(
                "VideoCompositor: projection pipeline unavailable; "
                "video cues will play audio only"
            )
            # Drop the half-built pipeline (_build may fail after
            # creating it) so nothing later mistakes it for a live one.
            self.shutdown()

    def clock(self):
        """The shared clock every cue pipeline must adopt so pumped
        video stays in sync with the cue's own audio."""
        return self._clock

    def canvas_size(self):
        return self._canvas

    def latency(self):
        """The projection pipeline's min latency (ns), shared by every
        cue's pump. Cached so the pumps do not each walk the GL
        pipeline; re-queried every LATENCY_CACHE_NS or after an
        invalidation. Callable from any thread; 0 when shut down."""
        pipeline = self.pipeline
        if pipeline is None:
            return 0
        now = time.monotonic_ns()
        with self._lock:
            if (
                self._latency is not None
                and now - self._latency_at < LATENCY_CACHE_NS
            ):
                return self._latency
        latency = query_min_latency(pipeline)
        with self._lock:
            self._latency = latency
            self._latency_at = now
        return latency

    def _invalidate_latency(self):
        # Lock-free on purpose: a single attribute store is atomic, and
        # _detach (which calls this) can run under _lock (a failed
        # _attach inside register()); _lock is not re-entrant.
        self._latency = None

    def set_canvas_size(self, width, height):
        """Resize the canvas live (main thread). No-op when unchanged.

        Re-pins the post-mixer canvas caps, rescales the background
        pad, and re-fits every cue whose caps are already known.
        """
        with self._fit_lock:
            if (width, height) == self._canvas:
                return
            # Under the fit lock: a pump fit either finished before
            # this (its reg.caps is set, so it is re-fitted below) or
            # reads the new canvas.
            self._canvas = (width, height)
        if not self.available or self.pipeline is None:
            return
        logger.debug("VideoCompositor: canvas -> %dx%d", width, height)
        self._canvas_filter.set_property(
            "caps", _canvas_caps(width, height, self._gl)
        )
        self._bg_pad.set_property("width", width)
        self._bg_pad.set_property("height", height)
        with self._lock:
            visible = list(self._registrations.values()) + self._lingering
        for reg in visible:
            if reg.caps is not None:
                self._apply_fit(reg)

    def shutdown(self):
        """Stop the projection pipeline for good. Idempotent.

        Called from GstBackend.finalize(), which runs before the session
        and the Qt windows are torn down. Left PLAYING, the GL sinks
        keep rendering into dying X windows during interpreter exit
        (MESA BadDrawable errors, intermittent segfault). Also cancels
        a pending rebuild.
        """
        self._closed = True
        with self._lock:
            self._quarantined.clear()  # hold no sinks past finalize
        self._teardown()

    def _teardown(self):
        """Stop and drop the current pipeline, its registrations and
        every pending timer (linger, release, rebuild). Idempotent."""
        self.available = False
        with self._lock:
            self._registrations.clear()
            self._lingering.clear()
            timers = list(self._timers)
            self._timers.clear()
        for timer in timers:
            self._unschedule(timer)
        self._invalidate_latency()
        if self.pipeline is None:
            return
        bus = self.pipeline.get_bus()
        if self._sync_handler is not None:
            bus.disconnect(self._sync_handler)
            self._sync_handler = None
        if self._bus_handler is not None:
            bus.disconnect(self._bus_handler)
            bus.remove_signal_watch()
            self._bus_handler = None
        self.pipeline.set_state(Gst.State.NULL)
        self.pipeline = None

    def register(self, sink):
        """Attach a cue to the projection pipeline. Returns a
        Registration the caller's pump pushes buffers into, or None if
        the compositor is unavailable or the attach failed."""
        if not self.available:
            return None
        with self._lock:
            if sink in self._quarantined:
                return None
            reg = self._registrations.get(sink)
            if reg is not None:
                return reg
            reg = self._attach(sink)
            if reg is not None:
                self._registrations[sink] = reg
        return reg

    def unregister(self, sink):
        """Stop treating a cue as active. Idempotent — a stop() after
        eos() (or vice versa) must not error.

        The cue's pad lingers (last frame stays up) until a successor's
        first frame is on screen or LINGER_MS passes with none — see the
        LINGER_* constants.
        """
        with self._lock:
            # The cue stopped: its next play gets a fresh chance.
            self._quarantined.discard(sink)
            reg = self._registrations.pop(sink, None)
            if reg is None:
                return
            self._lingering.append(reg)
        self._schedule_once(LINGER_MS, self._on_linger_timeout, reg)
        self._schedule_once(LINGER_CAP_MS, self._release, reg)

    def frame_ready(self, reg):
        """Pump hook (streaming thread): `reg` pushed its first frame.
        Hand off from every lingering predecessor once it is shown.
        A reg that was already unregistered (its stop raced the first
        frame) is lingering itself and must not release its peers."""
        with self._lock:
            if not any(r is reg for r in self._registrations.values()):
                return
            reg.frame_seen = True
            lingering = list(self._lingering)
        if lingering:
            self._schedule_once(
                HANDOFF_RELEASE_MS, self._release, *lingering
            )

    def video_ended(self, reg):
        """Pump hook (streaming thread): `reg`'s video branch hit EOS.
        If it never pushed a frame it never will (e.g. a file with no
        video stream), so lingering predecessors must not wait for one:
        once no active registration is still due a frame, they are
        released now (black) instead of at LINGER_CAP_MS."""
        with self._lock:
            if not any(r is reg for r in self._registrations.values()):
                return
            if reg.frame_seen:
                return  # a normal end; the handoff already happened
            reg.no_video = True
            waiting = [
                r for r in self._registrations.values() if not r.no_video
            ]
            lingering = list(self._lingering)
        if lingering and not waiting:
            self._schedule_once(0, self._release, *lingering)

    def is_registered(self, sink):
        with self._lock:
            return sink in self._registrations

    def _schedule_once(self, ms, fn, *args):
        """One-shot main-loop timer whose id is tracked, so shutdown()
        can cancel what is still pending. Callable from any thread."""
        timer = []

        def fire():
            with self._lock:
                if timer:
                    self._timers.discard(timer[0])
            fn(*args)
            return False

        with self._lock:
            timer.append(self._schedule(ms, fire))
            self._timers.add(timer[0])

    def _on_linger_timeout(self, reg):
        """Main loop. With no successor, release now (black on stop).
        With a successor, hand off once its first frame is up."""
        with self._lock:
            # A registration that ended without video shows nothing.
            active = [
                r for r in self._registrations.values() if not r.no_video
            ]
        if not active:
            self._release(reg)
        elif all(r.frame_seen for r in active):
            # Successor already showing (its frame_ready came first).
            self._schedule_once(HANDOFF_RELEASE_MS, self._release, reg)
        # else: the successor's frame_ready() releases us (cap: backstop)
        return False

    def _release(self, *regs):
        """Main loop. Detach lingering registrations; idempotent and a
        no-op after shutdown(). Returns False (one-shot GLib timeout)."""
        to_detach = []
        with self._lock:
            if self.pipeline is None:
                return False
            for reg in regs:
                if reg in self._lingering:
                    self._lingering.remove(reg)
                    to_detach.append(reg)
        for reg in to_detach:
            self._detach(reg)
        return False

    def fit_registration(self, reg, caps):
        """Scale-to-fit a cue's mixer pad once its caps are known.

        Called by the pump on the first sample (streaming thread);
        only touches GObject properties on the pad. The caps are kept
        on the registration so set_canvas_size() can re-fit it.
        """
        reg.caps = caps
        self._apply_fit(reg)

    def _apply_fit(self, reg):
        struct = reg.caps.get_structure(0)
        ok_w, src_w = struct.get_int("width")
        ok_h, src_h = struct.get_int("height")
        ok_par, par_n, par_d = struct.get_fraction("pixel-aspect-ratio")
        if not ok_par:
            par_n, par_d = 1, 1
        if not (ok_w and ok_h):
            src_w = src_h = 0
        with self._fit_lock:
            x, y, w, h = fit_rect(
                src_w, src_h, par_n, par_d, *self._canvas
            )
            reg.mix_pad.set_property("xpos", x)
            reg.mix_pad.set_property("ypos", y)
            reg.mix_pad.set_property("width", w)
            reg.mix_pad.set_property("height", h)

    def _attach(self, sink):
        """Live-add appsrc (+ the upload bin on GL) + a mixer request
        pad. Returns the Registration, or None on failure.

        Every step is checked. On failure whatever was already added is
        removed again, so a cue that cannot attach plays audio only
        instead of aborting its start or leaving orphan elements (and a
        dangling mixer pad) in the projection pipeline.
        """
        reg = Registration()
        try:
            appsrc = Gst.ElementFactory.make("appsrc", None)
            if appsrc is None:
                raise RuntimeError("cannot create appsrc")
            _configure_appsrc(appsrc)
            self.pipeline.add(appsrc)
            reg.appsrc = appsrc

            tail = appsrc
            if self._plan["upload"] is not None:
                reg.upload = _make_upload(self._plan["upload"])
                self.pipeline.add(reg.upload)
                if not appsrc.link(reg.upload):
                    raise RuntimeError("cannot link appsrc to upload")
                tail = reg.upload

            tmpl = self.mixer.get_pad_template("sink_%u")
            reg.mix_pad = self.mixer.request_pad(tmpl, None, None)
            if reg.mix_pad is None:
                raise RuntimeError("mixer refused a sink pad")
            reg.mix_pad.set_property("zorder", self._next_zorder)
            self._next_zorder += 1

            result = tail.get_static_pad("src").link(reg.mix_pad)
            if result != Gst.PadLinkReturn.OK:
                raise RuntimeError(f"cannot link to mixer: {result}")
            # Downstream first, so the live appsrc never pushes into a
            # still-NULL (flushing) upload bin.
            for element in (reg.upload, appsrc):
                if element is not None and not element.sync_state_with_parent():
                    raise RuntimeError(f"cannot start {element.get_name()}")
        except Exception:
            logger.exception("VideoCompositor: attach failed")
            self._detach(reg)
            return None
        self._invalidate_latency()
        return reg

    def _detach(self, reg):
        """Remove a cue's branch (or what exists of it, after a failed
        attach). The mixer reverts to the black background = 'black on
        stop'. Every step runs even if an earlier one fails, so one
        GStreamer hiccup cannot strand the rest in the pipeline.

        No pad probe: we own the only upstream element (the appsrc), so
        NULLing it stops its streaming task and flushes the branch;
        after that it is inert and can be unlinked and released.
        Doing this teardown inside a blocking pad-probe callback runs it
        on a streaming thread and deadlocks glvideomixer (Phase 1
        spike). Callers must therefore not be on a projection-pipeline
        streaming thread: releases run from GLib timeouts on the main
        loop (see unregister), and a failed attach is undone on the
        registering thread before any data flowed.
        """
        tail = reg.upload if reg.upload is not None else reg.appsrc
        steps = []
        if reg.appsrc is not None:
            steps.append(lambda: reg.appsrc.set_state(Gst.State.NULL))
        if reg.upload is not None:
            steps.append(lambda: reg.upload.set_state(Gst.State.NULL))
        if reg.mix_pad is not None:
            if tail is not None:
                steps.append(
                    lambda: tail.get_static_pad("src").unlink(reg.mix_pad)
                )
            steps.append(lambda: self.mixer.release_request_pad(reg.mix_pad))
        if reg.appsrc is not None:
            steps.append(lambda: self.pipeline.remove(reg.appsrc))
        if reg.upload is not None:
            steps.append(lambda: self.pipeline.remove(reg.upload))
        for step in steps:
            try:
                step()
            except Exception:
                logger.exception("VideoCompositor: detach step failed")
        self._invalidate_latency()

    def _build(self):
        plan = plan_pipeline()
        logger.debug("VideoCompositor: build plan %s", plan)
        self._plan = plan
        self._gl = plan["gl"]

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
        caps = Gst.ElementFactory.make("capsfilter", None)
        self.mixer = Gst.ElementFactory.make(plan["mixer"], "mix")
        # Pins the mixer's output to the canvas size; set_canvas_size()
        # re-pins it live.
        self._canvas_filter = Gst.ElementFactory.make("capsfilter", None)
        tee = Gst.ElementFactory.make("tee", None)
        proj_q = Gst.ElementFactory.make("queue", None)
        self._proj_sink = Gst.ElementFactory.make(plan["sink"], None)
        mon_q = Gst.ElementFactory.make("queue", None)
        self._mon_sink = Gst.ElementFactory.make(plan["sink"], None)
        created = (bg, caps, self.mixer, self._canvas_filter, tee,
                   proj_q, self._proj_sink, mon_q, self._mon_sink)
        if any(e is None for e in created):
            # Before any set_property on them.
            logger.warning("VideoCompositor: element creation failed")
            return False

        bg.set_property("pattern", 2)  # black
        bg.set_property("is-live", True)
        caps.set_property(
            "caps",
            Gst.Caps.from_string(
                f"video/x-raw,width={BG_SIZE},height={BG_SIZE},"
                f"framerate={COMP_FPS}/1"
            ),
        )

        self._canvas_filter.set_property(
            "caps", _canvas_caps(*self._canvas, self._gl)
        )
        # Monitor branch is leaky so a hidden/slow monitor sink can
        # never back-pressure the projection branch.
        mon_q.set_property("leaky", 2)  # downstream (drop-oldest)

        bg_upload = None
        elems = [bg, caps]
        if plan["upload"] is not None:
            bg_upload = _make_upload(plan["upload"])
            elems.append(bg_upload)
        elems += [
            self.mixer,
            self._canvas_filter,
            tee,
            proj_q,
            self._proj_sink,
            mon_q,
            self._mon_sink,
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
        bg_tail = bg_upload if bg_upload is not None else caps
        self._bg_pad = bg_tail.get_static_pad("src").get_peer()
        self._bg_pad.set_property("width", self._canvas[0])
        self._bg_pad.set_property("height", self._canvas[1])
        # mixer → canvas filter → tee → {projection, monitor}
        if not (
            self.mixer.link(self._canvas_filter)
            and self._canvas_filter.link(tee)
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
        # Async watch (dispatched on the main loop) for runtime errors.
        bus.add_signal_watch()
        self._bus_handler = bus.connect("message", self._on_bus_message)

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

    def _on_bus_message(self, bus, message):
        """Main loop. A WARNING is logged. An ERROR from one cue's
        branch (its appsrc or upload bin) drops just that cue's video;
        any other ERROR means the shared pipeline is gone: it is torn
        down (every video cue plays audio only) and rebuilt with
        backoff (see REBUILD_BACKOFF_MS)."""
        if message.type == Gst.MessageType.LATENCY:
            # The pipeline recalculates its latency; re-query it.
            self._invalidate_latency()
        elif message.type == Gst.MessageType.WARNING:
            warning, debug = message.parse_warning()
            logger.warning(
                "VideoCompositor: %s (%s)", warning.message, debug
            )
        elif message.type == Gst.MessageType.ERROR:
            error, debug = message.parse_error()
            reg = self._branch_of(message.src)
            if reg is not None:
                logger.error(
                    "VideoCompositor: cue video branch failed, dropping "
                    "it: %s (%s)", error.message, debug,
                )
                self._drop_branch(reg)
                return
            if not self._in_pipeline(message.src):
                # A branch already detached (dropped or released). One
                # failing branch posts several ERRORs (the upload
                # child's, then the appsrc's "Internal data stream
                # error") before the first is handled here; the late
                # ones are not the shared pipeline failing.
                logger.debug(
                    "VideoCompositor: ignoring error from a detached "
                    "branch: %s (%s)", error.message, debug,
                )
                return
            logger.error(
                "VideoCompositor: projection pipeline failed: %s (%s)",
                error.message, debug,
            )
            self._fail()

    def _try_build(self):
        """_build(), with an exception treated as a failed build (e.g.
        a GLib.Error from parse_bin_from_description): it must degrade
        to audio only, never take the backend down with it."""
        try:
            return self._build()
        except Exception:
            logger.exception("VideoCompositor: projection build failed")
            return False

    def _fail(self):
        """Main loop. The shared pipeline died: drop it (every cue goes
        audio only for now) and schedule a rebuild.

        Failing again soon after a good rebuild points at a cue rather
        than a GL/driver hiccup: most likely one re-attached by the
        rebuild, whose input breaks a shared element (an error the
        mixer or sink posts, so not caught as a branch error). The cues
        registered now are quarantined, so the next rebuild comes up
        without them instead of failing on them again."""
        recent = (
            self._rebuilt_at is not None
            and time.monotonic() - self._rebuilt_at
            <= REBUILD_STABLE_MS / 1000
        )
        if recent:
            with self._lock:
                suspects = set(self._registrations)
                self._quarantined |= suspects
            if suspects:
                logger.warning(
                    "VideoCompositor: projection failed again soon after "
                    "a rebuild; %d video cue(s) will play audio only "
                    "until stopped", len(suspects),
                )
        self._teardown()
        if self._closed:
            return
        if self._rebuilt_at is not None and not recent:
            # Long after the last good rebuild: a new incident.
            self._rebuild_attempt = 0
        if self._out_of_attempts():
            # No restart is coming: announce only that.
            self._give_up()
            return
        self.failed.emit()
        self._schedule_rebuild()

    def _out_of_attempts(self):
        return self._rebuild_attempt >= len(REBUILD_BACKOFF_MS)

    def _give_up(self):
        logger.error(
            "VideoCompositor: projection did not come back after "
            "%d attempts; video cues will play audio only",
            self._rebuild_attempt,
        )
        self.gave_up.emit()

    def _schedule_rebuild(self):
        if self._out_of_attempts():
            self._give_up()
            return
        delay = REBUILD_BACKOFF_MS[self._rebuild_attempt]
        self._rebuild_attempt += 1
        logger.info(
            "VideoCompositor: rebuilding the projection in %d ms "
            "(attempt %d)", delay, self._rebuild_attempt,
        )
        self._schedule_once(delay, self._rebuild)

    def _rebuild(self):
        """Main loop (GLib timeout). Build a fresh pipeline; on success
        emit restored (active cues re-register), otherwise back off
        again. Runs on the main loop for the same reason teardown
        does: never on a projection streaming thread."""
        if self._closed:
            return False
        if self._try_build():
            self.available = True
            self._rebuilt_at = time.monotonic()
            logger.info("VideoCompositor: projection restored")
            self.restored.emit()
        else:
            self._teardown()  # drop the half-built pipeline
            self._schedule_rebuild()
        return False

    def _branch_of(self, element):
        """The registration whose appsrc/upload bin owns `element`."""
        with self._lock:
            regs = list(self._registrations.values()) + self._lingering
        while element is not None:
            for reg in regs:
                if element == reg.appsrc or element == reg.upload:
                    return reg
            element = element.get_parent()
        return None

    def _in_pipeline(self, element):
        """True if `element` is (inside) the live projection pipeline.
        _detach removes a branch's appsrc/upload bin from the pipeline,
        which unparents them, so their ancestry no longer reaches it.

        Structural on purpose, not a WeakSet of detached elements: that
        would hold PyGObject wrappers, and a message can outlive the
        wrapper (it keeps the GObject alive, then gets a new one)."""
        pipeline = self.pipeline
        while element is not None:
            if element == pipeline:
                return True
            element = element.get_parent()
        return False

    def _drop_branch(self, reg):
        """Main loop. Forget and detach one failed registration. Its
        cue keeps playing audio; its pump's pushes now return FLUSHING
        and are dropped."""
        with self._lock:
            for sink, other in list(self._registrations.items()):
                if other is reg:
                    del self._registrations[sink]
            if reg in self._lingering:
                self._lingering.remove(reg)
        self._detach(reg)

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
