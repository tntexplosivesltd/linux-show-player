# This file is part of Linux Show Player
#
# Copyright 2025 Thomas Sherlock
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

from concurrent.futures import ThreadPoolExecutor
from typing import Union

from lisp.core.fade_functions import FadeInType, FadeOutType


class FaderGroup:
    """Run multiple faders in parallel.

    Used by MediaCue to fade audio volume and video alpha
    simultaneously.  Each fader can target a different value
    (e.g. audio -> 0, video -> 0).

    The API mirrors BaseFader so MediaCue can treat a single
    fader and a group interchangeably.
    """

    def __init__(self, faders=None):
        self._faders = list(faders) if faders else []

    def __len__(self):
        return len(self._faders)

    def __bool__(self):
        return len(self._faders) > 0

    @property
    def faders(self):
        return self._faders

    def prepare(self):
        for fader in self._faders:
            fader.prepare()

    def fade(
        self,
        duration: float,
        to_values,
        fade_type: Union[FadeInType, FadeOutType],
    ) -> bool:
        """Fade all faders in parallel.

        :param duration: Fade duration in seconds
        :param to_values: List of target values, one per fader
        :param fade_type: The fade curve to use
        :return: True if all faders completed, False if any
                 were interrupted
        """
        if not self._faders:
            return True

        with ThreadPoolExecutor(
            max_workers=len(self._faders)
        ) as pool:
            futures = [
                pool.submit(
                    fader.fade, duration, to_value, fade_type
                )
                for fader, to_value in zip(
                    self._faders, to_values
                )
            ]

        return all(f.result() for f in futures)

    def stop(self):
        for fader in self._faders:
            fader.stop()

    def is_running(self) -> bool:
        return any(f.is_running() for f in self._faders)

    def current_time(self) -> int:
        if not self._faders:
            return 0
        return max(f.current_time() for f in self._faders)
