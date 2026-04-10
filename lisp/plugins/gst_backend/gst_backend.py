# This file is part of Linux Show Player
#
# Copyright 2020 Francesco Ceruti <ceppofrancy@gmail.com>
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

import os.path

from PyQt5.QtCore import Qt, QT_TRANSLATE_NOOP
from PyQt5.QtGui import QCursor
from PyQt5.QtWidgets import QFileDialog, QApplication

from lisp import backend
from lisp.backend.backend import Backend as BaseBackend
from lisp.command.layout import LayoutAutoInsertCuesCommand
from lisp.core.decorators import memoize
from lisp.core.plugin import Plugin
from lisp.cues.media_cue import MediaCue
from lisp.plugins.gst_backend import config, elements, settings
from lisp.ui.widgets.notification import NotificationLevel
from lisp.plugins.gst_backend.gi_repository import Gst
from lisp.plugins.gst_backend.gst_media_cue import (
    GstCueFactory,
    UriAudioCueFactory,
    UriImageCueFactory,
    UriVideoCueFactory,
)
from lisp.plugins.gst_backend.gst_media_settings import GstMediaSettings
from lisp.plugins.gst_backend.gst_settings import GstSettings
from lisp.plugins.gst_backend.gst_utils import (
    gst_parse_tags_list,
    gst_uri_metadata,
    gst_mime_types,
    gst_uri_duration,
)
from lisp.plugins.gst_backend.gst_waveform import GstWaveform
from lisp.ui.settings.app_configuration import AppConfigurationDialog
from lisp.ui.settings.cue_settings import CueSettingsRegistry
from lisp.ui.ui_utils import translate, qfile_filters


