# This file is part of Linux Show Player
#
# Copyright 2017 Francesco Ceruti <ceppofrancy@gmail.com>
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

from PyQt5.QtCore import QT_TRANSLATE_NOOP, QTime, Qt
from PyQt5.QtWidgets import (
    QDateTimeEdit,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QSpinBox,
    QTimeEdit,
)

from lisp.ui.settings.cue_pages.cue_general import make_flat_group
from lisp.ui.settings.pages import SettingsPage
from lisp.ui.ui_utils import translate


class MediaCueSettings(SettingsPage):
    Name = QT_TRANSLATE_NOOP("SettingsPageName", "Media Cue")
    SortOrder = 60

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        grid = QGridLayout(self)
        grid.setContentsMargins(8, 4, 8, 4)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(2)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 3)

        self.startGroup = make_flat_group()
        self.startGroup.setLayout(QHBoxLayout())
        self.startGroup.layout().setContentsMargins(0, 0, 0, 0)
        self.startEdit = QTimeEdit(self.startGroup)
        self.startEdit.setDisplayFormat("HH:mm:ss.zzz")
        self.startEdit.setCurrentSection(QDateTimeEdit.SecondSection)
        self.startGroup.layout().addWidget(self.startEdit)
        grid.addWidget(self.startGroup, 0, 0)

        self.stopGroup = make_flat_group()
        self.stopGroup.setLayout(QHBoxLayout())
        self.stopGroup.layout().setContentsMargins(0, 0, 0, 0)
        self.stopEdit = QTimeEdit(self.stopGroup)
        self.stopEdit.setDisplayFormat("HH:mm:ss.zzz")
        self.stopEdit.setCurrentSection(QDateTimeEdit.SecondSection)
        self.stopGroup.layout().addWidget(self.stopEdit)
        grid.addWidget(self.stopGroup, 1, 0)

        self.loopGroup = make_flat_group()
        self.loopGroup.setLayout(QHBoxLayout())
        self.loopGroup.layout().setContentsMargins(0, 0, 0, 0)
        self.spinLoop = QSpinBox(self.loopGroup)
        self.spinLoop.setRange(-1, 1_000_000)
        self.loopGroup.layout().addWidget(self.spinLoop)
        grid.addWidget(self.loopGroup, 2, 0)

        # Column 1 reserved for the waveform trimmer. The trimmer is
        # mounted lazily in loadSettings() once the cue's media source
        # (or lack of one) is known. Two placeholder captions live in
        # the same grid cell — only one is ever visible at a time.
        self._waveformSlot = None
        self._waveformRow = (0, 3)

        self.placeholderLabel = QLabel("", self)
        self.placeholderLabel.setAlignment(Qt.AlignCenter)
        self.placeholderLabel.setStyleSheet("color: #888;")
        self.placeholderLabel.hide()
        grid.addWidget(self.placeholderLabel, 0, 1, 3, 1)

        self.imagePlaceholder = QLabel("", self)
        self.imagePlaceholder.setAlignment(Qt.AlignCenter)
        self.imagePlaceholder.setStyleSheet("color: #888;")
        self.imagePlaceholder.hide()
        grid.addWidget(self.imagePlaceholder, 0, 1, 3, 1)

        grid.setRowStretch(3, 1)

        self.retranslateUi()

    def retranslateUi(self):
        self.startGroup.setTitle(translate("MediaCueSettings", "Start time"))
        self.startEdit.setToolTip(
            translate("MediaCueSettings", "Start position of the media")
        )
        self.stopGroup.setTitle(translate("MediaCueSettings", "Stop time"))
        self.stopEdit.setToolTip(
            translate("MediaCueSettings", "Stop position of the media")
        )
        self.loopGroup.setTitle(translate("MediaCueSettings", "Loop"))
        self.spinLoop.setToolTip(
            translate(
                "MediaCueSettings",
                "Repetition after first play (-1 = infinite)",
            )
        )

    def getSettings(self):
        settings = {}

        if self.isGroupEnabled(self.startGroup):
            time = self.startEdit.time().msecsSinceStartOfDay()
            settings["start_time"] = time
        if self.isGroupEnabled(self.stopGroup):
            time = self.stopEdit.time().msecsSinceStartOfDay()
            settings["stop_time"] = time
        if self.isGroupEnabled(self.loopGroup):
            settings["loop"] = self.spinLoop.value()

        return {"media": settings}

    def enableCheck(self, enabled):
        self.setGroupEnabled(self.startGroup, enabled)
        self.setGroupEnabled(self.stopGroup, enabled)
        self.setGroupEnabled(self.loopGroup, enabled)

    def loadSettings(self, settings):
        media = settings.get("media", {})
        is_image = self._is_image_cue(media)

        if "loop" in media:
            self.spinLoop.setValue(media["loop"])

        duration = media.get("duration", 0)
        time = self._to_qtime(duration)
        self.startEdit.setMaximumTime(time)
        self.stopEdit.setMaximumTime(time)

        if "start_time" in media:
            self.startEdit.setTime(self._to_qtime(media["start_time"]))

        if "stop_time" in media:
            stop_display = self._display_stop(media["stop_time"], duration)
            self.stopEdit.setTime(self._to_qtime(stop_display))

        # Image cues: imagefreeze ignores seek positions, so start_time
        # and stop_time are no-ops. Disable the fields so the UI stops
        # offering knobs that don't turn anything.
        self.startEdit.setEnabled(not is_image)
        self.stopEdit.setEnabled(not is_image)

    @staticmethod
    def _is_image_cue(media_settings: dict) -> bool:
        # GstMedia.__getstate__ flattens each element's state under a
        # key named after the element class (typename(element)), so an
        # ImageInput shows up as a top-level "ImageInput" key. Test
        # callers may inject _element_classes directly.
        if "ImageInput" in media_settings:
            return True
        return "ImageInput" in media_settings.get("_element_classes", [])

    @staticmethod
    def _display_stop(stored_ms: int, duration_ms: int) -> int:
        # Backend treats stop_time == 0 as "play to natural end". Showing
        # a literal 0:00:00 is opaque; map to duration for display. Save
        # is verbatim — persisting duration is equivalent to persisting 0
        # (both fall through the 0 < stop_time < duration guard in
        # gst_media.py).
        if stored_ms == 0 and duration_ms > 0:
            return duration_ms
        return stored_ms

    def _to_qtime(self, m_seconds):
        return QTime.fromMSecsSinceStartOfDay(m_seconds)
