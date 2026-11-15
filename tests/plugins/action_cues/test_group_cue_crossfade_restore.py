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

"""H25: playlist crossfade must put the children's fade durations back.

The crossfade temporarily sets the outgoing child's `fadeout_duration`
and the incoming child's `fadein_duration` to the group's `crossfade`,
then restores them from one-shot signal handlers. `Signal` holds slots
by weak reference, so those handlers must be kept alive by the group,
or a garbage collection loses the restore and the crossfade value is
saved into the session.
"""

import gc
import threading
import time

import pytest

from lisp.cues.cue import Cue, CueAction, CueState
from lisp.plugins.action_cues.group_cue import GroupCue

CROSSFADE = 1.0
TIMEOUT = 3.0


class _FadeCue(Cue):
    """A real Cue that keeps running and models MediaCue's fade timing.

    - `__stop__(fade=True)` reads `fadeout_duration` (MediaCue passes it
      to the fader), then blocks on `stop_gate` like a fade in progress.
    - `__start__` blocks on `start_gate`. The fade-in duration is NOT
      read there: MediaCue reads it in `_on_start_fade`, an async
      function that can run after `started` is emitted. `run_fade_in()`
      plays that part, so a test can run it after `started`.
    """

    CueActions = (
        CueAction.Start,
        CueAction.Stop,
        CueAction.FadeInStart,
        CueAction.FadeOutStop,
        CueAction.Interrupt,
    )

    def __init__(self, app):
        super().__init__(app)
        self.duration = 10000
        self.position = 0
        self.start_gate = threading.Event()
        self.start_gate.set()
        self.stop_gate = threading.Event()
        self.stop_gate.set()
        self.started_with_fade = None
        self.read_fadeout = None
        self.read_fadein = None

    def current_time(self):
        return self.position

    def __start__(self, fade=False):
        self.start_gate.wait(TIMEOUT)
        self.started_with_fade = fade
        return True

    def __stop__(self, fade=False):
        if fade:
            self.read_fadeout = self.fadeout_duration
        self.stop_gate.wait(TIMEOUT)
        return True

    def run_fade_in(self):
        """MediaCue._on_start_fade: read the duration, then fade."""
        self.read_fadein = self.fadein_duration
        if self.read_fadein > 0:
            self.fadein_start.emit()


def _wait_for(predicate, what):
    deadline = time.monotonic() + TIMEOUT
    while not predicate():
        if time.monotonic() > deadline:
            pytest.fail(f"timed out waiting for {what}")
        time.sleep(0.005)


class _Fired:
    """Named signal observer (a bare lambda would be weakly dropped).

    Connected after the group's restore handler, so it runs after it.
    """

    def __init__(self, signal):
        self.event = threading.Event()
        signal.connect(self.on_signal)

    def on_signal(self, *_args):
        self.event.set()

    def wait(self, what):
        if not self.event.wait(TIMEOUT):
            pytest.fail(f"timed out waiting for {what}")


@pytest.fixture
def playlist(mock_app):
    mock_app.exclusive_manager.is_start_blocked.return_value = False
    mock_app.video_exclusive_manager.is_start_blocked.return_value = False

    group = GroupCue(app=mock_app)
    c1 = _FadeCue(mock_app)
    c2 = _FadeCue(mock_app)
    cues = {group.id: group, c1.id: c1, c2.id: c2}
    mock_app.cue_model.get.side_effect = cues.get

    for child in (c1, c2):
        child.group_id = group.id
    group.children = [c1.id, c2.id]
    group.group_mode = "playlist"
    group.crossfade = CROSSFADE

    yield group, c1, c2

    # Never leave a worker blocked on a gate.
    for child in (c1, c2):
        child.start_gate.set()
        child.stop_gate.set()


def _run_until_crossfade(group, c1, c2):
    """Start c1 as the group's current child and reach the crossfade."""
    c1.execute(CueAction.Start)
    _wait_for(lambda: c1.state & CueState.Running, "c1 to run")

    with group._lock:
        group._playlist_index = 0
        group._crossfade_armed = True
        group._connect_child(c1, parallel=False)

    # Hold both workers so nothing fires until the test says so.
    c1.stop_gate.clear()
    c2.start_gate.clear()

    c1.position = c1.duration - 500  # inside the 1 s crossfade
    group._check_crossfade()

    # The crossfade really engaged with the temporary durations.
    assert c1.fadeout_duration == CROSSFADE
    assert c2.fadein_duration == CROSSFADE


