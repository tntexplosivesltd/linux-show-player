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
from lisp.core.fade_functions import FadeInType
from lisp.core.properties import Property
from lisp.core.util import rsetattr
from lisp.cues.cue import Cue, CueAction, CueState
from lisp.ui.ui_utils import translate

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
        # Implemented in Task 5.
        return False

    def _running_fallback(self, target):
        # Implemented in Task 4.
        return False