class GstBackend(Plugin, BaseBackend):
    Name = "GStreamer Backend"
    Authors = ("Francesco Ceruti",)
    Description = (
        "Provide audio playback capabilities via the GStreamer framework"
    )

    def __init__(self, app):
        super().__init__(app)

        # Initialize GStreamer
        Gst.init([])
        # Register GStreamer settings widgets
        AppConfigurationDialog.registerSettingsPage(
            "plugins.gst", GstSettings, GstBackend.Config
        )
        # Register elements' application-level config
        for name, page in config.load():
            AppConfigurationDialog.registerSettingsPage(
                f"plugins.gst.{name}", page, GstBackend.Config
            )
        # Add MediaCue settings widget to the CueLayout
        CueSettingsRegistry().add(GstMediaSettings, MediaCue)

        # Register GstMediaCue factory
        app.cue_factory.register_factory("GstMediaCue", GstCueFactory(tuple()))
        # Add Menu entries
        self.app.window.registerCueMenu(
            translate("GstBackend", "Audio cue (from file)"),
            self._add_uri_audio_cue,
            category=QT_TRANSLATE_NOOP("CueCategory", "Media cues"),
            shortcut="CTRL+M",
        )
        self.app.window.registerCueMenu(
            translate("GstBackend", "Video cue (from file)"),
            self._add_uri_video_cue,
            category=QT_TRANSLATE_NOOP("CueCategory", "Media cues"),
            shortcut="CTRL+SHIFT+M",
        )
        self.app.window.registerCueMenu(
            translate("GstBackend", "Image cue (from file)"),
            self._add_uri_image_cue,
            category=QT_TRANSLATE_NOOP("CueCategory", "Media cues"),
            shortcut="CTRL+SHIFT+I",
        )

        # Load elements and their settings-widgets
        elements.load()
        settings.load()

        backend.set_backend(self)

    def uri_duration(self, uri):
        return gst_uri_duration(uri)

    def uri_tags(self, uri):
        tags = gst_uri_metadata(uri).get_tags()
        if tags is not None:
            return gst_parse_tags_list(tags)

        return {}

    @memoize
    def supported_extensions(self):
        extensions = {"audio": [], "video": [], "image": []}

        for gst_mime, gst_extensions in gst_mime_types():
            for mime in ["audio", "video", "image"]:
                if gst_mime.startswith(mime):
                    extensions[mime].extend(gst_extensions)

        return extensions

    def media_waveform(self, media):
        # Skip waveform for media without audio (e.g. image cues)
        try:
            if media.elements[0].src() is None:
                return None
        except (IndexError, AttributeError):
            pass
        return super().media_waveform(media)

    def uri_waveform(self, uri, duration=None):
        if duration is None or duration <= 0:
            duration = self.uri_duration(uri)

        waveform = GstWaveform(
            uri,
            duration,
            cache_dir=self.app.conf.get("cache.position", ""),
        )

        # Notify operator when waveform generation fails
        unquoted = uri.unquoted_uri
        waveform.failed.connect(
            lambda: self.app.notify.emit(
                f'Cannot generate waveform for "{unquoted}"',
                NotificationLevel.Warning,
            )
        )

        return waveform

    def _add_uri_audio_cue(self):
        """Add audio MediaCue(s) from user-selected files"""
        directory = GstBackend.Config.get("mediaLookupDir", "")
        if not os.path.exists(directory):
            directory = self.app.session.dir()

        files, _ = QFileDialog.getOpenFileNames(
            self.app.window,
            translate("GstBackend", "Select media files"),
            directory,
            qfile_filters(
                {"audio": self.supported_extensions()["audio"]},
                anyfile=True,
            ),
        )

        if files:
            GstBackend.Config["mediaLookupDir"] = os.path.dirname(
                files[0]
            )
            GstBackend.Config.write()
            self.add_cue_from_files(files)

    def _add_uri_video_cue(self):
        """Add video MediaCue(s) from user-selected files"""
        directory = GstBackend.Config.get("mediaLookupDir", "")
        if not os.path.exists(directory):
            directory = self.app.session.dir()

        files, _ = QFileDialog.getOpenFileNames(
            self.app.window,
            translate("GstBackend", "Select video files"),
            directory,
            qfile_filters(
                {"video": self.supported_extensions()["video"]},
                anyfile=True,
            ),
        )

        if files:
            GstBackend.Config["mediaLookupDir"] = os.path.dirname(
                files[0]
            )
            GstBackend.Config.write()
            self.add_video_cue_from_files(files)

    def _add_uri_image_cue(self):
        """Add image MediaCue(s) from user-selected files"""
        directory = GstBackend.Config.get("mediaLookupDir", "")
        if not os.path.exists(directory):
            directory = self.app.session.dir()

        files, _ = QFileDialog.getOpenFileNames(
            self.app.window,
            translate("GstBackend", "Select image files"),
            directory,
            qfile_filters(
                {"image": self.supported_extensions()["image"]},
                anyfile=True,
            ),
        )

        if files:
            GstBackend.Config["mediaLookupDir"] = os.path.dirname(
                files[0]
            )
            GstBackend.Config.write()
            self.add_image_cue_from_files(files)

    def add_cue_from_urls(self, urls):
        extensions = self.supported_extensions()
        extensions = extensions["audio"] + extensions["video"]
        files = []

        for url in urls:
            # Get the file extension without the leading dot
            extension = os.path.splitext(url.fileName())[-1][1:]
            # If is a supported audio/video file keep it
            if extension in extensions:
                files.append(url.path())

        self.add_cue_from_files(files)

    def add_cue_from_files(self, files):
        QApplication.setOverrideCursor(QCursor(Qt.WaitCursor))

        # Create media cues, and add them to the Application cue_model
        factory = UriAudioCueFactory(GstBackend.Config["pipeline"])

        cues = []
        for file in files:
            cue = factory(self.app, uri=file)
            # Use the filename without extension as cue name
            cue.name = os.path.splitext(os.path.basename(file))[0]

            cues.append(cue)

        # Insert the cue into the layout
        self.app.commands_stack.do(
            LayoutAutoInsertCuesCommand(self.app.session.layout, *cues)
        )

        QApplication.restoreOverrideCursor()

    def add_video_cue_from_files(self, files):
        QApplication.setOverrideCursor(QCursor(Qt.WaitCursor))

        factory = UriVideoCueFactory(
            GstBackend.Config.get(
                "video_pipeline", ["Volume", "DbMeter", "VideoSink"]
            )
        )

        cues = []
        for file in files:
            cue = factory(self.app, uri=file)
            cue.name = os.path.splitext(os.path.basename(file))[0]
            cues.append(cue)

        self.app.commands_stack.do(
            LayoutAutoInsertCuesCommand(self.app.session.layout, *cues)
        )

        QApplication.restoreOverrideCursor()

    def add_image_cue_from_files(self, files, duration=5000):
        QApplication.setOverrideCursor(QCursor(Qt.WaitCursor))

        factory = UriImageCueFactory(
            GstBackend.Config.get(
                "image_pipeline", ["VideoSink"]
            ),
            duration=duration,
        )

        cues = []
        for file in files:
            cue = factory(self.app, uri=file)
            cue.name = os.path.splitext(os.path.basename(file))[0]
            cues.append(cue)

        self.app.commands_stack.do(
            LayoutAutoInsertCuesCommand(self.app.session.layout, *cues)
        )

        QApplication.restoreOverrideCursor()
