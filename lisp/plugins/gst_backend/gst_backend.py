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
from PyQt5.QtWidgets import QAction, QFileDialog, QApplication

from lisp import backend
from lisp.backend.backend import Backend as BaseBackend
from lisp.command.layout import LayoutAutoInsertCuesCommand
from lisp.core.decorators import memoize
from lisp.core.plugin import Plugin
from lisp.cues.media_cue import MediaCue
from lisp.plugins.gst_backend import config, elements, settings
from lisp.ui.widgets.notification import NotificationLevel
from lisp.plugins.gst_backend.gi_repository import Gst
from lisp.plugins.gst_backend.video_exclusive import (
    VideoExclusiveManager,
)
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

    _video_window = None
    _monitor_window = None

    @classmethod
    def video_window(cls):
        """Return the singleton VideoOutputWindow, or None."""
        return cls._video_window

    @classmethod
    def monitor_window(cls):
        """Return the singleton VideoMonitorWindow, or None."""
        return cls._monitor_window

    def __init__(self, app):
        super().__init__(app)

        # Initialize GStreamer
        Gst.init([])

        # Create the shared video output and monitor windows.
        # Import here to avoid circular imports at module level.
        from lisp.plugins.gst_backend.gst_video_window import (
            VideoMonitorWindow,
            VideoOutputWindow,
        )
        GstBackend._video_window = VideoOutputWindow(app.window)
        GstBackend._monitor_window = VideoMonitorWindow(app.window)
        self.__apply_video_config()

        # Block overlapping video/image cue playback.
        self.app.video_exclusive_manager = (
            VideoExclusiveManager(self.app)
        )

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

        # Video monitor toggle in Tools menu
        self._monitor_action = QAction(
            translate("GstBackend", "Video Monitor"),
            self.app.window,
        )
        self._monitor_action.setCheckable(True)
        self._monitor_action.toggled.connect(
            self.__toggle_monitor_window
        )
        self.app.window.menuTools.addAction(self._monitor_action)

        # Load elements and their settings-widgets
        elements.load()
        settings.load()

        # Auto-show/hide the video window based on whether any
        # video or image cues exist in the session.
        self.app.cue_model.item_added.connect(
            self.__update_video_window_visibility
        )
        self.app.cue_model.item_removed.connect(
            self.__update_video_window_visibility
        )

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
        audio_files = []
        video_files = []
        image_files = []

        for url in urls:
            extension = os.path.splitext(url.fileName())[-1][1:]
            path = url.path()
            if extension in extensions["image"]:
                image_files.append(path)
            elif extension in extensions["video"]:
                video_files.append(path)
            elif extension in extensions["audio"]:
                audio_files.append(path)

        if audio_files:
            self.add_cue_from_files(audio_files)
        if video_files:
            self.add_video_cue_from_files(video_files)
        if image_files:
            self.add_image_cue_from_files(image_files)

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
                "video_pipeline",
                ["Volume", "DbMeter", "VideoAlpha", "VideoSink"],
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
                "image_pipeline",
                ["VideoAlpha", "VideoSink"],
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

    def __apply_video_config(self):
        """Apply video output settings to the shared window.

        Screen selection:
        * ``-1`` (auto): use the first non-primary screen if one
          is connected, otherwise fall back to the primary screen.
        * ``0..N``: use that specific screen index.

        Fullscreen is only engaged when the target screen is a
        secondary display — never on the primary, so the LiSP
        operator UI is not covered.
        """
        window = GstBackend.video_window()
        if window is None:
            return

        screens = QApplication.screens()
        primary = QApplication.primaryScreen()
        screen_cfg = GstBackend.Config.get("video_screen", -1)

        if screen_cfg >= 0 and screen_cfg < len(screens):
            target = screens[screen_cfg]
        elif len(screens) > 1:
            # Auto: pick first non-primary screen
            target = next(
                (s for s in screens if s is not primary),
                primary,
            )
        else:
            target = primary

        window.set_display_screen(target)

        is_secondary = target is not primary
        fullscreen = GstBackend.Config.get(
            "video_fullscreen", True
        )
        window.set_fullscreen(fullscreen and is_secondary)

    def __update_video_window_visibility(self, cue=None):
        """Show the video window if any video/image cues exist.

        Optimised: on add, if the new cue has VideoSink we can
        show immediately.  On remove, we only need to scan the
        model if the removed cue had VideoSink.
        """
        window = GstBackend.video_window()
        if window is None:
            return

        cue_has_video = (
            cue is not None
            and hasattr(cue, "media")
            and cue.media.element("VideoSink") is not None
        )

        if cue_has_video and not window.isVisible():
            # Re-apply config (user may have changed settings)
            self.__apply_video_config()
            window.show()
            return

        if not cue_has_video and window.isVisible():
            # Non-video cue changed, window already correct
            return

        # Full scan needed (video cue removed, or initial state)
        for c in self.app.cue_model:
            if hasattr(c, "media") and \
                    c.media.element("VideoSink") is not None:
                self.__apply_video_config()
                window.show()
                return

        window.hide()

    def __toggle_monitor_window(self, checked):
        monitor = GstBackend.monitor_window()
        if monitor is None:
            return

        if checked:
            monitor.show()
        else:
            monitor.hide()
