# This file is part of Linux Show Player
#
# Copyright 2024 Francesco Ceruti <ceppofrancy@gmail.com>
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
import random
from threading import Lock

from PyQt5.QtCore import QT_TRANSLATE_NOOP, Qt
from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QVBoxLayout,
)

from lisp.core.clock import Clock_33
from lisp.core.properties import Property
from lisp.core.signal import Connection, Signal

from lisp.cues.cue import Cue, CueAction, CueState
from lisp.ui.settings.cue_settings import CueSettingsRegistry
from lisp.ui.settings.pages import SettingsPage
from lisp.ui.ui_utils import translate

logger = logging.getLogger(__name__)


class GroupCue(Cue):
    Name = QT_TRANSLATE_NOOP("CueName", "Group Cue")
    Category = QT_TRANSLATE_NOOP("CueCategory", "Action cues")

    CueActions = (
        CueAction.Default,
        CueAction.Start,
        CueAction.Stop,
        CueAction.Pause,
        CueAction.Resume,
        CueAction.Interrupt,
    )

    children = Property(default=[])
    group_mode = Property(default="parallel")
    loop = Property(default=False)
    crossfade = Property(default=0.0)
    shuffle = Property(default=False)
    icon = Property(default="cue-group")
    collapsed = Property(default=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = translate("CueName", self.Name)

        self._lock = Lock()
        self._playlist_index = 0
        self._crossfade_armed = False
        # Track which children have signal handlers connected
        self._connected_children = set()

        # Signal to relay crossfade arming to the main thread.
        # Clock_33 is a QTimer — callbacks must be added from the
        # Qt main thread.  __start__ runs in a worker thread, so
        # we use QtQueued to post to the event loop.
        self._request_crossfade_arm = Signal()
        self._request_crossfade_arm.connect(
            self._start_crossfade_monitor, Connection.QtQueued
        )

        # Shuffle when the user toggles the option on.
        self.property_changed.connect(self._on_property_changed)

    def _on_property_changed(self, _cue, name, value):
        """Shuffle when the shuffle option transitions to True.

        Fires during deserialization as well; that's harmless
        since _shuffle_on_load will run on session_loaded and
        double-shuffling remains uniformly random.
        """
        if (
            name == "shuffle"
            and value is True
            and self.group_mode == "playlist"
            and len(self.children) > 1
        ):
            self.shuffle_children()

    def shuffle_children(self):
        """Randomize children order and sync the layout.

        Mutates `self.children` in place (list of IDs) and moves
        each child cue in the active layout's model so the list
        view rows match the new playback order.
        """
        random.shuffle(self.children)
        self._resync_layout_to_children()

    def _resync_layout_to_children(self):
        """Move children in the layout model so row order follows
        `self.children`.  Uses the layout adapter's `move` API so
        `item_moved` is emitted and the tree view reorders rows.
        """
        layout = getattr(self.app, "layout", None)
        model = getattr(layout, "model", None) if layout else None
        if model is None:
            return
        # Children occupy contiguous slots starting right after
        # the group itself.  Walk the shuffled list and move each
        # child to its target slot; cues in between shift naturally.
        base = self.index + 1
        for offset, child_id in enumerate(self.children):
            child = self.app.cue_model.get(child_id)
            if child is None:
                continue
            target = base + offset
            if child.index != target:
                model.move(child.index, target)

    def _resolve_children(self):
        """Return the list of child Cue objects in order."""
        cues = []
        for child_id in self.children:
            cue = self.app.cue_model.get(child_id)
            if cue is not None:
                cues.append(cue)
        return cues

    def execute(self, action=CueAction.Default):
        # Block start if no children can be resolved
        if action in (
            CueAction.Default,
            CueAction.Start,
            CueAction.FadeInStart,
        ):
            if not self._resolve_children():
                return
        return super().execute(action)

    def __start__(self, fade=False):
        children = self._resolve_children()
        if not children:
            return False

        if self.group_mode == "parallel":
            return self._start_parallel(children, fade)
        else:
            return self._start_playlist(children, fade)

    def _start_parallel(self, children, fade):
        """Start all children simultaneously."""
        with self._lock:
            self._connected_children = set()

            for child in children:
                self._connect_child(child, parallel=True)

        for child in children:
            if child.state & CueState.IsPaused:
                if fade and child.fadein_duration > 0:
                    child.execute(CueAction.FadeInResume)
                else:
                    child.execute(CueAction.Resume)
            elif fade and child.fadein_duration > 0:
                child.execute(CueAction.FadeInStart)
            else:
                child.execute(CueAction.Start)

        return True

    def _start_playlist(self, children, fade):
        """Start first child in the playlist."""
        with self._lock:
            # If the current child is paused, resume from that
            # position instead of resetting to the beginning.
            idx = self._playlist_index
            resuming = (
                idx < len(children)
                and children[idx].state & CueState.IsPaused
            )
            if not resuming:
                idx = 0
                self._playlist_index = 0
            self._connected_children = set()
            self._crossfade_armed = False

        self._play_child_at(idx, children, fade)
        return True

    def _play_child_at(self, index, children=None, fade=False):
        """Start the child at the given playlist index."""
        if children is None:
            children = self._resolve_children()

        if not children:
            self._ended()
            return

        if index >= len(children):
            if self.loop:
                index = 0
            else:
                self._ended()
                return

        child = children[index]
        with self._lock:
            self._playlist_index = index
            self._connect_child(child, parallel=False)

        if child.state & CueState.IsPaused:
            if fade and child.fadein_duration > 0:
                child.execute(CueAction.FadeInResume)
            else:
                child.execute(CueAction.Resume)
        elif fade and child.fadein_duration > 0:
            child.execute(CueAction.FadeInStart)
        else:
            child.execute(CueAction.Start)

        self._arm_crossfade_if_needed(index, children)

    def _arm_crossfade_if_needed(self, index, children):
        """Arm the crossfade monitor if there is a next child."""
        has_next = index + 1 < len(children)
        can_loop = self.loop and len(children) > 1
        if self.crossfade > 0 and (has_next or can_loop):
            with self._lock:
                self._crossfade_armed = True
            # Relay to the main thread via QtQueued signal — Clock_33
            # is a QTimer whose callbacks must be added from the main
            # thread, but __start__ runs in a worker thread.
            self._request_crossfade_arm.emit()

    def _start_crossfade_monitor(self):
        """Add the crossfade check to the clock (main thread only)."""
        with self._lock:
            if not self._crossfade_armed:
                return
        Clock_33.add_callback(self._check_crossfade)

    def _connect_child(self, child, parallel):
        """Connect signal handlers to a child cue. Must hold _lock."""
        if parallel:
            child.end.connect(
                self._on_child_ended, Connection.QtQueued
            )
            child.stopped.connect(
                self._on_child_ended, Connection.QtQueued
            )
            child.interrupted.connect(
                self._on_child_ended, Connection.QtQueued
            )
            child.error.connect(
                self._on_child_ended, Connection.QtQueued
            )
        else:
            # Playlist: natural end advances, manual stop kills group
            child.end.connect(
                self._on_playlist_child_ended, Connection.QtQueued
            )
            child.stopped.connect(
                self._on_playlist_child_stopped, Connection.QtQueued
            )
            child.interrupted.connect(
                self._on_playlist_child_stopped, Connection.QtQueued
            )
            child.error.connect(
                self._on_playlist_child_stopped, Connection.QtQueued
            )
        self._connected_children.add(child.id)

    def _disconnect_child(self, child, parallel):
        """Disconnect signal handlers from a child cue."""
        if parallel:
            child.end.disconnect(self._on_child_ended)
            child.stopped.disconnect(self._on_child_ended)
            child.interrupted.disconnect(self._on_child_ended)
            child.error.disconnect(self._on_child_ended)
        else:
            child.end.disconnect(self._on_playlist_child_ended)
            child.stopped.disconnect(
                self._on_playlist_child_stopped
            )
            child.interrupted.disconnect(
                self._on_playlist_child_stopped
            )
            child.error.disconnect(
                self._on_playlist_child_stopped
            )
        with self._lock:
            self._connected_children.discard(child.id)

    def _disconnect_all_children(self):
        """Disconnect signal handlers from all connected children."""
        parallel = self.group_mode == "parallel"
        with self._lock:
            child_ids = set(self._connected_children)

        for child_id in child_ids:
            child = self.app.cue_model.get(child_id)
            if child is not None:
                self._disconnect_child(child, parallel)

    def _check_crossfade(self):
        """Clock callback: check if crossfade point is reached."""
        with self._lock:
            if not self._crossfade_armed:
                return
            index = self._playlist_index

        children = self._resolve_children()
        if not children or index >= len(children):
            self._stop_crossfade_monitor()
            return

        child = children[index]
        if not (child.state & CueState.Running):
            return

        if child.duration <= 0:
            return

        remaining_ms = child.duration - child.current_time()
        crossfade_ms = self.crossfade * 1000

        if remaining_ms <= crossfade_ms:
            self._stop_crossfade_monitor()

            # Disconnect the current child BEFORE fading it out,
            # so its `stopped` signal won't trigger
            # _on_playlist_child_stopped and kill the group.
            self._disconnect_child(child, parallel=False)

            # Fade out current child — temporarily set the
            # fade duration for the crossfade without permanently
            # modifying the child's property (which gets serialized).
            # Restore via a one-shot stopped handler so the
            # worker thread has read the value before we reset.
            orig_fadeout = child.fadeout_duration
            if child.fadeout_duration <= 0:
                child.fadeout_duration = self.crossfade

                def _restore_fadeout(cue, _orig=orig_fadeout):
                    cue.fadeout_duration = _orig
                    cue.stopped.disconnect(_restore_fadeout)

                child.stopped.connect(_restore_fadeout)
            child.execute(CueAction.FadeOutStop)

            # Start next child with fade in
            next_index = index + 1
            if next_index >= len(children) and self.loop:
                next_index = 0

            if next_index < len(children):
                next_child = children[next_index]
                with self._lock:
                    self._playlist_index = next_index
                    self._connect_child(
                        next_child, parallel=False
                    )

                orig_fadein = next_child.fadein_duration
                if next_child.fadein_duration <= 0:
                    next_child.fadein_duration = self.crossfade

                    def _restore_fadein(
                        cue, _orig=orig_fadein
                    ):
                        cue.fadein_duration = _orig
                        cue.started.disconnect(
                            _restore_fadein
                        )

                    next_child.started.connect(
                        _restore_fadein
                    )
                next_child.execute(CueAction.FadeInStart)

                # Re-arm crossfade for the next transition
                self._arm_crossfade_if_needed(
                    next_index, children
                )

    def _stop_crossfade_monitor(self):
        with self._lock:
            self._crossfade_armed = False
        try:
            Clock_33.remove_callback(self._check_crossfade)
        except Exception:
            pass

    def _on_child_ended(self, cue):
        """Parallel mode: track when all children have ended."""
        self._disconnect_child(cue, parallel=True)

        with self._lock:
            remaining = bool(self._connected_children)

        if not remaining and self.state & CueState.Running:
            self._ended()

    def _on_playlist_child_ended(self, cue):
        """Playlist mode: child finished naturally, advance."""
        self._disconnect_child(cue, parallel=False)

        if not (self.state & CueState.Running):
            return

        with self._lock:
            # If other children are still connected (crossfade
            # overlap), wait for them to finish too.
            if self._connected_children:
                return
            next_index = self._playlist_index + 1

        children = self._resolve_children()

        if next_index >= len(children):
            if self.loop:
                self._play_child_at(0, children)
            else:
                self._ended()
        else:
            self._play_child_at(next_index, children)

    def _on_playlist_child_stopped(self, cue):
        """Playlist mode: child was stopped/interrupted, stop group."""
        self._stop_crossfade_monitor()
        self._disconnect_all_children()

        if self.state & CueState.Running:
            self._ended()

    def __stop__(self, fade=False):
        self._stop_crossfade_monitor()
        self._disconnect_all_children()

        for child in self._resolve_children():
            if child.state & CueState.IsRunning:
                if fade:
                    child.execute(CueAction.FadeOutStop)
                else:
                    child.execute(CueAction.Stop)

        return True

    def __pause__(self, fade=False):
        self._stop_crossfade_monitor()

        for child in self._resolve_children():
            if child.state & CueState.Running:
                if fade:
                    child.execute(CueAction.FadeOutPause)
                else:
                    child.execute(CueAction.Pause)

        return True

    def __interrupt__(self, fade=False):
        self._stop_crossfade_monitor()
        self._disconnect_all_children()

        for child in self._resolve_children():
            if child.state & CueState.IsRunning:
                if fade:
                    child.execute(CueAction.FadeOutInterrupt)
                else:
                    child.execute(CueAction.Interrupt)

        return True


class GroupCueSettings(SettingsPage):
    Name = QT_TRANSLATE_NOOP("SettingsPageName", "Group Settings")

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.setLayout(QVBoxLayout())
        self.layout().setAlignment(Qt.AlignTop)

        self.group = QGroupBox(self)
        self.group.setLayout(QFormLayout())
        self.layout().addWidget(self.group)

        self.modeCombo = QComboBox(self.group)
        self.modeCombo.addItem(
            translate("GroupCue", "Parallel"), "parallel"
        )
        self.modeCombo.addItem(
            translate("GroupCue", "Playlist"), "playlist"
        )
        self.group.layout().addRow(
            translate("GroupCue", "Mode"), self.modeCombo
        )

        self.crossfadeSpin = QDoubleSpinBox(self.group)
        self.crossfadeSpin.setRange(0.0, 60.0)
        self.crossfadeSpin.setSingleStep(0.5)
        self.crossfadeSpin.setSuffix(" s")
        self.crossfadeSpin.setDecimals(1)
        self.group.layout().addRow(
            translate("GroupCue", "Crossfade"), self.crossfadeSpin
        )

        self.loopCheck = QCheckBox(self.group)
        self.group.layout().addRow(
            translate("GroupCue", "Loop"), self.loopCheck
        )

        self.shuffleCheck = QCheckBox(self.group)
        self.group.layout().addRow(
            translate("GroupCue", "Shuffle"), self.shuffleCheck
        )

        self.modeCombo.currentIndexChanged.connect(
            self._mode_changed
        )

        self.retranslateUi()

    def retranslateUi(self):
        self.group.setTitle(
            translate("GroupCue", "Group Settings")
        )

    def _mode_changed(self, index):
        is_playlist = self.modeCombo.currentData() == "playlist"
        self.crossfadeSpin.setEnabled(is_playlist)
        self.loopCheck.setEnabled(is_playlist)
        self.shuffleCheck.setEnabled(is_playlist)

    def enableCheck(self, enabled):
        self.setGroupEnabled(self.group, enabled)

    def loadSettings(self, settings):
        mode = settings.get("group_mode", "parallel")
        index = self.modeCombo.findData(mode)
        if index >= 0:
            self.modeCombo.setCurrentIndex(index)

        self.crossfadeSpin.setValue(settings.get("crossfade", 0.0))
        self.loopCheck.setChecked(settings.get("loop", False))
        self.shuffleCheck.setChecked(settings.get("shuffle", False))
        self._mode_changed(self.modeCombo.currentIndex())

    def getSettings(self):
        if self.isGroupEnabled(self.group):
            return {
                "group_mode": self.modeCombo.currentData(),
                "crossfade": self.crossfadeSpin.value(),
                "loop": self.loopCheck.isChecked(),
                "shuffle": self.shuffleCheck.isChecked(),
            }
        return {}


CueSettingsRegistry().add(GroupCueSettings, GroupCue)
