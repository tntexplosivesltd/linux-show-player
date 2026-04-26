# This file is part of Linux Show Player
#
# Copyright 2018 Francesco Ceruti <ceppofrancy@gmail.com>
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

from lisp.backend.media import Media, MediaState


class _DummyMedia(Media):
    """Minimal Media subclass that doesn't override arm methods,
    used to verify the abstract default behaviour.
    """

    def __init__(self):
        super().__init__()

    @property
    def state(self):
        return MediaState.Null

    def current_time(self):
        return 0

    def element(self, class_name):
        return None

    def input_uri(self):
        return None

    def pause(self):
        pass

    def play(self):
        pass

    def seek(self, position):
        pass

    def stop(self):
        pass


def test_prearm_default_returns_false():
    m = _DummyMedia()
    assert m.prearm() is False


def test_disarm_default_is_noop():
    m = _DummyMedia()
    m.disarm()  # should not raise


def test_reseek_default_is_noop():
    m = _DummyMedia()
    m.reseek(0)  # should not raise


def test_armed_signal_exists():
    m = _DummyMedia()
    assert hasattr(m, "armed")
    assert hasattr(m, "disarmed")
