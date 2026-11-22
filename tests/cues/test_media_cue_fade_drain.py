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

"""A cue's own fade-out ends with its picture drained to the screen.

The fade bakes alpha into frames that are pumped ahead of their time:
stopping the media the moment the fader reaches 0 drops the last,
darkest frames, and the projection cut from ~15 % straight to black.
After a completed fade-out MediaCue asks the media to drain its video
(media.drain_video) before it stops / pauses it.
"""

import pytest

from lisp.cues.cue import CueState
from tests.cues.media_fakes import make_media_cue


def _cue(mock_app, fade_completes=True):
    cue, media = make_media_cue(mock_app)
    cue.fadeout_duration = 1.0
    cue._state = CueState.Running
    for part in media.parts.values():
        part.fader.fade.return_value = fade_completes
    calls = []
    media.drain_video.side_effect = lambda *a, **k: calls.append("drain")
    media.stop.side_effect = lambda: calls.append("stop")
    media.pause.side_effect = lambda: calls.append("pause")
    return cue, calls


def _run(cue, method, fade):
    # The cue's caller holds the state lock around __stop__/__pause__.
    cue._st_lock.acquire()
    try:
        getattr(cue, method)(fade=fade)
    finally:
        cue._st_lock.release()


@pytest.mark.parametrize("method, action", [
    ("__stop__", "stop"),
    ("__pause__", "pause"),
])
def test_completed_fade_out_drains_before_the_action(mock_app, method,
                                                     action):
    cue, calls = _cue(mock_app)
    _run(cue, method, fade=True)
    assert calls == ["drain", action]


def test_interrupt_fade_drains_before_stopping(mock_app):
    cue, calls = _cue(mock_app)
    cue.fadeout_duration = 0
    cue._interrupt_fade_duration = lambda: 1.0
    _run(cue, "__interrupt__", fade=True)
    assert calls == ["drain", "stop"]


def test_interrupted_fade_out_does_not_drain(mock_app):
    cue, calls = _cue(mock_app, fade_completes=False)
    _run(cue, "__stop__", fade=True)
    assert calls == ["stop"]


def test_hard_stop_does_not_drain(mock_app):
    # No fade: the picture and the sound stop at once, as before.
    cue, calls = _cue(mock_app)
    _run(cue, "__stop__", fade=False)
    assert calls == ["stop"]


def test_drain_failure_still_stops(mock_app):
    cue, calls = _cue(mock_app)
    cue.media.drain_video.side_effect = RuntimeError("boom")
    _run(cue, "__stop__", fade=True)
    assert calls == ["stop"]


def test_second_stop_during_the_drain_cuts_at_once(mock_app):
    # The drain runs with the state lock released. A second Stop in
    # that time must cut, as a Stop mid-fade does: end the drain, and
    # never start a second (0 -> 0) fade-out of its own.
    import threading
    import time

    cue, calls = _cue(mock_app)
    draining = threading.Event()
    result = []

    def blocking_drain(abort=None, deadline=None):
        draining.set()
        result.append(abort.wait(timeout=2))  # True once aborted
        calls.append("drain")
        return False

    cue.media.drain_video.side_effect = blocking_drain
    first = threading.Thread(target=_run, args=(cue, "__stop__", True))
    first.start()
    assert draining.wait(timeout=2)
    t0 = time.monotonic()
    _run(cue, "__stop__", fade=True)  # the operator presses Stop again
    first.join(timeout=2)

    assert result == [True]  # the drain was told to stop waiting
    assert time.monotonic() - t0 < 1.0
    fades = sum(p.fader.fade.call_count for p in cue.media.parts.values())
    assert fades == len(cue.media.parts)  # the first fade only
    assert calls.count("drain") == 1
