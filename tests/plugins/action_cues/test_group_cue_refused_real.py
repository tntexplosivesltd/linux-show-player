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

"""H31 with real cues: children refused by the real `Cue.execute` gate
(the exclusive manager says blocked), the group following them through
its real, queued signal wiring."""

import pytest

from lisp.cues.cue import Cue, CueAction, CueState
from lisp.plugins.action_cues.group_cue import GroupCue

TIMEOUT_MS = 3000


class _RunCue(Cue):
    """Runs until stopped, or until the test ends it (`_ended`)."""

    CueActions = (
        CueAction.Start,
        CueAction.Stop,
        CueAction.Pause,
        CueAction.Resume,
        CueAction.Interrupt,
    )

    def __start__(self, fade=False):
        return True

    def __stop__(self, fade=False):
        return True

    def __pause__(self, fade=False):
        return True

    def __interrupt__(self, fade=False):
        pass


@pytest.fixture
def blocked(mock_app):
    """The cues the exclusive manager blocks; the group itself never."""
    cues = set()

    def is_start_blocked(cue, notify=True):
        return cue in cues

    mock_app.exclusive_manager.is_start_blocked.side_effect = (
        is_start_blocked
    )
    mock_app.video_exclusive_manager.is_start_blocked.return_value = False
    return cues


@pytest.fixture
def make_group(mock_app, blocked):
    made = []

    def make(mode, count):
        group = GroupCue(app=mock_app)
        children = [_RunCue(mock_app) for _ in range(count)]
        cues = {c.id: c for c in [group, *children]}
        mock_app.cue_model.get.side_effect = cues.get
        for child in children:
            child.group_id = group.id
        group.children = [c.id for c in children]
        group.group_mode = mode
        made.extend([group, *children])
        return group, children

    yield make

    for cue in made:
        if cue.state & (CueState.IsRunning | CueState.IsPaused):
            cue.interrupt()


def _state_is(cue, state):
    return lambda: cue.state == state


def test_parallel_group_ends_with_the_child_that_started(
    make_group, blocked, qtbot
):
    group, (a, b) = make_group("parallel", 2)
    blocked.add(b)

    group.execute(CueAction.Start)
    # The group goes Running on its own worker, after __start__ has
    # started the children on theirs: wait for both.
    qtbot.waitUntil(_state_is(group, CueState.Running), timeout=TIMEOUT_MS)
    qtbot.waitUntil(_state_is(a, CueState.Running), timeout=TIMEOUT_MS)
    assert b.state == CueState.Stop

    a._ended()

    qtbot.waitUntil(_state_is(group, CueState.Stop), timeout=TIMEOUT_MS)


def test_playlist_advance_skips_a_refused_child(
    make_group, blocked, qtbot
):
    group, (a, b, c) = make_group("playlist", 3)

    group.execute(CueAction.Start)
    qtbot.waitUntil(_state_is(group, CueState.Running), timeout=TIMEOUT_MS)
    qtbot.waitUntil(_state_is(a, CueState.Running), timeout=TIMEOUT_MS)
    blocked.add(b)

    a._ended()

    qtbot.waitUntil(_state_is(c, CueState.Running), timeout=TIMEOUT_MS)
    assert b.state == CueState.Stop
    c._ended()
    qtbot.waitUntil(_state_is(group, CueState.Stop), timeout=TIMEOUT_MS)


@pytest.mark.parametrize("mode", ["parallel", "playlist"])
def test_paused_group_resume_refused_stays_paused(
    make_group, blocked, qtbot, mode
):
    group, children = make_group(mode, 2)
    group.execute(CueAction.Start)
    qtbot.waitUntil(_state_is(group, CueState.Running), timeout=TIMEOUT_MS)
    playing = [c for c in children if c.state == CueState.Running]
    assert playing

    group.execute(CueAction.Pause)
    qtbot.waitUntil(_state_is(group, CueState.Pause), timeout=TIMEOUT_MS)
    for child in playing:
        qtbot.waitUntil(_state_is(child, CueState.Pause),
                        timeout=TIMEOUT_MS)
    blocked.update(playing)

    assert group.execute(CueAction.Default) is False
    assert group.state == CueState.Pause
    assert all(c.state == CueState.Pause for c in playing)

    blocked.clear()
    group.execute(CueAction.Default)
    qtbot.waitUntil(_state_is(group, CueState.Running), timeout=TIMEOUT_MS)
    for child in playing:
        qtbot.waitUntil(_state_is(child, CueState.Running),
                        timeout=TIMEOUT_MS)
