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
from lisp.core.signal import Connection, Signal
from lisp.plugins.gst_backend.gi_repository import Gst
from lisp.plugins.gst_backend.gst_element import GstMediaElement

logger = logging.getLogger(__name__)

# Preferred video sink elements in priority order.
# glimagesink: OpenGL-based, good quality, works on X11 + XWayland.
# xvimagesink: X11 XVideo extension, lower overhead, X11 only.
_VIDEO_SINK_FACTORIES = ("glimagesink", "xvimagesink")

# How long stop() waits before actually clearing the projection
# surface.  Playlist auto-advance and similar back-to-back triggers
# call VideoSink.play() within one Qt event-loop tick (sub-ms in
# practice); any value comfortably above that window produces seamless
# transitions while staying below the threshold of operator
# perception when no follow-up cue arrives.  Tuned conservatively.
_DEFERRED_CLEAR_MS = 100


def _create_video_sink():
    """Create the best available video sink with VideoOverlay support.

    Falls back through _VIDEO_SINK_FACTORIES in order.  If none are
    available, returns autovideosink (no overlay, opens own window).
    """
    for name in _VIDEO_SINK_FACTORIES:
        element = Gst.ElementFactory.make(name, None)
        if element is not None:
            logger.debug("VideoSink: using %s", name)
            return element

    logger.warning(
        "VideoSink: no overlay-capable sink found, "
        "falling back to autovideosink"
    )
    return Gst.ElementFactory.make("autovideosink", None)


