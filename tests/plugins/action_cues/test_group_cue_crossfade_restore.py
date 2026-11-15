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

The restore write is queued to the Qt main thread, so assertions on
the restored value wait for Qt events (`qtbot.waitUntil`).
"""

import gc
import threading
import time

import pytest

from lisp.cues.cue import Cue, CueAction, CueState
from lisp.plugins.action_cues.group_cue import GroupCue

CROSSFADE = 1.0
TIMEOUT = 3.0
TIMEOUT_MS = int(TIMEOUT * 1000)


class _FadeCue(Cue):
    """A real Cue that keeps running and models MediaCue's fade timing.

    - `__stop__(fade=True)` waits on `stop_gate`, reads
      `fadeout_duration` (MediaCue passes it to the fader), emits
      `fadeout_start` when it has a fader, then waits on `fade_gate`
      (the fade in progress).
    - `__start__` waits on `start_gate`. With a fader, the fade-in
      duration is NOT read there: MediaCue reads it in `_on_start_fade`,
      an async function that can run after `started`. `run_fade_in()`
      plays that part. Without a fader the cue only sees the duration
      inside its start (recorded in `start_read_fadein`).
    """

    CueActions = (
        CueAction.Start,
        CueAction.Stop,
        CueAction.FadeInStart,
        CueAction.FadeOutStop,
        CueAction.Interrupt,
    )

    def __init__(self, app, fader=True):
        super().__init__(app)
        self.fader = fader
        self.duration = 10000
        self.position = 0
        self.start_gate = threading.Event()
        self.start_gate.set()
        self.stop_gate = threading.Event()
        self.stop_gate.set()
        self.fade_gate = threading.Event()
        self.fade_gate.set()
        self.started_with_fade = None
        self.start_read_fadein = None
        self.read_fadeout = None
        self.read_fadein = None

    def _can_fade(self):
        return self.fader

    def current_time(self):
        return self.position

    def __start__(self, fade=False):
        self.start_gate.wait(TIMEOUT)
        self.started_with_fade = fade
        self.start_read_fadein = self.fadein_duration
        return True

    def __stop__(self, fade=False):
        self.stop_gate.wait(TIMEOUT)
        if fade:
            self.read_fadeout = self.fadeout_duration
            if self.read_fadeout > 0 and self.fader:
                self.fadeout_start.emit()
                self.fade_gate.wait(TIMEOUT)
        return True

    def run_fade_in(self):
        """MediaCue._on_start_fade: read the duration, then fade."""
        self.read_fadein = self.fadein_duration
        if self.read_fadein > 0 and self.fader:
            self.fadein_start.emit()


class _PlainCue(Cue):
    """A cue that can't take FadeInStart (like most action cues)."""

    CueActions = (CueAction.Start, CueAction.Stop)

    def __start__(self, fade=False):
        return True


def _wait_for(predicate, what):
    deadline = time.monotonic() + TIMEOUT
    while not predicate():
        if time.monotonic() > deadline:
            pytest.fail(f"timed out waiting for {what}")
        time.sleep(0.005)


class _Fired:
    """Named signal observer (a bare lambda would be weakly dropped)."""

    def __init__(self, signal):
        self.event = threading.Event()
        signal.connect(self.on_signal)

    def on_signal(self, *_args):
        self.event.set()

    def wait(self, what):
        if not self.event.wait(TIMEOUT):
            pytest.fail(f"timed out waiting for {what}")


class _PropertyWrites:
    """Records (name, value, thread) for every fade property change."""

    def __init__(self, cue):
        self.writes = []
        cue.property_changed.connect(self.on_changed)

    def on_changed(self, _cue, name, value):
        if name in ("fadein_duration", "fadeout_duration"):
            self.writes.append((name, value, threading.current_thread()))


@pytest.fixture
def make_playlist(mock_app):
    mock_app.exclusive_manager.is_start_blocked.return_value = False
    mock_app.video_exclusive_manager.is_start_blocked.return_value = False
    made = []

    def make(c2=None):
        group = GroupCue(app=mock_app)
        c1 = _FadeCue(mock_app)
        c2 = c2 if c2 is not None else _FadeCue(mock_app)
        cues = {group.id: group, c1.id: c1, c2.id: c2}
        mock_app.cue_model.get.side_effect = cues.get

        for child in (c1, c2):
            child.group_id = group.id
        group.children = [c1.id, c2.id]
        group.group_mode = "playlist"
        group.crossfade = CROSSFADE
        made.extend((c1, c2))
        return group, c1, c2

    yield make

    # Never leave a worker blocked on a gate.
    for child in made:
        for gate in ("start_gate", "stop_gate", "fade_gate"):
            if hasattr(child, gate):
                getattr(child, gate).set()


