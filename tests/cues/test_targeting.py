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

"""Unit tests for the TargetingCue mixin."""

from lisp.core.properties import Property
from lisp.core.signal import Signal
from lisp.cues.cue import Cue
from lisp.cues.targeting import TargetingCue


class _FakeCueModel:
    """Minimal in-memory cue model with the signals TargetingCue needs."""

    def __init__(self):
        self._cues = {}
        self.item_added = Signal()
        self.item_removed = Signal()

    def get(self, cue_id, default=None):
        return self._cues.get(cue_id, default)

    def add(self, cue):
        self._cues[cue.id] = cue
        self.item_added.emit(cue)

    def remove(self, cue):
        self._cues.pop(cue.id, None)
        self.item_removed.emit(cue)


def _make_app():
    """Build an app stub with a real signal-bearing cue_model."""
    class _App:
        pass
    a = _App()
    a.cue_model = _FakeCueModel()
    return a


class _TargetCue(TargetingCue, Cue):
    """Single-target cue used by the tests."""

    target_id = Property()


def test_empty_target_id_is_invalid():
    app = _make_app()
    cue = _TargetCue(app=app)
    assert cue.invalid_target is True


def test_valid_target_id_clears_invalid():
    app = _make_app()
    target = Cue(app=app)
    app.cue_model.add(target)

    cue = _TargetCue(app=app)
    cue.target_id = target.id

    assert cue.invalid_target is False


def test_invalid_target_signal_fires_on_change():
    app = _make_app()
    target = Cue(app=app)
    app.cue_model.add(target)

    cue = _TargetCue(app=app)

    fires = []
    def on_change(value):
        fires.append(value)
    cue.changed("invalid_target").connect(on_change)

    cue.target_id = target.id  # invalid -> valid
    assert fires == [False]

    app.cue_model.remove(target)  # valid -> invalid
    assert fires == [False, True]


def test_invalid_target_signal_does_not_fire_when_unchanged():
    app = _make_app()
    cue = _TargetCue(app=app)  # starts invalid (empty target_id)

    fires = []
    def on_change(value):
        fires.append(value)
    cue.changed("invalid_target").connect(on_change)

    # Add an unrelated cue. Mixin will recheck because invalid_target
    # is True; result is still True; no signal should fire.
    other = Cue(app=app)
    app.cue_model.add(other)

    assert fires == []


def test_dangling_target_after_re_add_becomes_valid():
    app = _make_app()
    target = Cue(app=app)
    app.cue_model.add(target)

    cue = _TargetCue(app=app)
    cue.target_id = target.id
    assert cue.invalid_target is False

    fires = []
    def on_change(value):
        fires.append(value)
    cue.changed("invalid_target").connect(on_change)

    app.cue_model.remove(target)
    assert cue.invalid_target is True

    # Re-add a cue with the same id (e.g. session reload).
    target2 = Cue(app=app, id=target.id)
    app.cue_model.add(target2)
    assert cue.invalid_target is False

    # Signal must fire on both transitions: valid -> invalid (remove)
    # and invalid -> valid (re-add).
    assert fires == [True, False]
