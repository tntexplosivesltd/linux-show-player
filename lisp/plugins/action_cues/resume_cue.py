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
    QGroupBox, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget,
)

from lisp.application import Application
from lisp.core.decorators import async_function
from lisp.core.fade_functions import FadeInType
from lisp.core.properties import Property
from lisp.core.util import rsetattr
from lisp.cues.cue import Cue, CueAction, CueState
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
from lisp.ui.widgets.fades import FadeComboBox

logger = logging.getLogger(__name__)


class ResumeCue(Cue):
    Name = QT_TRANSLATE_NOOP("CueName", "Fade & Resume")
    Category = QT_TRANSLATE_NOOP("CueCategory", "Action cues")

    target_id = Property()
    fade_type = Property(default=FadeInType.Linear.name)
    icon = Property(default="action-resume")

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

    def __start__(self, fade=False):
        target = self.app.cue_model.get(self.target_id)
        if target is None:
            logger.warning(
                "ResumeCue: target cue %r not found", self.target_id
            )
            self._error()
            return False

        state = target.state
        if state & CueState.Pause:
            return self._paused_path(target)
        if state & CueState.IsRunning:
            return self._running_fallback(target)

        # Stopped or Error — nothing sensible to resume.
        logger.warning(
            "ResumeCue: target %r is in state %r; cannot resume",
            self.target_id, state,
        )
        self._error()
        return False

    def _paused_path(self, target):
        """Target is Paused — zero faders, Resume, fade back up to 1.0."""
        affected = build_affected_set(target)
        faders = collect_live_faders(
            affected, states=CueState.Pause | CueState.IsRunning,
        )

        will_fade = self.duration > 0 and faders

        if will_fade:
            # Zero each fader's live property synchronously BEFORE dispatching
            # Resume, so the GStreamer pipeline reads gain=0 for the first
            # samples post-Resume. Prevents pops regardless of how the
            # target was paused (e.g. a plain Pause rather than a prior
            # Fade & Stop).
            for fader in faders:
                rsetattr(fader.target, fader.attribute, 0.0)

        target.execute(CueAction.Resume)

        if not will_fade:
            return False

        self._runner = ParallelFadeRunner(
            faders=faders,
            to_value=1.0,
            curve=FadeInType[self.fade_type],
            duration_seconds=self.duration / 1000,
        )
        self._run_fade(target=target)
        return True

    def _running_fallback(self, target):
        """Target is already running — fade faders up to 1.0, no Resume."""
        affected = build_affected_set(target)
        faders = collect_live_faders(affected, states=CueState.IsRunning)

        if self.duration <= 0 or not faders:
            return False  # nothing to do

        self._runner = ParallelFadeRunner(
            faders,
            to_value=1.0,
            curve=FadeInType[self.fade_type],
            duration_seconds=self.duration / 1000,
        )
        self._run_fade(target=target)
        return True

    @async_function
    def _run_fade(self, target):
        """Drive the runner to completion in a daemon thread.

        Shared by `_paused_path` (post-Resume fade-up) and
        `_running_fallback` (fade-up only). On completion or abort,
        clear `_runner` and call `_ended()`. Exceptions reach `_error()`.
        """
        try:
            completed = self._runner.run_until_complete()
            if not completed:
                return  # aborted — __stop__ handled state
        except Exception:
            logger.exception("ResumeCue: error during fade-up")
            self._error()
            return
        finally:
            self._runner = None

        self._ended()

    def __stop__(self, fade=False):
        """Cancel the in-flight fade, if any.

        Does NOT re-pause the target — "I changed my mind about fading in"
        does not mean "put the target back where it was". The target stays
        wherever the partial fade-up left it.
        """
        runner = self._runner
        if runner is not None:
            runner.abort()
        return True

    __interrupt__ = __stop__

    def current_time(self):
        """Elapsed fade time in ms (delegates to the runner).

        The list-layout CueTime widget polls this to advance the
        countdown. Returns 0 when no fade is in flight. Symmetric
        with StopCue.current_time().
        """
        runner = self._runner
        if runner is None:
            return 0
        return runner.current_time()


class ResumeCueSettings(SettingsPage):
    Name = QT_TRANSLATE_NOOP("SettingsPageName", "Fade & Resume Settings")
    SortOrder = 30  # Matches StopCueSettings so both sort together.

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.setLayout(QVBoxLayout())
        self.layout().setAlignment(Qt.AlignTop)
        self.layout().setContentsMargins(6, 6, 6, 6)
        self.layout().setSpacing(6)

        self.cue_id = ""
        # Exclude ResumeCue (and StopCue, by symmetry) from the target
        # picker — a ResumeCue targeting another SFR-cue has no useful
        # semantics, same as Part 1's self-filter for StopCue.
        from lisp.plugins.action_cues.stop_cue import StopCue
        all_cues = Application().cue_model.filter(Cue)
        targets = [
            c for c in all_cues
            if not isinstance(c, (ResumeCue, StopCue))
        ]
        self.cueDialog = CueSelectDialog(cues=targets, parent=self)

        # Target group: cue picker only (no action combo — verb is fixed).
        self.targetGroup = QGroupBox(self)
        targetLayout = QHBoxLayout(self.targetGroup)
        targetLayout.setContentsMargins(8, 6, 8, 6)
        targetLayout.setSpacing(12)

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
        targetLayout.addWidget(cueColumnWidget)

        self.layout().addWidget(self.targetGroup)

        # Fade settings — FadeIn mode so the combo icons match the verb.
        self.fadeGroup = QGroupBox(self)
        fadeLayout = QVBoxLayout(self.fadeGroup)
        fadeLayout.setContentsMargins(8, 6, 8, 6)
        self.fadeEdit = FadeEdit(
            self.fadeGroup, mode=FadeComboBox.Mode.FadeIn,
        )
        fadeLayout.addWidget(self.fadeEdit)
        self.layout().addWidget(self.fadeGroup)

        self.retranslateUi()

    def retranslateUi(self):
        self.targetGroup.setTitle(translate("ResumeCue", "Target"))
        self.cueButton.setText(translate("ResumeCue", "Click to select"))
        self.cueLabel.setText(translate("ResumeCue", "Not selected"))
        self.fadeGroup.setTitle(translate("ResumeCue", "Fade"))

    def select_cue(self):
        dlg = self.cueDialog
        opened = dlg.exec()
        if opened == dlg.Accepted:
            selected = dlg.selected_cue()
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
        if self.isGroupEnabled(self.fadeGroup):
            settings["duration"] = int(self.fadeEdit.duration() * 1000)
            settings["fade_type"] = self.fadeEdit.fadeType()
        return settings

    def loadSettings(self, settings):
        target = Application().cue_model.get(settings.get("target_id", ""))
        if target is not None:
            self.cue_id = settings["target_id"]
            self.cueLabel.setText(target.name)

        self.fadeEdit.setDuration(settings.get("duration", 0) / 1000)
        self.fadeEdit.setFadeType(
            settings.get("fade_type", FadeInType.Linear.name)
        )


CueSettingsRegistry().add(ResumeCueSettings, ResumeCue)
