# This file is part of Linux Show Player
#
# Copyright 2018 Francesco Ceruti <ceppofrancy@gmail.com>
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

from PyQt5.QtCore import Qt, QMimeData, pyqtSignal, QPoint, QSize
from PyQt5.QtGui import QColor, QDrag, QIcon, QPainter, QPixmap
from PyQt5.QtWidgets import (
    QProgressBar,
    QLCDNumber,
    QLabel,
    QHBoxLayout,
    QWidget,
    QSizePolicy,
    QVBoxLayout,
)
from qdigitalmeter import QDigitalMeter

from lisp.backend.audio_utils import slider_to_fader, fader_to_slider
from lisp.core.signal import Connection
from lisp.core.util import strtime
from lisp.cues.cue import CueState
from lisp.cues.cue_time import CueTime
from lisp.cues.media_cue import MediaCue
from lisp.plugins.cart_layout.page_widget import CartPageWidget
from lisp.ui import themes
from lisp.ui.icons import IconTheme
from lisp.ui.ui_utils import css_to_dict, dict_to_css, translate
from lisp.ui.widgets import QClickLabel, QClickSlider
from lisp.ui.widgets.target_warning import paint_invalid_target_badge
from lisp import ICON_THEMES_DIR


_DIM_ICON_SIZE = 64  # px; cart buttons render at <= 48px


def _dim_icon(icon):
    """Return a copy of `icon` rendered at 40% opacity.

    Qt's QIcon does not respect parent widget opacity or
    stylesheet `opacity:` rules, so we composite a new pixmap
    at half opacity and wrap it in a fresh QIcon. Rendered at
    _DIM_ICON_SIZE; QPushButton scales smoothly on display.
    """
    source = icon.pixmap(QSize(_DIM_ICON_SIZE, _DIM_ICON_SIZE))
    result = QPixmap(source.size())
    result.fill(Qt.transparent)
    painter = QPainter(result)
    painter.setOpacity(0.4)
    painter.drawPixmap(0, 0, source)
    painter.end()
    return QIcon(result)


def _resolve_cart_stylesheet(cue) -> str:
    """Build the stylesheet string for a cart cue widget.

    Themed cues (``color_name`` set) get the active theme's hex
    injected as the ``background`` key. Legacy cues pass through.
    Other CSS properties (color, font-size) are preserved verbatim.
    """
    if not getattr(cue, "color_name", ""):
        return cue.stylesheet or ""
    css = css_to_dict(cue.stylesheet or "")
    css["background"] = themes.cue_color_hex(cue.color_name)
    return dict_to_css(css)


