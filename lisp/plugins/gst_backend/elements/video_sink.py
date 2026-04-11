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

        # Video path: queue -> overlay-capable video sink.
        self.video_queue = Gst.ElementFactory.make("queue", None)
        self.video_sink = _create_video_sink()
        self.pipeline.add(self.video_queue)
        self.pipeline.add(self.video_sink)
        self.video_queue.link(self.video_sink)

        self._audio_removed = False
        self._video_removed = False
        self._window_handle = 0

        # Install a synchronous bus handler so we can set the
        # window handle before the sink opens its own window.
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

    def stop(self):
        if VideoSink._previous_sink is self:
            VideoSink._previous_sink = None

        window = self._video_window()
        if window is not None:
            window.clear_display()

    def sink(self):
        """Audio sink -- connected by the linear chain."""
        return self.audio_sink

    def post_link(self, all_elements):
        """Wire the video branch and remove unused sinks.

        For video+audio pipelines (UriAvInput): wires the video
        branch, keeps both audio and video sinks.

        For video-only pipelines (ImageInput): wires the video
        branch and removes the unused audio sink to prevent the
        pipeline from hanging on an unlinked autoaudiosink.
        """
        video_wired = False
        has_audio_src = False

        for element in all_elements:
            if element is self:
                continue
            if not video_wired:
                video_src = element.video_src()
                if video_src is not None:
                    if not video_src.link(self.video_queue):
                        logger.warning(
                            "VideoSink: failed to link video "
                            "source to video queue"
                        )
                    video_wired = True
            if element.src() is not None:
                has_audio_src = True

        if not video_wired:
            logger.debug(
                "VideoSink: no video source found in pipeline"
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
            self.pipeline.remove(self.video_sink)
        if not self._audio_removed:
            self.pipeline.remove(self.audio_sink)

    @staticmethod
    def _video_window():
        from lisp.plugins.gst_backend.gst_backend import (
            GstBackend,
        )
        return GstBackend.video_window()

    def __on_sync_message(self, bus, message):
        """Handle prepare-window-handle from the video sink.

        This runs in the GStreamer streaming thread, before the
        sink creates its own window.  Setting the handle here
        ensures GStreamer renders into our VideoOutputWindow.

        Always fetches the current handle from the window
        (not cached) because the render widget may have been
        recreated since the last call.
        """
        if message.get_structure() is None:
            return
        if message.get_structure().get_name() != \
                "prepare-window-handle":
            return

        window = self._video_window()
        if window is not None:
            self._window_handle = window.window_handle()

        if self._window_handle != 0:
            message.src.set_window_handle(self._window_handle)
            logger.debug(
                "VideoSink: set window handle %d on %s",
                self._window_handle,
                message.src.get_name(),
            )
