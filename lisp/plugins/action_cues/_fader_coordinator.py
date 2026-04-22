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
"""Shared fader-orchestration helpers for the Fade & Stop / Fade & Resume
action cues. Underscore prefix keeps this module out of ActionCues'
load_classes cue-registration loop.
"""

import logging
from threading import Thread

from lisp.cues.cue import CueState
from lisp.cues.media_cue import MediaCue

logger = logging.getLogger(__name__)


_FADEABLE_ELEMENTS = (
    ("Volume", "live_volume"),
    ("VideoAlpha", "live_alpha"),
)


def collect_live_faders(cues, states=CueState.IsRunning):
    """Return a list of Fader objects for cues whose state matches `states`.

    For each MediaCue in `cues` whose `state & states` is non-zero, ask
    its Volume / VideoAlpha elements for a fader on their live
    properties. Non-MediaCues and cues without the requisite elements
    contribute nothing.

    Default `states=CueState.IsRunning` matches StopCue's use case
    (fading things that are actively playing). ResumeCue passes
    `states=CueState.Pause | CueState.IsRunning` to pick up paused
    cues it's about to resume.
    """
    faders = []
    for cue in cues:
        if not (cue.state & states):
            continue
        if not isinstance(cue, MediaCue):
            continue
        media = getattr(cue, "media", None)
        if media is None:
            continue
        for element_name, fader_prop in _FADEABLE_ELEMENTS:
            element = media.element(element_name)
            if element is None:
                continue
            faders.append(element.get_fader(fader_prop))
    return faders


def build_affected_set(target):
    """Flatten target (and any nested GroupCues) to a list of leaf cues.

    GroupCue membership is resolved via `_resolve_children()`; nested
    groups are flattened recursively. The target itself is returned
    as a single-element list when it is not a GroupCue.
    """
    # Local import to avoid a circular import at module load time
    # (group_cue imports from cues.cue, and this module is imported
    # from stop_cue / resume_cue which live in the same package).
    from lisp.plugins.action_cues.group_cue import GroupCue

    if not isinstance(target, GroupCue):
        return [target]

    leaves = []
    for child in target._resolve_children():
        leaves.extend(build_affected_set(child))
    return leaves


class ParallelFadeRunner:
    """Drive a set of Faders concurrently to a target value.

    Each fader runs in its own daemon thread (Fader.fade is blocking).
    `run_until_complete()` joins all threads and returns True if the run
    completed, False if `abort()` was called. `abort()` calls `stop()`
    on each fader and flips a flag the return value reads.
    """

    def __init__(self, faders, to_value, curve, duration_seconds):
        self._faders = list(faders)
        self._to_value = to_value
        self._curve = curve
        self._duration_seconds = duration_seconds
        self._aborted = False
        self._threads = []

    def run_until_complete(self):
        """Start faders in parallel, join them, return True if not aborted."""
        for fader in self._faders:
            try:
                fader.prepare()
            except Exception:
                logger.exception(
                    "ParallelFadeRunner: fader.prepare() raised; continuing"
                )

        for fader in self._faders:
            t = Thread(
                target=self._run_single,
                args=(fader,),
                daemon=True,
            )
            t.start()
            self._threads.append(t)

        for t in self._threads:
            t.join()

        return not self._aborted

    def abort(self):
        """Cooperatively cancel the in-flight fades."""
        self._aborted = True
        for fader in self._faders:
            try:
                fader.stop()
            except Exception:
                logger.exception(
                    "ParallelFadeRunner: fader.stop() raised during abort"
                )

    def _run_single(self, fader):
        try:
            fader.fade(self._duration_seconds, self._to_value, self._curve)
        except Exception:
            logger.exception("ParallelFadeRunner: fader.fade() raised")

    def current_time(self):
        """Elapsed fade time in ms, taken from the first fader.

        All faders run in parallel with the same duration, so any one of
        them is representative. Returns 0 if the fader set is empty.
        """
        if not self._faders:
            return 0
        return self._faders[0].current_time()
