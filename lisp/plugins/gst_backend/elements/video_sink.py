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


class VideoSink(GstMediaElement):
    ElementType = ElementType.Output
    MediaType = MediaType.AudioAndVideo
    Name = QT_TRANSLATE_NOOP("MediaElementName", "A/V System Out")

    def __init__(self, pipeline):
        super().__init__(pipeline)

        # Audio path: same as the existing AutoSink
        self.audio_sink = Gst.ElementFactory.make(
            "autoaudiosink", None
        )
        self.pipeline.add(self.audio_sink)

        # Video path: queue -> autovideosink
        # The queue decouples the video branch from the audio branch,
        # and autovideosink picks the best available video output.
        self.video_queue = Gst.ElementFactory.make("queue", None)
        self.video_sink = Gst.ElementFactory.make(
            "autovideosink", None
        )
        self.pipeline.add(self.video_queue)
        self.pipeline.add(self.video_sink)
        self.video_queue.link(self.video_sink)

        self._audio_removed = False
        self._video_removed = False

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
        if not self._video_removed:
            self.pipeline.remove(self.video_queue)
            self.pipeline.remove(self.video_sink)
        if not self._audio_removed:
            self.pipeline.remove(self.audio_sink)