class CueWidget(QWidget):
    ICON_SIZE = 14
    SLIDER_RANGE = 1000

    contextMenuRequested = pyqtSignal(QPoint)
    cueExecuted = pyqtSignal(object)
    selectedChanged = pyqtSignal()
    exclusiveSelectRequested = pyqtSignal(object)

    def __init__(self, cue, **kwargs):
        super().__init__(**kwargs)
        self._cue = None
        self._selected = False
        self._accurateTiming = False
        self._countdownMode = True
        self._showDBMeter = False
        self._showVolume = False

        # Dim-icon variants are constructed on demand by `_dim_icon`
        # (it composites a fresh pixmap). Without caching, each
        # `_updateStyle` rebuild for a disabled cue allocates a new
        # `QIcon`, which (a) is wasted work, and (b) breaks identity
        # comparison against `IconTheme.get(...)` for any tool that
        # reads `nameButton._icon`. Keyed by the source icon's id —
        # `IconTheme` caches its returns, so the key is stable.
        self._dimIconCache: dict = {}

        self._dBMeterElement = None
        self._volumeElement = None
        self._fadeElement = None

        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setLayout(QVBoxLayout())

        self.layout().setContentsMargins(0, 0, 0, 0)
        self.layout().setSpacing(2)

        self.hLayout = QHBoxLayout()
        self.hLayout.setContentsMargins(0, 0, 0, 0)
        self.hLayout.setSpacing(2)
        self.layout().addLayout(self.hLayout, 4)

        self.nameButton = QClickLabel(self)
        self.nameButton.setObjectName("ButtonCueWidget")
        self.nameButton.setWordWrap(True)
        self.nameButton.setAlignment(Qt.AlignCenter)
        self.nameButton.setFocusPolicy(Qt.NoFocus)
        self.nameButton.clicked.connect(self._clicked)
        self.nameButton.setSizePolicy(
            QSizePolicy.Ignored, QSizePolicy.Preferred
        )
        self.hLayout.addWidget(self.nameButton, 5)

        self.statusIcon = QLabel(self.nameButton)
        self.statusIcon.setStyleSheet("background-color: transparent")
        self.statusIcon.setPixmap(
            IconTheme.get("led-off").pixmap(CueWidget.ICON_SIZE)
        )

        self.targetWarning = QLabel(self.nameButton)
        self.targetWarning.setStyleSheet("background-color: transparent")
        self.targetWarning.setPixmap(
            self._make_target_badge_pixmap(CueWidget.ICON_SIZE)
        )
        self.targetWarning.setVisible(False)

        self.seekSlider = QClickSlider(self.nameButton)
        self.seekSlider.setOrientation(Qt.Horizontal)
        self.seekSlider.setFocusPolicy(Qt.NoFocus)
        self.seekSlider.setVisible(False)

        self.volumeSlider = QClickSlider(self.nameButton)
        self.volumeSlider.setObjectName("VolumeSlider")
        self.volumeSlider.setOrientation(Qt.Vertical)
        self.volumeSlider.setFocusPolicy(Qt.NoFocus)
        self.volumeSlider.setRange(0, CueWidget.SLIDER_RANGE)
        self.volumeSlider.setPageStep(10)
        self.volumeSlider.valueChanged.connect(
            self._changeVolume, Qt.DirectConnection
        )
        self.volumeSlider.setVisible(False)

        self.dbMeter = QDigitalMeter(self)
        self.dbMeter.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        self.dbMeter.setVisible(False)

        self.timeBar = QProgressBar(self)
        self.timeBar.setTextVisible(False)
        self.timeBar.setLayout(QHBoxLayout())
        self.timeBar.layout().setContentsMargins(0, 0, 0, 0)
        self.timeDisplay = QLCDNumber(self.timeBar)
        self.timeDisplay.setStyleSheet("background-color: transparent")
        self.timeDisplay.setSegmentStyle(QLCDNumber.Flat)
        self.timeDisplay.setDigitCount(8)
        self.timeDisplay.display("00:00:00")
        self.timeBar.layout().addWidget(self.timeDisplay)
        self.timeBar.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.timeBar.setVisible(False)

        self._setCue(cue)

    @property
    def cue(self):
        return self._cue

    @property
    def selected(self):
        return self._selected

    @selected.setter
    def selected(self, value):
        value = bool(value)
        if value == self._selected:
            return
        self._selected = value
        # Show the selection via stylesheet/qproperties
        self.nameButton.setProperty("selected", self.selected)
        self.nameButton.style().unpolish(self.nameButton)
        self.nameButton.style().polish(self.nameButton)
        self.selectedChanged.emit()

    def contextMenuEvent(self, event):
        self.contextMenuRequested.emit(event.globalPos())

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.LeftButton and (
            event.modifiers() == Qt.ControlModifier
            or event.modifiers() == Qt.ShiftModifier
        ):
            mime_data = QMimeData()
            mime_data.setText(CartPageWidget.DRAG_MAGIC)

            drag = QDrag(self)
            drag.setMimeData(mime_data)
            drag.setPixmap(self.grab(self.rect()))

            if event.modifiers() == Qt.ControlModifier:
                drag.exec_(Qt.CopyAction)
            else:
                drag.exec_(Qt.MoveAction)

    def setCountdownMode(self, mode):
        self._countdownMode = mode
        self._updateTime(self._cue.current_time(), True)

    def showAccurateTiming(self, enable):
        self._accurateTiming = enable
        if self._cue.state & CueState.Pause:
            self._updateTime(self._cue.current_time(), True)
        elif not self._cue.state & CueState.Running:
            self._updateDuration(self._cue.duration)

    def showSeekSlider(self, visible):
        if isinstance(self._cue, MediaCue):
            self.seekSlider.setVisible(visible)
            self.update()

    def showDBMeters(self, visible):
        if isinstance(self._cue, MediaCue):
            self._showDBMeter = visible

            if self._dBMeterElement is not None:
                self._dBMeterElement.level_ready.disconnect(self.dbMeter.plot)
                self._dBMeterElement = None

            if visible:
                self._dBMeterElement = self._cue.media.element("DbMeter")
                if self._dBMeterElement is not None:
                    self._dBMeterElement.level_ready.connect(
                        self.dbMeter.plot, Connection.QtQueued
                    )

                self.hLayout.insertWidget(2, self.dbMeter, 1)
                self.dbMeter.show()
            else:
                self.hLayout.removeWidget(self.dbMeter)
                self.dbMeter.hide()

            self.update()

    def showVolumeSlider(self, visible):
        if isinstance(self._cue, MediaCue):
            self._showVolume = visible

            if self._volumeElement is not None:
                self._volumeElement.changed("volume").disconnect(
                    self.resetVolume
                )
                self._volumeElement = None

            if visible:
                self.volumeSlider.setEnabled(self._cue.state & CueState.Running)
                self._volumeElement = self._cue.media.element("Volume")
                if self._volumeElement is not None:
                    self.resetVolume()
                    self._volumeElement.changed("volume").connect(
                        self.resetVolume, Connection.QtQueued
                    )

                self.hLayout.insertWidget(1, self.volumeSlider, 1)
                self.volumeSlider.show()
            else:
                self.hLayout.removeWidget(self.volumeSlider)
                self.volumeSlider.hide()

            self.update()

    def resetVolume(self):
        if self._volumeElement is not None:
            self.volumeSlider.setValue(
                round(
                    fader_to_slider(self._volumeElement.volume)
                    * CueWidget.SLIDER_RANGE
                )
            )

    def _setCue(self, cue):
        self._cue = cue

        # Cue properties changes
        self._cue.changed("name").connect(self._updateName, Connection.QtQueued)
        self._cue.changed("stylesheet").connect(
            self._updateStyle, Connection.QtQueued
        )
        self._cue.changed("color_name").connect(
            self._updateStyle, Connection.QtQueued
        )
        # Effective_disabled may flip via the cue's own `disabled`
        # or via any ancestor group's. Subscribe to the full chain:
        # own `disabled`, own `group_id` (to re-walk ancestors when
        # re-parented), and every ancestor group's `disabled`. The
        # ancestor subscriptions are (re)wired via `_wire_ancestor_disable`.
        self._cue.changed("disabled").connect(
            self._updateStyle, Connection.QtQueued
        )
        self._cue.changed("group_id").connect(
            self._onGroupIdChanged, Connection.QtQueued
        )
        # `_updateStyle` reads `self._cue.icon` to choose the cart
        # button glyph; without an icon-change subscription, the
        # cell stays frozen on its old icon until _setCue runs again
        # (i.e., until the session reloads).
        self._cue.changed("icon").connect(
            self._updateStyle, Connection.QtQueued
        )
        self._wire_ancestor_disable()
        # Repaint and refresh tooltip when target validity flips.
        # Only cues that mix in TargetingCue have this property; guard
        # with a property-name check so non-target cues are unaffected.
        if "invalid_target" in self._cue.properties_names():
            self._cue.changed("invalid_target").connect(
                self._onInvalidTargetChanged, Connection.QtQueued
            )
            self._onInvalidTargetChanged(self._cue.invalid_target)
        self._cue.changed("duration").connect(
            self._updateDuration, Connection.QtQueued
        )
        self._cue.changed("description").connect(
            self._updateDescription, Connection.QtQueued
        )

        # FadeOut start/end
        self._cue.fadein_start.connect(self._enterFadein, Connection.QtQueued)
        self._cue.fadein_end.connect(self._exitFade, Connection.QtQueued)

        # FadeIn start/end
        self._cue.fadeout_start.connect(self._enterFadeout, Connection.QtQueued)
        self._cue.fadeout_end.connect(self._exitFade, Connection.QtQueued)

        # Cue status changed
        self._cue.interrupted.connect(self._statusStopped, Connection.QtQueued)
        self._cue.started.connect(self._statusPlaying, Connection.QtQueued)
        self._cue.stopped.connect(self._statusStopped, Connection.QtQueued)
        self._cue.paused.connect(self._statusPaused, Connection.QtQueued)
        self._cue.error.connect(self._statusError, Connection.QtQueued)
        self._cue.end.connect(self._statusStopped, Connection.QtQueued)
        # Hibernating is a dedicated status. awoken is intentionally
        # NOT wired here — the subsequent started/stopped/interrupted
        # signal updates the icon to the actual destination state
        # (wiring awoken would race with _statusPlaying on resume).
        self._cue.hibernated.connect(
            self._statusHibernating, Connection.QtQueued
        )

        # Media cues features dBMeter and seekSlider
        if isinstance(cue, MediaCue):
            self._cue.media.elements_changed.connect(
                self._mediaUpdated, Connection.QtQueued
            )

            self._cue.paused.connect(self.dbMeter.reset, Connection.QtQueued)
            self._cue.stopped.connect(self.dbMeter.reset, Connection.QtQueued)
            self._cue.end.connect(self.dbMeter.reset, Connection.QtQueued)
            self._cue.error.connect(self.dbMeter.reset, Connection.QtQueued)

            self.seekSlider.sliderMoved.connect(self._cue.media.seek)
            self.seekSlider.sliderJumped.connect(self._cue.media.seek)

        self._cueTime = CueTime(self._cue)
        self._cueTime.notify.connect(self._updateTime, Connection.QtQueued)

        self._updateName(cue.name)
        self._updateStyle()
        self._updateDuration(self._cue.duration)

    def _mediaUpdated(self):
        self.showDBMeters(self._showDBMeter)
        self.showVolumeSlider(self._showVolume)

    def _updateName(self, name):
        self.nameButton.setText(name)

    def _updateDescription(self, description):
        self.nameButton.setToolTip(description)

    @staticmethod
    def _make_target_badge_pixmap(size):
        """Create a fixed-size pixmap of the warning badge."""
        from PyQt5.QtCore import QRect
        from PyQt5.QtGui import QPainter, QPixmap

        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        try:
            paint_invalid_target_badge(painter, QRect(0, 0, size, size))
        finally:
            painter.end()
        return pixmap

    def _invalidTargetTooltip(self):
        """Return the i18n string explaining the current invalid state."""
        if "targets" in self._cue.properties_names():
            return translate(
                "TargetingCue",
                "Collection has invalid target(s)",
            )
        target_id = getattr(self._cue, "target_id", "")
        if not target_id:
            return translate("TargetingCue", "Target cue is not set")
        return translate("TargetingCue", "Target cue is missing")

    def _onInvalidTargetChanged(self, invalid):
        """Show/hide the warning badge and refresh tooltip."""
        self.targetWarning.setVisible(bool(invalid))
        if invalid:
            self.targetWarning.setToolTip(self._invalidTargetTooltip())
        else:
            self.targetWarning.setToolTip("")

    def _changeVolume(self, new_volume):
        self._volumeElement.live_volume = slider_to_fader(
            new_volume / CueWidget.SLIDER_RANGE
        )

    def _clicked(self, event):
        if not (
            self.seekSlider.geometry().contains(event.pos())
            and self.seekSlider.isVisible()
        ):
            if event.button() != Qt.RightButton:
                if event.modifiers() == Qt.ShiftModifier:
                    # Replaces the legacy "open settings dialog" path.
                    # The inspector follows layout selection, so the
                    # widget asks the layout to make this cue the sole
                    # selection — Ctrl+click stays as additive toggle.
                    self.exclusiveSelectRequested.emit(self)
                elif event.modifiers() == Qt.ControlModifier:
                    self.selected = not self.selected
                elif event.modifiers() == Qt.NoModifier:
                    self._cue.execute()
                    self.cueExecuted.emit(self._cue)

    def _updateStyle(self, *_args):
        """Resolve and apply the cue widget's stylesheet.

        Reads from ``self._cue`` directly (themed colour resolved via
        ``_resolve_cart_stylesheet``); any positional arg is ignored,
        present only so this method is callable as a signal slot."""
        disabled = self._cue.effective_disabled
        stylesheet = _resolve_cart_stylesheet(self._cue)
        if disabled:
            # Append a dim overlay. Keep the original stylesheet so
            # colour/font selections survive re-enabling.
            stylesheet = (
                (stylesheet or "")
                + "\nQWidget { color: rgba(160, 160, 160, 0.5); }"
            )
        self.nameButton.setStyleSheet(stylesheet)
        icon = IconTheme.get(f"{self._cue.icon}-cart")
        if disabled:
            cached = self._dimIconCache.get(id(icon))
            if cached is None:
                cached = _dim_icon(icon)
                self._dimIconCache[id(icon)] = cached
            icon = cached
        self.nameButton.setIcon(icon)

    def _onGroupIdChanged(self, _value=None):
        """Handle re-parenting: rewire ancestor subscriptions and
        refresh dim state."""
        self._wire_ancestor_disable()
        self._updateStyle()

    def _wire_ancestor_disable(self):
        """Subscribe to `disabled` on every ancestor group so a
        parent-group toggle refreshes this cell's dim state.

        Rewired whenever the cell's own `group_id` changes.
        Connecting the same slot to the same signal twice is a
        no-op (the slot is identified by identity), so re-entry
        is safe. Weak-ref signal system means stale subscriptions
        to detached ancestors are collected automatically.
        """
        model = getattr(self._cue.app, "cue_model", None)
        if model is None:
            return
        gid = self._cue.group_id
        visited = set()
        while gid and gid not in visited:
            visited.add(gid)
            parent = model.get(gid)
            if parent is None:
                break
            parent.changed("disabled").connect(
                self._updateStyle, Connection.QtQueued
            )
            gid = parent.group_id

    def _enterFadein(self):
        p = self.timeDisplay.palette()
        p.setColor(p.WindowText, QColor(0, 255, 0))
        self.timeDisplay.setPalette(p)

    def _enterFadeout(self):
        p = self.timeDisplay.palette()
        p.setColor(p.WindowText, QColor(255, 50, 50))
        self.timeDisplay.setPalette(p)

    def _exitFade(self):
        self.timeDisplay.setPalette(self.timeBar.palette())

    def _statusStopped(self):
        self.statusIcon.setPixmap(
            IconTheme.get("led-off").pixmap(CueWidget.ICON_SIZE)
        )
        self.volumeSlider.setEnabled(False)
        self._updateTime(0, True)
        self.resetVolume()

    def _statusPlaying(self):
        self.statusIcon.setPixmap(
            IconTheme.get("led-running").pixmap(CueWidget.ICON_SIZE)
        )
        self.volumeSlider.setEnabled(True)

    def _statusPaused(self):
        self.statusIcon.setPixmap(
            IconTheme.get("led-pause").pixmap(CueWidget.ICON_SIZE)
        )
        self.volumeSlider.setEnabled(False)

    def _statusHibernating(self):
        self.statusIcon.setPixmap(
            IconTheme.get("led-hibernating").pixmap(CueWidget.ICON_SIZE)
        )
        self.volumeSlider.setEnabled(False)

    def _statusError(self):
        self.statusIcon.setPixmap(
            IconTheme.get("led-error").pixmap(CueWidget.ICON_SIZE)
        )
        self.volumeSlider.setEnabled(False)
        self.resetVolume()

    def _updateDuration(self, duration):
        # Update the maximum values of seek-slider and time progress-bar
        if duration > 0:
            if not self.timeBar.isVisible():
                self.layout().addWidget(self.timeBar, 1)
                self.timeBar.show()
            self.timeBar.setMaximum(duration)
            self.seekSlider.setMaximum(duration)
        elif duration == -1:
            # Indefinite — show time bar for elapsed display
            if not self.timeBar.isVisible():
                self.layout().addWidget(self.timeBar, 1)
                self.timeBar.show()
            self.timeBar.setMaximum(1)
            self.seekSlider.setMaximum(0)
        else:
            self.layout().removeWidget(self.timeBar)
            self.timeBar.hide()

        if not self._cue.state & CueState.Running:
            self._updateTime(duration, True)

    def _updateTime(self, time, ignore_visibility=False):
        if ignore_visibility or not self.visibleRegion().isEmpty():
            # If the given value is the duration or < 0 set the time to 0
            if time == self._cue.duration or time < 0:
                time = 0

            # Set the value the seek slider
            self.seekSlider.setValue(time)

            # If in count-down mode the widget will show the remaining
            # time — but not for indefinite cues (no known endpoint)
            if self._countdownMode and self._cue.duration > 0:
                time = self._cue.duration - time

            # Set the value of the timer progress-bar
            if self._cue.duration > 0:
                self.timeBar.setValue(time)

            # Show the time in the widget
            self.timeDisplay.display(
                strtime(time, accurate=self._accurateTiming)
            )

    def resizeEvent(self, event):
        self.update()

    def update(self):
        super().update()
        self.hLayout.activate()
        self.layout().activate()

        s_width = self.nameButton.width() - 8
        s_height = self.seekSlider.height()
        s_ypos = self.nameButton.height() - s_height

        self.seekSlider.setGeometry(4, s_ypos, s_width, s_height)
        self.statusIcon.setGeometry(
            4, 4, CueWidget.ICON_SIZE, CueWidget.ICON_SIZE
        )
        self.targetWarning.setGeometry(
            self.nameButton.width() - CueWidget.ICON_SIZE - 4,
            self.nameButton.height() - CueWidget.ICON_SIZE - 4,
            CueWidget.ICON_SIZE,
            CueWidget.ICON_SIZE,
        )
