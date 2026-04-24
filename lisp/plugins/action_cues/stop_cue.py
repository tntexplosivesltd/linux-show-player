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
from collections import namedtuple

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

# Duck-typed CueAction-like for the StopCue-local "Hibernate"
# option. Has .name and .value so the combo populator
# (`for a in SupportedActions: addItem(translate(..., a.name),
# a.value)`) handles it unchanged. Not a CueAction enum value —
# hibernation is StopCue-originated; targets only ever see Pause.
_ActionLike = namedtuple("_ActionLike", ["name", "value"])
HIBERNATE_ACTION = _ActionLike(name="Hibernate", value="Hibernate")


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

        # List of (cue, handler) pairs armed by _arm_hibernate_listener
        # when action=Hibernate. For single-target cases this is one
        # entry; GroupCue cascades add one per affected child (Task 6).
        # None = not armed.
        self._hib_handlers = None

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
        if self.action == HIBERNATE_ACTION.value:
            # "Hibernate" is StopCue-local, not a CueAction enum —
            # translate its label directly.
            verb = translate("CueAction", "Hibernate")
        else:
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

        # Arm the hibernate listener BEFORE any dispatch so the
        # pause-to-hibernate hop is race-free.
        if self.action == HIBERNATE_ACTION.value:
            self._arm_hibernate_listener(target)

        if self.duration > 0 and faders:
            self._runner = ParallelFadeRunner(
                faders,
                to_value=0.0,
                curve=FadeOutType[self.fade_type],
                duration_seconds=self.duration / 1000,
            )
            self._run_fade_then_action(target)
            return True

        # Instant path: no fade to run, dispatch action.
        # NOTE: Cue.pause() is @async_function — returns before the
        # target actually transitions and emits `paused`. We do NOT
        # disarm here; the handler's `fired` flag makes it
        # self-idempotent, and weak-ref cleanup disposes it when
        # StopCue is GC'd.
        self._dispatch_action(target)
        return False

    @async_function
    def _run_fade_then_action(self, target):
        """Drive the runner to completion (in a daemon thread), then
        dispatch the action. Skip dispatch if the runner was aborted.
        """
        try:
            completed = self._runner.run_until_complete()
            if not completed:
                # Fade aborted — disarm the hibernate listener so the
                # target isn't accidentally hibernated by a later
                # unrelated pause.
                self._disarm_hibernate_listener(target)
                return  # caller's __stop__ handled state
            # Dispatch Pause. Cue.pause() is @async_function — it
            # returns before the target transitions. We do NOT disarm
            # here (it would race with the pending paused emission).
            # The handler's `fired` flag makes it idempotent; weak-
            # ref cleanup disposes it when StopCue is GC'd.
            self._dispatch_action(target)
        except Exception:
            logger.exception("StopCue: error during fade-and-action")
            self._disarm_hibernate_listener(target)
            self._error()
            return
        finally:
            self._runner = None

        self._ended()

    def _arm_hibernate_listener(self, target):
        """Subscribe one-shot-style handlers to target.paused that flip
        the Hibernating bit on the target.

        Re-arming: always discards any previously-armed handlers
        (typically left behind by the non-disarming success path —
        the handler's `fired` flag is sticky across invocations, so
        stale handlers would no-op and block re-hibernation on reuse).

        Each handler uses a `fired` flag for idempotence; the actual
        signal disconnect happens in _disarm_hibernate_listener after
        emit returns — disconnecting from inside emit would mutate the
        slot dict mid-iteration and raise RuntimeError.

        Cascades listeners to GroupCue children by iterating a
        snapshot of cue_model and matching children via the
        `group_id` property.
        """
        # Discard any stale handlers from a previous invocation.
        self._disarm_hibernate_listener(target)

        self._hib_handlers = []

        def make_handler(cue):
            fired = [False]

            def handler(_emitter):
                if fired[0]:
                    return
                fired[0] = True
                cue._set_hibernated(True)
            return handler

        def connect(cue):
            h = make_handler(cue)
            cue.paused.connect(h)
            self._hib_handlers.append((cue, h))

        connect(target)

        # If target is a group (or any cue with children), arm each
        # direct child. Iterate a *snapshot* of cue_model so a
        # concurrent add/remove (via test harness, OSC, etc.) can't
        # raise "dictionary changed size during iteration".
        #
        # Only direct children are cascaded — grandchildren (if a
        # nested group is a child of this target) pick up their bit
        # through their own `paused` emission when the parent group's
        # cascade reaches them. If deeper nesting is ever added to
        # GroupCue, this may need to recurse.
        target_id = getattr(target, "id", None)
        if target_id:
            try:
                children_snapshot = list(self.app.cue_model)
            except TypeError:
                children_snapshot = []
            for child in children_snapshot:
                if child is target:
                    continue
                if getattr(child, "group_id", "") == target_id:
                    connect(child)

    def _disarm_hibernate_listener(self, _target):
        """Disconnect every armed hibernate listener (no-op if none)."""
        if self._hib_handlers is None:
            return
        for cue, handler in self._hib_handlers:
            try:
                cue.paused.disconnect(handler)
            except (TypeError, ValueError, RuntimeError):
                pass
        self._hib_handlers = None

    def _dispatch_action(self, target):
        """Dispatch the configured action. The Hibernate sentinel is
        translated to CueAction.Pause; the listener armed by
        _arm_hibernate_listener handles the bit flip."""
        if self.action == HIBERNATE_ACTION.value:
            target.execute(CueAction.Pause)
        else:
            target.execute(CueAction(self.action))

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
        HIBERNATE_ACTION,
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
