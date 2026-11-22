"""M74: a fade-in start must begin silent on the elements that play.

MediaCue.__start__ zeroes the live volume/alpha, then media.play(). A
disarmed media (pipeline NULL, e.g. a playlist child the pre-arm
manager tore down) rebuilds its elements inside play(): the new
Volume came up at the saved level, the fader read base == target and
did nothing - the fade-in was skipped (playlist natural advance, the
original M74 symptom).
"""

import time
from unittest.mock import MagicMock

import pytest

from tests.cues.media_fakes import FakeElement as _Element
from tests.cues.media_fakes import make_media_cue


class _RebuildingVolume(_Element):
    """Rebuilds the media's elements the moment it is silenced: a
    pre-arm-thread rebuild landing in the middle of __start__."""

    def __init__(self, media):
        self._media = media
        self._live = 1.0
        super().__init__(live=1.0)

    @property
    def live_volume(self):
        return self._live

    @live_volume.setter
    def live_volume(self, value):
        self._live = value
        if value == 0 and self._media is not None:
            media, self._media = self._media, None
            media._build()
            media.elements_changed.emit(media)


def _wait_until(predicate, timeout=2.0):
    deadline = time.monotonic() + timeout
    while not predicate():
        assert time.monotonic() < deadline, "timed out waiting"
        time.sleep(0.005)


_cue = make_media_cue


class TestFadeInStartIsSilentOnTheElementsThatPlay:
    def test_kept_pipeline(self, mock_app):
        cue, media = _cue(mock_app, rebuild_on_play=False)

        cue.__start__(fade=True)

        assert media.played == [(0, 0)]

    def test_rebuilt_pipeline(self, mock_app):
        cue, media = _cue(mock_app, rebuild_on_play=True)

        cue.__start__(fade=True)

        # Zeroed before the new pipeline goes to PLAYING.
        assert media.played == [(0, 0)]

    def test_plain_start_keeps_the_saved_level(self, mock_app):
        cue, media = _cue(mock_app, rebuild_on_play=True)

        cue.__start__(fade=False)

        assert media.played == [(1.0, 1.0)]

    def test_later_rebuild_is_not_zeroed(self, mock_app):
        # Only the start's own play() is silenced: a rebuild after it
        # (e.g. a pipe edit) keeps the saved level.
        cue, media = _cue(mock_app, rebuild_on_play=False)
        cue.__start__(fade=True)

        media._build()
        media.elements_changed.emit(media)

        assert media.parts["Volume"].live_volume == 1.0
        assert media.parts["VideoAlpha"].live_alpha == 1.0

    def test_fade_runs_on_the_rebuilt_elements(self, mock_app):
        cue, media = _cue(mock_app, rebuild_on_play=True)
        old_fader = media.parts["Volume"].fader

        cue.__start__(fade=True)

        new_fader = media.parts["Volume"].fader
        _wait_until(lambda: new_fader.fade.called)
        old_fader.fade.assert_not_called()

    def test_rebuild_during_the_silencing_is_silenced(self, mock_app):
        # The flag goes up before the zeroing: a rebuild that lands
        # between them (pre-arm thread) must still start silent.
        cue, media = _cue(mock_app, rebuild_on_play=False)
        media.parts["Volume"] = _RebuildingVolume(media)
        media.elements_changed.emit(media)

        cue.__start__(fade=True)

        assert media.played == [(0, 0)]

    def test_failed_play_lowers_the_flag(self, mock_app):
        cue, media = _cue(mock_app, rebuild_on_play=False)
        media.fail_play = True

        with pytest.raises(RuntimeError):
            cue.__start__(fade=True)
        media._build()
        media.elements_changed.emit(media)

        assert media.parts["Volume"].live_volume == 1.0
        assert media.parts["VideoAlpha"].live_alpha == 1.0
