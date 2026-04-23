# This file is part of Linux Show Player
#
# Copyright 2026 Francesco Ceruti <ceppofrancy@gmail.com>
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

from PyQt5.QtCore import QT_TRANSLATE_NOOP, Qt
from PyQt5.QtWidgets import (
    QComboBox, QFormLayout, QGroupBox, QHBoxLayout, QLabel,
    QPushButton, QVBoxLayout, QWidget,
)

from lisp.application import Application
from lisp.core.decorators import async_function
from lisp.core.fade_functions import FadeOutType
from lisp.core.properties import Property
from lisp.cues.cue import Cue, CueAction
from lisp.plugins.action_cues._fader_coordinator import (
    build_affected_set,
    collect_live_faders,
    ParallelFadeRunner,
)
from lisp.ui.cuelistdialog import CueSelectDialog
from lisp.ui.settings.cue_settings import CueSettingsRegistry
from lisp.ui.settings.pages import SettingsPage
from lisp.ui.ui_utils import translate
from lisp.ui.widgets import FadeEdit

logger = logging.getLogger(__name__)


class StopCue(Cue):
    Name = QT_TRANSLATE_NOOP("CueName", "Fade & Stop")
    Category = QT_TRANSLATE_NOOP("CueCategory", "Action cues")

    target_id = Property()
    action = Property(default=CueAction.Stop.value)
    fade_type = Property(default=FadeOutType.Linear.name)
    icon = Property(default="action-stop")

    CueActions = (
        CueAction.Default,
        CueAction.Start,
        CueAction.Stop,
        CueAction.Interrupt,
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = translate("CueName", self.Name)

        # In-flight ParallelFadeRunner, if any. Set by __start__, cleared
        # on completion/abort. Used by __stop__ to cancel the fade.
        self._runner = None

        # Tracks what the auto-rename handler last wrote to `name`.
        # If `self.name` still matches this value, auto-management is
        # still "on" and a target/action change re-derives. If it
        # diverges (user typed a custom label, or a session load set a
        # non-auto name), we leave it alone.
        self._last_auto_name = self.name
        self.property_changed.connect(self._on_property_changed)

    def _on_property_changed(self, _cue, name, _value):
        if name not in ("target_id", "action"):
            return
        if self.name != self._last_auto_name:
            # User (or a prior session load) has customised the name —
            # don't overwrite it.
            return
        new_name = self._derive_name()
        self.name = new_name
        self._last_auto_name = new_name

    def _derive_name(self):
        """Return a descriptive name based on current target + action.

        Falls back to the class's default translated Name when no
        target is resolvable (unset, deleted, or pointing at a
        non-existent cue) — the generic label beats a nonsense
        "Fade and Stop ''".
        """
        target = self.app.cue_model.get(self.target_id)
        if target is None:
            return translate("CueName", self.Name)
        action = CueAction(self.action)
        verb = translate("CueAction", action.name)
        return f"Fade and {verb} '{target.name}'"

    def update_properties(self, properties):
        super().update_properties(properties)
        # Post-load reseed: if the loaded name matches what we'd
        # auto-derive now (i.e. the saved name was auto), treat
        # it as still auto-managed so future target/action edits
        # re-derive. If not, the user customised it — leave
        # `_last_auto_name` stale so the handler won't touch the
        # loaded name.
        if self.name == self._derive_name():
            self._last_auto_name = self.name

    def __start__(self, fade=False):
        target = self.app.cue_model.get(self.target_id)
        if target is None:
            logger.warning(
                "StopCue: target cue %r not found", self.target_id
            )
            self._error()
            return False

        affected = build_affected_set(target)
        faders = collect_live_faders(affected)

        if self.duration > 0 and faders:
            self._runner = ParallelFadeRunner(
                faders,
                to_value=0.0,
                curve=FadeOutType[self.fade_type],
                duration_seconds=self.duration / 1000,
            )
            self._run_fade_then_action(target)
            return True

        # Instant path: no fade to run, dispatch action synchronously.
        target.execute(CueAction(self.action))
        return False

    @async_function
    def _run_fade_then_action(self, target):
        """Drive the runner to completion (in a daemon thread), then
        dispatch the action. Skip dispatch if the runner was aborted.
        """
        try:
            completed = self._runner.run_until_complete()
            if not completed:
                return  # aborted — caller's __stop__ handled state
            target.execute(CueAction(self.action))
        except Exception:
            logger.exception("StopCue: error during fade-and-action")
            self._error()
            return
        finally:
            self._runner = None

        self._ended()

    def __stop__(self, fade=False):
        """Cancel the in-flight fade, if any.

        Does NOT re-start the target — "I changed my mind about fading"
        means "cancel the fade," not "put the audio back". The target
        stays wherever the partial fade left it.
        """
        runner = self._runner
        if runner is not None:
            runner.abort()
        return True

    __interrupt__ = __stop__

    def current_time(self):
        """Elapsed fade time in ms (delegates to the runner).

        The list-layout `CueTime` widget polls this to advance the
        countdown. Returns 0 when no fade is in flight.
        """
        runner = self._runner
        if runner is None:
            return 0
        return runner.current_time()


class StopCueSettings(SettingsPage):
    Name = QT_TRANSLATE_NOOP("SettingsPageName", "Fade & Stop Settings")
    SortOrder = 30

    SupportedActions = [
        CueAction.Stop,
        CueAction.Pause,
        CueAction.Interrupt,
    ]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.setLayout(QVBoxLayout())
        self.layout().setAlignment(Qt.AlignTop)
        self.layout().setContentsMargins(6, 6, 6, 6)
        self.layout().setSpacing(6)

        self.cue_id = ""
        # Exclude StopCues and ResumeCues from the target picker —
        # targeting another SFR-cue has no useful semantics: they aren't
        # MediaCues, no faders would be collected, and the instant path
        # would just re-fire the configured action on a non-playing
        # target. Symmetric with ResumeCueSettings' exclusion.
        from lisp.plugins.action_cues.resume_cue import ResumeCue
        all_cues = Application().cue_model.filter(Cue)
        targets = [
            c for c in all_cues
            if not isinstance(c, (StopCue, ResumeCue))
        ]
        self.cueDialog = CueSelectDialog(cues=targets, parent=self)

        # Combined Target + Action group: cue picker on the left, action
        # combo on the right. One group, one border, one title — less
        # visual weight than three stacked boxes.
        self.targetGroup = QGroupBox(self)
        targetLayout = QHBoxLayout(self.targetGroup)
        targetLayout.setContentsMargins(8, 6, 8, 6)
        targetLayout.setSpacing(12)

        # Left column: cue picker (label + button stacked)
        cueColumn = QVBoxLayout()
        cueColumn.setContentsMargins(0, 0, 0, 0)
        cueColumn.setSpacing(4)
        self.cueLabel = QLabel(self.targetGroup)
        self.cueLabel.setAlignment(Qt.AlignCenter)
        self.cueLabel.setStyleSheet("font-weight: bold;")
        self.cueButton = QPushButton(self.targetGroup)
        self.cueButton.clicked.connect(self.select_cue)
        cueColumn.addWidget(self.cueLabel)
        cueColumn.addWidget(self.cueButton)

        cueColumnWidget = QWidget(self.targetGroup)
        cueColumnWidget.setLayout(cueColumn)
        targetLayout.addWidget(cueColumnWidget, stretch=3)

        # Right column: action combo with its own sub-label
        actionColumn = QFormLayout()
        actionColumn.setContentsMargins(0, 0, 0, 0)
        actionColumn.setSpacing(4)
        self.actionLabel = QLabel(self.targetGroup)
        self.actionCombo = QComboBox(self.targetGroup)
        for a in self.SupportedActions:
            self.actionCombo.addItem(
                translate("CueAction", a.name), a.value,
            )
        actionColumn.addRow(self.actionLabel, self.actionCombo)

        actionColumnWidget = QWidget(self.targetGroup)
        actionColumnWidget.setLayout(actionColumn)
        targetLayout.addWidget(actionColumnWidget, stretch=2)

        self.layout().addWidget(self.targetGroup)

        # Fade settings (unchanged)
        self.fadeGroup = QGroupBox(self)
        fadeLayout = QVBoxLayout(self.fadeGroup)
        fadeLayout.setContentsMargins(8, 6, 8, 6)
        self.fadeEdit = FadeEdit(self.fadeGroup)
        fadeLayout.addWidget(self.fadeEdit)
        self.layout().addWidget(self.fadeGroup)

        self.retranslateUi()

    def retranslateUi(self):
        self.targetGroup.setTitle(translate("StopCue", "Target"))
        self.cueButton.setText(translate("StopCue", "Click to select"))
        self.cueLabel.setText(translate("StopCue", "Not selected"))
        self.actionLabel.setText(translate("StopCue", "Action:"))
        self.fadeGroup.setTitle(translate("StopCue", "Fade"))

    def select_cue(self):
        dialog = self.cueDialog
        if dialog.exec() == dialog.Accepted:
            selected = dialog.selected_cue()
            if selected is not None:
                self.cue_id = selected.id
                self.cueLabel.setText(selected.name)

    def enableCheck(self, enabled):
        self.setGroupEnabled(self.targetGroup, enabled)
        self.setGroupEnabled(self.fadeGroup, enabled)

    def getSettings(self):
        settings = {}
        if self.isGroupEnabled(self.targetGroup):
            settings["target_id"] = self.cue_id
            settings["action"] = self.actionCombo.currentData()
        if self.isGroupEnabled(self.fadeGroup):
            settings["duration"] = int(self.fadeEdit.duration() * 1000)
            settings["fade_type"] = self.fadeEdit.fadeType()
        return settings

    def loadSettings(self, settings):
        target = Application().cue_model.get(settings.get("target_id", ""))
        if target is not None:
            self.cue_id = settings["target_id"]
            self.cueLabel.setText(target.name)

        action_value = settings.get("action", CueAction.Stop.value)
        index = self.actionCombo.findData(action_value)
        if index >= 0:
            self.actionCombo.setCurrentIndex(index)

        self.fadeEdit.setDuration(settings.get("duration", 0) / 1000)
        self.fadeEdit.setFadeType(
            settings.get("fade_type", FadeOutType.Linear.name)
        )


CueSettingsRegistry().add(StopCueSettings, StopCue)