class TestCrossfadeRestoreSurvivesGC:
    def test_fadeout_restored_after_gc(self, playlist):
        group, c1, c2 = playlist
        stopped = _Fired(c1.stopped)

        _run_until_crossfade(group, c1, c2)
        gc.collect()

        c1.stop_gate.set()
        stopped.wait("c1.stopped")

        assert c1.read_fadeout == CROSSFADE
        assert c1.fadeout_duration == 0
        assert c1.properties()["fadeout_duration"] == 0

    def test_fadein_restored_after_gc(self, playlist):
        group, c1, c2 = playlist
        started = _Fired(c2.started)

        _run_until_crossfade(group, c1, c2)
        gc.collect()

        c2.start_gate.set()
        started.wait("c2.started")
        gc.collect()
        c2.run_fade_in()

        assert c2.started_with_fade is True
        assert c2.read_fadein == CROSSFADE
        assert c2.fadein_duration == 0
        assert c2.properties()["fadein_duration"] == 0

    def test_fadein_not_restored_before_the_fade_reads_it(
        self, playlist
    ):
        """MediaCue reads fadein_duration on its own thread, possibly
        after `started`. Restoring on `started` races that read and
        leaves the next child silent at volume 0 (the bug 6cec7266
        set out to fix)."""
        group, c1, c2 = playlist
        started = _Fired(c2.started)

        _run_until_crossfade(group, c1, c2)
        c2.start_gate.set()
        started.wait("c2.started")

        c2.run_fade_in()

        assert c2.read_fadein == CROSSFADE
        assert c2.fadein_duration == 0


class TestCrossfadeRestoreEdgeCases:
    def test_group_stopped_mid_crossfade_restores_both(self, playlist):
        group, c1, c2 = playlist
        _run_until_crossfade(group, c1, c2)
        gc.collect()

        # Neither child has emitted anything yet.
        group.__stop__()

        assert c1.fadeout_duration == 0
        assert c2.fadein_duration == 0
        assert c1.properties()["fadeout_duration"] == 0
        assert c2.properties()["fadein_duration"] == 0

    def test_group_interrupted_mid_crossfade_restores_both(
        self, playlist
    ):
        group, c1, c2 = playlist
        _run_until_crossfade(group, c1, c2)
        gc.collect()

        group.__interrupt__()

        assert c1.fadeout_duration == 0
        assert c2.fadein_duration == 0

    def test_next_child_start_blocked_restores_fadein(
        self, playlist, mock_app
    ):
        """An exclusive cue blocks the incoming child: it never emits
        `started` or `fadein_start`, so nothing else would restore."""
        group, c1, c2 = playlist

        def blocked(cue):
            return cue is c2

        mock_app.exclusive_manager.is_start_blocked.side_effect = blocked
        _run_until_crossfade_blocked(group, c1, c2)
        gc.collect()

        assert c2.fadein_duration == 0
        assert c2.properties()["fadein_duration"] == 0

    def test_outgoing_child_ends_instead_of_stopping(self, playlist):
        """EOS can beat the fade-out: the child emits `end`, and the
        FadeOutStop then finds nothing running and emits no `stopped`.
        """
        group, c1, c2 = playlist
        _run_until_crossfade(group, c1, c2)
        gc.collect()

        c1._ended()

        assert c1.fadeout_duration == 0

    def test_user_edit_during_crossfade_is_kept(self, playlist):
        group, c1, c2 = playlist
        stopped = _Fired(c1.stopped)
        _run_until_crossfade(group, c1, c2)

        c1.fadeout_duration = 4.0  # operator edits it mid-crossfade
        c1.stop_gate.set()
        stopped.wait("c1.stopped")

        assert c1.fadeout_duration == 4.0

    def test_registry_empties_after_restores(self, playlist):
        group, c1, c2 = playlist
        stopped = _Fired(c1.stopped)
        started = _Fired(c2.started)
        _run_until_crossfade(group, c1, c2)

        c1.stop_gate.set()
        c2.start_gate.set()
        stopped.wait("c1.stopped")
        started.wait("c2.started")
        c2.run_fade_in()

        assert group._pending_restores == {}


def _run_until_crossfade_blocked(group, c1, c2):
    """Like _run_until_crossfade, but c2's start is refused, so its
    temporary fadein_duration is not asserted mid-crossfade."""
    c1.execute(CueAction.Start)
    _wait_for(lambda: c1.state & CueState.Running, "c1 to run")
    with group._lock:
        group._playlist_index = 0
        group._crossfade_armed = True
        group._connect_child(c1, parallel=False)
    c1.position = c1.duration - 500
    group._check_crossfade()
