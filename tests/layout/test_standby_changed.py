# This file is part of Linux Show Player
#
# Copyright 2024 Francesco Ceruti <ceppofrancy@gmail.com>
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

from unittest.mock import MagicMock

from lisp.core.signal import Signal
from lisp.layout.cue_layout import CueLayout


class _StubLayout(CueLayout):
    NAME = "stub"

    @property
    def model(self):
        return None

    @property
    def view(self):
        return None

    def cues(self, cue_type=None):
        return iter([])

    def cue_at(self, index):
        raise IndexError

    def selected_cues(self, cue_type=None):
        return iter([])

    def invert_selection(self):
        pass

    def select_all(self, cue_type=None):
        pass

    def deselect_all(self, cue_type=None):
        pass


def test_cue_layout_has_standby_changed():
    """CueLayout subclasses inherit a standby_changed Signal instance."""
    layout = _StubLayout(MagicMock())
    assert hasattr(layout, "standby_changed")
    assert isinstance(layout.standby_changed, Signal)

    received = []

    def _handler(cue):
        received.append(cue)

    layout.standby_changed.connect(_handler)
    layout.standby_changed.emit(None)
    assert received == [None]


def test_standby_changed_emits_with_cue():
    """standby_changed can carry a non-None cue value."""
    layout = _StubLayout(MagicMock())

    received = []

    def _handler(cue):
        received.append(cue)

    layout.standby_changed.connect(_handler)

    sentinel = object()
    layout.standby_changed.emit(sentinel)
    assert received == [sentinel]
