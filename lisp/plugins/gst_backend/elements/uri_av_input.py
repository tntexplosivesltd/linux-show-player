# This file is part of Linux Show Player
#
# Copyright 2024 Francesco Ceruti <ceppofrancy@gmail.com>
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
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PyQt5.QtCore import QT_TRANSLATE_NOOP

from lisp.backend.media_element import MediaType
from lisp.core.decorators import async_in_pool
from lisp.core.properties import Property
from lisp.core.session_uri import SessionURI
from lisp.plugins.gst_backend.gi_repository import Gst
from lisp.plugins.gst_backend.gst_element import GstSrcElement
from lisp.plugins.gst_backend.gst_properties import (
    GstProperty,
    GstURIProperty,
)
from lisp.plugins.gst_backend.gst_utils import gst_uri_duration

logger = logging.getLogger(__name__)


class UriAvInput(GstSrcElement):
    MediaType = MediaType.AudioAndVideo
    Name = QT_TRANSLATE_NOOP("MediaElementName", "URI A/V Input")

    _mtime = Property(default=-1)
    uri = GstURIProperty("decoder", "uri")
    download = GstProperty("decoder", "download", default=False)
    buffer_size = GstProperty("decoder", "buffer-size", default=-1)
    use_buffering = GstProperty(
        "decoder", "use-buffering", default=False
    )

    def __init__(self, pipeline):
        super().__init__(pipeline)

        self.decoder = Gst.ElementFactory.make("uridecodebin", None)

        # Audio branch: queue -> audioconvert
        # Queues are essential in multi-stream pipelines to prevent
        # GStreamer deadlock between audio and video branches.
        self.audio_queue = Gst.ElementFactory.make("queue", None)
        self.audio_convert = Gst.ElementFactory.make(
            "audioconvert", None
        )

        # Video branch: queue -> videoconvert -> videoscale
        self.video_queue = Gst.ElementFactory.make("queue", None)
        self.video_convert = Gst.ElementFactory.make(
            "videoconvert", None
        )
        self.video_scale = Gst.ElementFactory.make("videoscale", None)

        self._audio_linked = False
        self._video_linked = False

        self._pad_handler = self.decoder.connect(
            "pad-added", self.__on_pad_added
        )
        self._no_more_pads_handler = self.decoder.connect(
            "no-more-pads", self.__on_no_more_pads
        )

        self.pipeline.add(self.decoder)
        self.pipeline.add(self.audio_queue)
        self.pipeline.add(self.audio_convert)
        self.pipeline.add(self.video_queue)
        self.pipeline.add(self.video_convert)
        self.pipeline.add(self.video_scale)

        self.audio_queue.link(self.audio_convert)
        self.video_queue.link(self.video_convert)
        self.video_convert.link(self.video_scale)

        self.changed("uri").connect(self.__uri_changed)

    def input_uri(self) -> SessionURI:
        return SessionURI(self.uri)

    def dispose(self):
        self.decoder.disconnect(self._pad_handler)
        self.decoder.disconnect(self._no_more_pads_handler)

    def src(self):
        """Audio source -- feeds the linear audio chain."""
        return self.audio_convert

    def video_src(self):
        """Video source -- feeds the video branch via post_link."""
        return self.video_scale

    def has_audio(self):
        """Check if the decoded stream contains audio pads."""
        for pad in self.decoder.pads:
            caps = pad.get_current_caps()
            if caps and caps.to_string().startswith("audio"):
                return True
        return False

    def has_video(self):
        """Check if the decoded stream contains video pads."""
        for pad in self.decoder.pads:
            caps = pad.get_current_caps()
            if caps and caps.to_string().startswith("video"):
                return True
        return False

    def __on_pad_added(self, decodebin, pad):
        caps = pad.get_current_caps()
        if caps is None:
            return

        struct_name = caps.get_structure(0).get_name()
        if struct_name.startswith("audio/"):
            if self._audio_linked:
                logger.debug("UriAvInput: ignoring extra audio pad")
                return
            sink_pad = self.audio_queue.get_static_pad("sink")
            result = pad.link(sink_pad)
            if result == Gst.PadLinkReturn.OK:
                self._audio_linked = True
            else:
                logger.warning(
                    "UriAvInput: failed to link audio pad: %s",
                    result,
                )
        elif struct_name.startswith("video/"):
            if self._video_linked:
                logger.debug("UriAvInput: ignoring extra video pad")
                return
            sink_pad = self.video_queue.get_static_pad("sink")
            result = pad.link(sink_pad)
            if result == Gst.PadLinkReturn.OK:
                self._video_linked = True
            else:
                logger.warning(
                    "UriAvInput: failed to link video pad: %s",
                    result,
                )

    def __on_no_more_pads(self, decodebin):
        """Called when uridecodebin has emitted all pads.

        Remove unused branches so GStreamer doesn't hang waiting
        for data on unlinked elements.
        """
        if not self._audio_linked:
            logger.info(
                "UriAvInput: no audio stream found, removing "
                "audio branch"
            )
            self.pipeline.remove(self.audio_queue)
            self.pipeline.remove(self.audio_convert)
        if not self._video_linked:
            logger.info(
                "UriAvInput: no video stream found, removing "
                "video branch"
            )
            self.pipeline.remove(self.video_queue)
            self.pipeline.remove(self.video_convert)
            self.pipeline.remove(self.video_scale)

    def __uri_changed(self, uri):
        uri = SessionURI(uri)

        old_mtime = self._mtime
        if uri.is_local:
            path = Path(uri.absolute_path)
            if path.exists():
                self._mtime = path.stat().st_mtime
        else:
            old_mtime = None
            self._mtime = -1

        if old_mtime != self._mtime or self.duration < 0:
            self.__duration()

    @async_in_pool(pool=ThreadPoolExecutor(1))
    def __duration(self):
        self.duration = gst_uri_duration(self.input_uri())
