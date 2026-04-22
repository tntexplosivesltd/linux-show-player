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

from lisp.backend import get_backend
from lisp.core.signal import Connection
from lisp.ui.settings.cue_pages.cue_general import make_flat_group
from lisp.ui.settings.pages import SettingsPage
from lisp.ui.ui_utils import translate
from lisp.ui.widgets.waveform import (
    TrimmableTimelineWidget,
    TrimmableWaveformWidget,
)


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

        self.trimmer = None
        self._cue = None
        self._current_waveform = None
        # Stashed at loadSettings time so getSettings can map a displayed
        # stop_time == duration back to the 0 sentinel (SeekType.NONE).
        self._last_duration = 0

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
            # Backend uses stop_time == 0 as SeekType.NONE ("play to
            # natural end"), distinct from SeekType.SET duration. When
            # the displayed stop equals the known duration, map back to
            # the sentinel so the seek semantics survive a save cycle.
            if self._last_duration > 0 and time == self._last_duration:
                time = 0
            settings["stop_time"] = time
        if self.isGroupEnabled(self.loopGroup):
            settings["loop"] = self.spinLoop.value()

        return {"media": settings}

    def enableCheck(self, enabled):
        self.setGroupEnabled(self.startGroup, enabled)
        self.setGroupEnabled(self.stopGroup, enabled)
        self.setGroupEnabled(self.loopGroup, enabled)
        # Multi-select: waveforms don't compose across cues, so hide
        # the trimmer slot and show a placeholder caption.
        self.placeholderLabel.setText(
            translate("MediaCueSettings", "Select a single cue")
            if enabled
            else ""
        )
        self.placeholderLabel.setVisible(enabled)

    def setCue(self, cue):
        """Bind the live cue. Called by the inspector before loadSettings."""
        self._cue = cue

    def loadSettings(self, settings):
        media = settings.get("media", {})
        is_image = self._is_image_cue(media)
        duration = media.get("duration", 0)
        self._last_duration = duration

        if "loop" in media:
            self.spinLoop.setValue(media["loop"])

        time = self._to_qtime(duration)
        self.startEdit.setMaximumTime(time)
        self.stopEdit.setMaximumTime(time)

        if "start_time" in media:
            self.startEdit.setTime(self._to_qtime(media["start_time"]))

        stop_display = duration
        if "stop_time" in media:
            stop_display = self._display_stop(media["stop_time"], duration)
            self.stopEdit.setTime(self._to_qtime(stop_display))

        # Reactive bound logic only runs once a user edits a field; seed
        # the bounds here so initial state already reflects start < stop.
        start_ms = self._ms(self.startEdit.time())
        if stop_display > 0:
            self.stopEdit.setMinimumTime(self._to_qtime(start_ms + 1))
            self.startEdit.setMaximumTime(
                self._to_qtime(max(0, stop_display - 1))
            )

        # Image cues: imagefreeze ignores seek positions, so start_time
        # and stop_time are no-ops. Disable the fields so the UI stops
        # offering knobs that don't turn anything.
        self.startEdit.setEnabled(not is_image)
        self.stopEdit.setEnabled(not is_image)

        cue = self._cue
        if cue is None:
            self._teardown_trimmer()
            return

        if is_image:
            self._show_image_placeholder()
        else:
            waveform = get_backend().media_waveform(cue.media)
            self._install_waveform(waveform, use_timeline=False)
            # Seed new trimmer from the field values — the trimmer was
            # just built with defaults (0, duration) and the field edits
            # above fired into no handler (we connect them in install).
            self.trimmer.setStartTime(start_ms, silent=True)
            if stop_display > 0:
                self.trimmer.setStopTime(stop_display, silent=True)

    def _teardown_trimmer(self):
        # Stop the outgoing GStreamer decode pipeline and drop signal
        # connections so a late failed/ready emission on an orphan
        # waveform can't swap the current trimmer for a different cue.
        if self._current_waveform is not None:
            try:
                self._current_waveform.failed.disconnect(
                    self._on_waveform_failed
                )
            except Exception:
                pass
            try:
                self._current_waveform.clear()
            except Exception:
                pass
            self._current_waveform = None

        if self._waveformSlot is not None:
            # Detach field handlers so a later edit on a torn-down page
            # doesn't fire dead-reference propagation into setStopTime
            # on a half-disposed widget.
            try:
                self.startEdit.timeChanged.disconnect(
                    self._on_start_edit_changed
                )
            except TypeError:
                pass
            try:
                self.stopEdit.timeChanged.disconnect(
                    self._on_stop_edit_changed
                )
            except TypeError:
                pass
            # Break the waveform→widget ready link before deleteLater
            # so a queued ready emission can't land on a Qt-dead widget.
            if hasattr(self._waveformSlot, "detach"):
                self._waveformSlot.detach()
            self.layout().removeWidget(self._waveformSlot)
            self._waveformSlot.deleteLater()
            self._waveformSlot = None
            self.trimmer = None
        self.imagePlaceholder.hide()

    def _show_image_placeholder(self):
        self._teardown_trimmer()
        self.imagePlaceholder.setText(
            translate(
                "MediaCueSettings",
                "Trimming does not apply to image cues.",
            )
        )
        self.imagePlaceholder.show()

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

    def _install_waveform(self, waveform_or_duration, use_timeline: bool):
        # Tear down any existing trimmer first so repeated loadSettings
        # (user navigating between cues) doesn't leak widgets or signals.
        self._teardown_trimmer()

        if use_timeline:
            duration = (
                waveform_or_duration.duration
                if hasattr(waveform_or_duration, "duration")
                else int(waveform_or_duration)
            )
            slot = TrimmableTimelineWidget(duration_ms=duration, parent=self)
            self._current_waveform = None
        else:
            slot = TrimmableWaveformWidget(waveform_or_duration, parent=self)
            self._current_waveform = waveform_or_duration
            # Custom Signal uses weakrefs — bound method, not lambda.
            waveform_or_duration.failed.connect(
                self._on_waveform_failed, Connection.QtQueued
            )

        slot.setMinimumHeight(120)
        row, row_span = self._waveformRow
        self.layout().addWidget(slot, row, 1, row_span, 1)
        self._waveformSlot = slot
        self.trimmer = slot

        # Bidirectional sync. silent=True on the trimmer side and
        # blockSignals on the QTimeEdit side break the cycle.
        self.startEdit.timeChanged.connect(self._on_start_edit_changed)
        self.stopEdit.timeChanged.connect(self._on_stop_edit_changed)
        self.trimmer.startTimeChanged.connect(self._on_trim_start_changed)
        self.trimmer.stopTimeChanged.connect(self._on_trim_stop_changed)
        self.trimmer.trimReleased.connect(self.commit_requested.emit)

    def _on_waveform_failed(self):
        wf = self._current_waveform
        if wf is None:
            return
        self._swap_to_timeline(wf.duration)

    def _swap_to_timeline(self, duration_ms: int):
        if isinstance(self._waveformSlot, TrimmableTimelineWidget):
            return
        start = self.trimmer.startTime() if self.trimmer else 0
        stop = self.trimmer.stopTime() if self.trimmer else duration_ms
        self._install_waveform(duration_ms, use_timeline=True)
        self.trimmer.setStartTime(start, silent=True)
        self.trimmer.setStopTime(stop, silent=True)

    def _ms(self, qtime) -> int:
        return qtime.msecsSinceStartOfDay()

    def _on_start_edit_changed(self, qtime):
        if self.trimmer is None:
            return
        ms = self._ms(qtime)
        self.trimmer.setStartTime(ms, silent=True)
        stop_max = max(0, self.trimmer.stopTime() - 1)
        self.stopEdit.setMinimumTime(self._to_qtime(ms + 1))
        self.startEdit.setMaximumTime(self._to_qtime(stop_max))

    def _on_stop_edit_changed(self, qtime):
        if self.trimmer is None:
            return
        ms = self._ms(qtime)
        self.trimmer.setStopTime(ms, silent=True)
        self.startEdit.setMaximumTime(self._to_qtime(max(0, ms - 1)))

    def _on_trim_start_changed(self, ms: int):
        self.startEdit.blockSignals(True)
        self.startEdit.setTime(self._to_qtime(ms))
        self.startEdit.blockSignals(False)
        self.stopEdit.setMinimumTime(self._to_qtime(ms + 1))

    def _on_trim_stop_changed(self, ms: int):
        self.stopEdit.blockSignals(True)
        self.stopEdit.setTime(self._to_qtime(ms))
        self.stopEdit.blockSignals(False)
        self.startEdit.setMaximumTime(self._to_qtime(max(0, ms - 1)))