@pytest.fixture
def playlist(make_playlist):
    return make_playlist()


def _run_until_crossfade(group, c1, c2, expect_fadein_hold=True):
    """Start c1 as the group's current child and reach the crossfade.

    Both workers are held (c1's stop, c2's start) until the test
    releases them.
    """
    c1.execute(CueAction.Start)
    _wait_for(lambda: c1.state & CueState.Running, "c1 to run")

    with group._lock:
        group._playlist_index = 0
        group._crossfade_armed = True
        group._connect_child(c1, parallel=False)

    c1.stop_gate.clear()
    if hasattr(c2, "start_gate"):
        c2.start_gate.clear()

    c1.position = c1.duration - 500  # inside the 1 s crossfade
    group._check_crossfade()

    # The crossfade really engaged with the temporary durations.
    assert c1.fadeout_duration == CROSSFADE
    if expect_fadein_hold:
        assert c2.fadein_duration == CROSSFADE


class TestCrossfadeRestoreSurvivesGC:
    def test_fadeout_restored_after_gc(self, playlist, qtbot):
        group, c1, c2 = playlist
        stopped = _Fired(c1.stopped)

        _run_until_crossfade(group, c1, c2)
        gc.collect()

        c1.stop_gate.set()
        stopped.wait("c1.stopped")
        qtbot.waitUntil(lambda: c1.fadeout_duration == 0, timeout=TIMEOUT_MS)

        assert c1.read_fadeout == CROSSFADE
        assert c1.properties()["fadeout_duration"] == 0

    def test_fadein_restored_after_gc(self, playlist, qtbot):
        group, c1, c2 = playlist
        started = _Fired(c2.started)

        _run_until_crossfade(group, c1, c2)
        gc.collect()

        c2.start_gate.set()
        started.wait("c2.started")
        gc.collect()
        c2.run_fade_in()
        qtbot.waitUntil(lambda: c2.fadein_duration == 0, timeout=TIMEOUT_MS)

        assert c2.started_with_fade is True
        assert c2.read_fadein == CROSSFADE
        assert c2.properties()["fadein_duration"] == 0

    def test_fadein_not_restored_before_the_fade_reads_it(
        self, playlist, qtbot
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
        qtbot.wait(50)  # deliver any (wrongly) queued early restore

        c2.run_fade_in()

        assert c2.read_fadein == CROSSFADE
        qtbot.waitUntil(lambda: c2.fadein_duration == 0, timeout=TIMEOUT_MS)


class TestCrossfadeRestoreTiming:
    def test_restores_write_on_the_main_thread(self, playlist, qtbot):
        """Restores are triggered on worker threads, but the write must
        land on the main thread: property_changed listeners such as the
        inspector start Qt timers, which fails off the main thread."""
        group, c1, c2 = playlist
        c1_writes = _PropertyWrites(c1)
        c2_writes = _PropertyWrites(c2)
        started = _Fired(c2.started)

        _run_until_crossfade(group, c1, c2)
        c1.stop_gate.set()
        c2.start_gate.set()
        started.wait("c2.started")
        threading.Thread(target=c2.run_fade_in).start()
        qtbot.waitUntil(
            lambda: c1.fadeout_duration == 0 and c2.fadein_duration == 0,
            timeout=TIMEOUT_MS,
        )

        restores = [
            w for w in c1_writes.writes + c2_writes.writes if w[1] == 0
        ]
        assert len(restores) == 2
        assert all(
            thread is threading.main_thread() for _, _, thread in restores
        )

    def test_fadeout_restored_when_the_fade_starts(self, playlist, qtbot):
        """The stop worker reads fadeout_duration before fadeout_start,
        so the hold ends there, not after the whole crossfade."""
        group, c1, c2 = playlist
        c1.fade_gate.clear()  # keep c1 fading

        _run_until_crossfade(group, c1, c2)
        c1.stop_gate.set()
        qtbot.waitUntil(lambda: c1.fadeout_duration == 0, timeout=TIMEOUT_MS)

        assert c1.read_fadeout == CROSSFADE
        assert c1.state & CueState.Running  # still fading out

    def test_child_without_fader_restored_on_started(
        self, make_playlist, mock_app, qtbot
    ):
        """A child that can't fade never emits fadein_start; it sees the
        duration inside its start, so `started` ends the hold."""
        group, c1, c2 = make_playlist(_FadeCue(mock_app, fader=False))
        started = _Fired(c2.started)

        _run_until_crossfade(group, c1, c2)
        c2.start_gate.set()
        started.wait("c2.started")
        qtbot.waitUntil(lambda: c2.fadein_duration == 0, timeout=TIMEOUT_MS)

        assert c2.start_read_fadein == CROSSFADE
        assert c2.state & CueState.Running
        assert c2.properties()["fadein_duration"] == 0

    def test_child_without_fadein_action_is_not_held(
        self, make_playlist, mock_app
    ):
        """FadeInStart is ignored by a cue that doesn't list it, so a
        hold would never be released by a start. Don't hold at all."""
        group, c1, c2 = make_playlist(_PlainCue(mock_app))
        writes = _PropertyWrites(c2)

        _run_until_crossfade(group, c1, c2, expect_fadein_hold=False)

        assert c2.fadein_duration == 0
        assert writes.writes == []
        assert (c2.id, "fadein_duration") not in group._pending_restores


class TestCrossfadeRestoreEdgeCases:
    def test_group_stopped_mid_crossfade_restores_both(
        self, playlist, qtbot
    ):
        group, c1, c2 = playlist
        _run_until_crossfade(group, c1, c2)
        gc.collect()

        # Neither child has emitted anything yet.
        group.__stop__()

        qtbot.waitUntil(
            lambda: c1.fadeout_duration == 0 and c2.fadein_duration == 0,
            timeout=TIMEOUT_MS,
        )
        assert c1.properties()["fadeout_duration"] == 0
        assert c2.properties()["fadein_duration"] == 0
        assert group._pending_restores == {}

    def test_group_interrupted_mid_crossfade_restores_both(
        self, playlist, qtbot
    ):
        group, c1, c2 = playlist
        _run_until_crossfade(group, c1, c2)
        gc.collect()

        group.__interrupt__()

        qtbot.waitUntil(
            lambda: c1.fadeout_duration == 0 and c2.fadein_duration == 0,
            timeout=TIMEOUT_MS,
        )

    def test_next_child_start_blocked_restores_fadein(
        self, playlist, mock_app, qtbot
    ):
        """An exclusive cue blocks the incoming child: it never emits
        `started` or `fadein_start`, so nothing else would restore."""
        group, c1, c2 = playlist

        def blocked(cue):
            return cue is c2

        mock_app.exclusive_manager.is_start_blocked.side_effect = blocked
        _run_until_crossfade(group, c1, c2, expect_fadein_hold=False)
        gc.collect()

        qtbot.waitUntil(lambda: c2.fadein_duration == 0, timeout=TIMEOUT_MS)
        assert c2.properties()["fadein_duration"] == 0

    def test_outgoing_child_ends_instead_of_stopping(self, playlist, qtbot):
        """EOS can beat the fade-out: the child emits `end`, and the
        FadeOutStop then finds nothing running and emits no `stopped`.
        """
        group, c1, c2 = playlist
        _run_until_crossfade(group, c1, c2)
        gc.collect()

        c1._ended()

        qtbot.waitUntil(lambda: c1.fadeout_duration == 0, timeout=TIMEOUT_MS)

    def test_user_edit_during_crossfade_is_kept(self, playlist, qtbot):
        group, c1, c2 = playlist
        stopped = _Fired(c1.stopped)
        _run_until_crossfade(group, c1, c2)

        c1.fadeout_duration = 4.0  # operator edits it mid-crossfade
        c1.stop_gate.set()
        stopped.wait("c1.stopped")
        qtbot.wait(50)  # deliver the queued restore

        assert c1.fadeout_duration == 4.0

    def test_registry_empties_after_restores(self, playlist, qtbot):
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
        qtbot.waitUntil(
            lambda: c1.fadeout_duration == 0 and c2.fadein_duration == 0,
            timeout=TIMEOUT_MS,
        )
