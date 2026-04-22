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

from PyQt5.QtCore import QT_TRANSLATE_NOOP

from lisp.core.decorators import async_function
from lisp.core.fade_functions import FadeOutType
from lisp.core.properties import Property
from lisp.cues.cue import Cue, CueAction
from lisp.plugins.action_cues._fader_coordinator import (
    build_affected_set,
    collect_live_faders,
    ParallelFadeRunner,
)
from lisp.ui.ui_utils import translate

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
