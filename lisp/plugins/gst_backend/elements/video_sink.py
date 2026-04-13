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

logger = logging.getLogger(__name__)

# Preferred video sink elements in priority order.
# glimagesink: OpenGL-based, good quality, works on X11 + XWayland.
# xvimagesink: X11 XVideo extension, lower overhead, X11 only.
_VIDEO_SINK_FACTORIES = ("glimagesink", "xvimagesink")


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

        # Install a synchronous bus handler so we can set the
        # window handle before each sink opens its own window.
        bus = self.pipeline.get_bus()
        bus.enable_sync_message_emission()
        self._sync_handler = bus.connect(
            "sync-message::element", self.__on_sync_message
        )

    def play(self):
        VideoSink._previous_sink = self

        window = self._video_window()
        if window is not None:
            window.show_display()

        monitor = self._monitor_window()
        if monitor is not None and monitor.isVisible():
            monitor.show_display()

    def stop(self):
        if VideoSink._previous_sink is self:
            VideoSink._previous_sink = None

        window = self._video_window()
        if window is not None:
            window.clear_display()

        monitor = self._monitor_window()
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
        bus = self.pipeline.get_bus()
        if bus is not None:
            bus.disconnect(self._sync_handler)
        if not self._video_removed:
            self.pipeline.remove(self.video_queue)
            self.pipeline.remove(self.video_tee)
            self.pipeline.remove(self.proj_queue)
            self.pipeline.remove(self.video_sink)
            self.pipeline.remove(self.monitor_queue)
            self.pipeline.remove(self.monitor_sink)
        if not self._audio_removed:
            self.pipeline.remove(self.audio_sink)

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
