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
from lisp.plugins.action_cues._fader_coordinator import (
    build_affected_set,
    collect_live_faders,
    ParallelFadeRunner,
)
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
