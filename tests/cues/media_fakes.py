"""Fake media for MediaCue unit tests: no GStreamer, no audio device.

`FakeMedia` stands in for GstMedia: real `element()` lookups returning
`FakeElement`s, a recordable `play()`, and a mock for every other
attribute (signals the cue connects to, stop/pause...).
"""

from unittest.mock import MagicMock

from lisp.core.signal import Signal
from lisp.cues.media_cue import MediaCue


class FakeElement:
    def __init__(self, live, saved=1.0, attribute="live_volume"):
        setattr(self, attribute, live)
        self.volume = saved
        self.alpha = saved
        self.fader = MagicMock()

    def get_fader(self, attribute):
        return self.fader


class FakeMedia:
    """A media whose play() rebuilds its elements when asked to, the
    way GstMedia.play() runs __init_pipeline from NULL. Any other
    attribute (signals the cue connects to) is a mock."""

    def __init__(self, rebuild_on_play):
        self._mocks = {}
        self.elements_changed = Signal()
        self.rebuild_on_play = rebuild_on_play
        self.fail_play = False
        self.played = []
        self._build()

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return self._mocks.setdefault(name, MagicMock())

    def _build(self):
        self.parts = {
            "Volume": FakeElement(live=1.0),
            "VideoAlpha": FakeElement(live=1.0, attribute="live_alpha"),
        }

    def element(self, name):
        return self.parts.get(name)

    def play(self):
        if self.fail_play:
            raise RuntimeError("play failed")
        if self.rebuild_on_play:
            self._build()
            self.elements_changed.emit(self)
        self.played.append(
            (
                self.parts["Volume"].live_volume,
                self.parts["VideoAlpha"].live_alpha,
            )
        )


def make_media_cue(mock_app, rebuild_on_play=False):
    media = FakeMedia(rebuild_on_play)
    cue = MediaCue(mock_app, media)
    cue.fadein_duration = 1.0
    return cue, media