class VideoSink(GstMediaElement):
    ElementType = ElementType.Output
    MediaType = MediaType.AudioAndVideo
    Name = QT_TRANSLATE_NOOP("MediaElementName", "A/V System Out")

    # Track the last VideoSink that rendered, so we can release
    # its GL context before a different sink takes over.
    _previous_sink = None

    # Class-level coordination for the deferred clear.  stop() sets
    # _pending_clear = True and schedules a delayed clear; any
    # VideoSink.play() within the defer window resets the flag,
    # cancelling the clear.  This produces QLab-style "clear on stop"
    # for standalone cues while keeping playlist transitions seamless
    # (because auto-advance fires play() within a Qt tick).
    _pending_clear = False

    def __init__(self, pipeline):
        super().__init__(pipeline)

        # Audio path: same as the existing AutoSink
        self.audio_sink = Gst.ElementFactory.make(
            "autoaudiosink", None
        )
        self.pipeline.add(self.audio_sink)

        # Video path: queue -> tee -> projection + monitor branches.
        # The tee duplicates video buffers so both the projection
        # window and the operator's monitor window can render
        # independently.
        self.video_queue = Gst.ElementFactory.make("queue", None)
        self.video_tee = Gst.ElementFactory.make("tee", None)

        # Projection branch
        self.proj_queue = Gst.ElementFactory.make("queue", None)
        self.video_sink = _create_video_sink()

        # Monitor branch
        self.monitor_queue = Gst.ElementFactory.make("queue", None)
        self.monitor_sink = _create_video_sink()

        for elem in (
            self.video_queue, self.video_tee,
            self.proj_queue, self.video_sink,
            self.monitor_queue, self.monitor_sink,
        ):
            self.pipeline.add(elem)

        self.video_queue.link(self.video_tee)
        self.video_tee.link(self.proj_queue)
        self.proj_queue.link(self.video_sink)
        self.video_tee.link(self.monitor_queue)
        self.monitor_queue.link(self.monitor_sink)

        self._audio_removed = False
        self._video_removed = False

        # Stale-frame bleed-through guard.  The projection window's
        # native child widget is a process-wide singleton: cue A's
        # last frame remains cached by the X11 compositor after A's
        # sink is torn down.  When cue B's render widget is re-mapped
        # we must not show it until B's sink has actually rendered a
        # buffer, or the compositor briefly composites A's content.
        #
        # _first_buffer_probe holds the GstPad probe id while we are
        # waiting for B's first buffer through proj_queue.src.  The
        # probe fires on the GStreamer streaming thread, so it routes
        # through _first_buffer_signal (QtQueued) to invoke
        # _show_displays on the Qt main thread.
        self._first_buffer_probe = None
        self._first_buffer_signal = Signal()
        self._first_buffer_signal.connect(
            self._show_displays, Connection.QtQueued
        )

        # Deferred-clear bridge.  stop() may be called from a bus
        # EOS handler whose thread isn't guaranteed to be the Qt main
        # thread; route the timer-scheduling through QtQueued so the
        # QTimer is always created on the main thread.
        self._deferred_clear_signal = Signal()
        self._deferred_clear_signal.connect(
            self._on_deferred_clear_scheduled, Connection.QtQueued
        )

        # Install a synchronous bus handler so we can set the
        # window handle before each sink opens its own window.
        bus = self.pipeline.get_bus()
        bus.enable_sync_message_emission()
        self._sync_handler = bus.connect(
            "sync-message::element", self.__on_sync_message
        )

    def play(self):
        # Cancel any clear that an immediately-preceding stop() may
        # have scheduled.  In a playlist GroupCue the auto-advance
        # path runs us within one Qt tick of the previous child's
        # stop(), well inside the defer window — cancelling here is
        # how playlists keep their flow seamless.
        VideoSink._pending_clear = False

        VideoSink._previous_sink = self

        # Fast path: pipeline already holds a prerolled buffer
        # (pre-armed cue, or resume from pause).  The sink can render
        # immediately on map, so showing now is safe and avoids one
        # preroll cycle of added latency.
        _, state, _ = self.pipeline.get_state(0)
        if state == Gst.State.PAUSED:
            self._show_displays()
            return

        # Cold-start path: pipeline is in READY/Null.  Defer the
        # show until proj_queue.src emits its first buffer (preroll
        # of the new sink), or the singleton render widget would
        # briefly composite the previous cue's last frame.
        pad = self.proj_queue.get_static_pad("src")
        if pad is None or self._first_buffer_probe is not None:
            # No pad, or a probe is somehow already installed —
            # fall back to immediate show.  Should not happen in
            # normal flow.
            self._show_displays()
            return

        self._first_buffer_probe = pad.add_probe(
            Gst.PadProbeType.BUFFER,
            self.__on_first_buffer,
        )

    def _show_displays(self):
        """Map the projection (and monitor) render surfaces.

        Called either directly from play() on the fast path, or via
        _first_buffer_signal once the new sink's first buffer has
        passed proj_queue.src.
        """
        window = self._video_window()
        if window is not None:
            window.show_display()

        monitor = self._monitor_window()
        if monitor is not None and monitor.isVisible():
            monitor.show_display()

    def __on_first_buffer(self, pad, info):
        """Pad probe — fires on the streaming thread.

        Marks the probe consumed and hands off to the main thread
        for the Qt show() call.  Returning REMOVE uninstalls the
        probe atomically; subsequent buffers must not re-trigger.
        """
        self._first_buffer_probe = None
        self._first_buffer_signal.emit()
        return Gst.PadProbeReturn.REMOVE

    def _consume_first_buffer_probe(self):
        """Remove a pending first-buffer probe, if any.

        Called from stop()/dispose() to clean up when a cue is torn
        down before its first buffer arrives — the probe would
        otherwise outlive the proj_queue element.
        """
        if self._first_buffer_probe is None:
            return
        probe_id = self._first_buffer_probe
        self._first_buffer_probe = None
        pad = self.proj_queue.get_static_pad("src")
        if pad is not None:
            try:
                pad.remove_probe(probe_id)
            except Exception:
                # Pad already gone (pipeline tear-down race) —
                # losing the probe with the pad is benign.
                pass

    def stop(self):
        self._consume_first_buffer_probe()

        if VideoSink._previous_sink is self:
            VideoSink._previous_sink = None

        # Defer the projection clear by _DEFERRED_CLEAR_MS.  An
        # immediate clear here would race the playlist GroupCue's
        # auto-advance: A's stopped → queued slot → B's play() runs
        # all within a Qt tick, but the X11 unmap/remap between them
        # is visible to the compositor as a black gap.  By deferring,
        # the outgoing cue's last frame stays visible until either
        # the next cue's first buffer overwrites it (seamless flow)
        # or the timer expires (standalone stop → black, matching
        # QLab/SCS default behaviour).
        VideoSink._pending_clear = True
        self._deferred_clear_signal.emit()

    def _on_deferred_clear_scheduled(self):
        """Main thread: arm the QTimer that performs the clear.

        Invoked via _deferred_clear_signal (QtQueued) so the QTimer
        is always created on the main thread, regardless of the
        thread that called stop().
        """
        from PyQt5.QtCore import QTimer
        QTimer.singleShot(
            _DEFERRED_CLEAR_MS, VideoSink._maybe_do_clear,
        )

    @classmethod
    def _maybe_do_clear(cls):
        """QTimer callback (main thread).

        Performs the clear only if a subsequent play() hasn't reset
        the pending flag.  Idempotent across multiple in-flight
        timers: the first one through clears and resets; later ones
        no-op.
        """
        if not cls._pending_clear:
            return
        cls._pending_clear = False

        # Lazy import to avoid the circular gst_backend ↔ video_sink
        # import that would happen at module load time.
        from lisp.plugins.gst_backend.gst_backend import GstBackend
        window = GstBackend.video_window()
        if window is not None:
            window.clear_display()

        monitor = GstBackend.monitor_window()
        if monitor is not None and monitor.isVisible():
            monitor.clear_display()

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
                if vs is not None and not hasattr(
                    element, "video_sink"
                ):
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
                    "VideoSink: failed to link video "
                    "source to video queue"
                )
        else:
            logger.debug(
                "VideoSink: no video source found in "
                "pipeline"
            )

        if not has_audio_src:
            logger.info(
                "VideoSink: no audio source, removing "
                "audio sink"
            )
            self.pipeline.remove(self.audio_sink)
            self._audio_removed = True

    def dispose(self):
        # Clean up before tearing the pipeline down — proj_queue may
        # be removed below, after which the probe id can't be revoked.
        self._consume_first_buffer_probe()

        bus = self.pipeline.get_bus()
        if bus is not None and self._sync_handler is not None:
            bus.disconnect(self._sync_handler)
            self._sync_handler = None
        if not self._video_removed:
            self.pipeline.remove(self.video_queue)
            self.pipeline.remove(self.video_tee)
            self.pipeline.remove(self.proj_queue)
            self.pipeline.remove(self.video_sink)
            self.pipeline.remove(self.monitor_queue)
            self.pipeline.remove(self.monitor_sink)
            self._video_removed = True
        if not self._audio_removed:
            self.pipeline.remove(self.audio_sink)
            self._audio_removed = True

    @staticmethod
    def _video_window():
        from lisp.plugins.gst_backend.gst_backend import (
            GstBackend,
        )
        return GstBackend.video_window()

    @staticmethod
    def _monitor_window():
        from lisp.plugins.gst_backend.gst_backend import (
            GstBackend,
        )
        return GstBackend.monitor_window()

    def _find_owner_sink(self, element):
        """Walk up from element to find which top-level sink it
        belongs to.  Bin-based sinks like glimagesink post
        prepare-window-handle from an internal child, not from
        the bin we stored."""
        while element is not None:
            if element == self.video_sink:
                return self._video_window()
            if element == self.monitor_sink:
                return self._monitor_window()
            element = element.get_parent()
        return None

    def __on_sync_message(self, bus, message):
        """Handle prepare-window-handle from video sinks.

        This runs in the GStreamer streaming thread, before each
        sink creates its own window.  We route the projection
        sink to VideoOutputWindow and the monitor sink to
        VideoMonitorWindow.
        """
        if message.get_structure() is None:
            return
        if message.get_structure().get_name() != \
                "prepare-window-handle":
            return

        window = self._find_owner_sink(message.src)

        if window is not None:
            handle = window.window_handle()
            if handle != 0:
                message.src.set_window_handle(handle)
                logger.debug(
                    "VideoSink: set window handle %d on %s",
                    handle,
                    message.src.get_name(),
                )
