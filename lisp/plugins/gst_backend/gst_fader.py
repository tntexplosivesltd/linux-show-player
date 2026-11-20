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

import logging
from functools import partial
from time import monotonic, perf_counter_ns
from typing import Union

from lisp.core.fade_functions import ntime, FadeInType, FadeOutType
from lisp.core.fader import BaseFader

logger = logging.getLogger(__name__)

# Seconds a fade waits, after its own duration, for a ramp that a
# stalled stream has not finished playing yet.
MAX_STREAM_LAG = 5


class GstFader(BaseFader):
    def __init__(self, target, attribute: str):
        super().__init__(target, attribute)
        self._start_time = -1
        self._to_value = None
        # The controller generation this fade's set() returned; None
        # when it anchored nothing (no-op fade, pipeline not playing).
        self._generation = None

    def _fade(
        self,
        duration: float,
        to_value: float,
        fade_type: Union[FadeInType, FadeOutType],
    ) -> bool:
        self._to_value = to_value
        self._generation = None
        base_value = getattr(self._target, self._attribute)
        value_diff = to_value - base_value

        if value_diff == 0:
            return True

        functor = fade_type.value
        steps = 100
        steps_duration = (duration * 1000) / steps
        control_points = {}

        for step in range(steps):
            control_points[step * steps_duration] = round(
                functor(
                    ntime(step, 0, steps - 1),
                    value_diff,
                    base_value,
                ),
                6,
            )

        controller = self._target.get_controller(self.attribute)
        self._generation = controller.set(control_points)

        self._running.wait(controller.delay / 1000)

        self._start_time = perf_counter_ns()

        self._running.wait(duration)
        self._wait_for_stream(controller)

    def _wait_for_stream(self, controller):
        """Wait, bounded, until the stream has played the whole ramp.

        The wait above runs on the wall clock, the ramp in stream time:
        when the sink stalled after play() (M74) the ramp started late,
        and pinning now would jump the level up mid-ramp.
        """
        deadline = monotonic() + MAX_STREAM_LAG
        while not self._running.is_set():
            remaining = controller.remaining(self._generation)
            left = deadline - monotonic()
            if not remaining or left <= 0:
                return
            self._running.wait(min(remaining / 1000, left, 0.1))

    def _after_fade(self, interrupted):
        generation, self._generation = self._generation, None
        to_value, self._to_value = self._to_value, None
        self._start_time = -1
        if generation is None:
            # Nothing anchored: the control source is not ours.
            return

        # A completed fade ends at its target even if the stream lagged
        # the wall clock and the ramp did not finish (or never started,
        # M74): clearing the points freezes the property at its last
        # applied value, which could leave a cue short or silent. An
        # interrupted fade keeps wherever it stopped. finish() does
        # nothing if a later fade or Volume.stop() (cue stopped or
        # ended mid-fade) has taken the controller over since: pinning
        # then would overwrite their level.
        apply = None
        if not interrupted:
            apply = partial(setattr, self._target, self._attribute, to_value)
        try:
            controller = self._target.get_controller(self.attribute)
            controller.finish(generation, apply)
        except Exception:
            logger.exception("Could not finish the fade on %s", self.attribute)

    def current_time(self):
        if self._start_time < 0:
            return 0

        return (perf_counter_ns() - self._start_time) // 1_000_000
