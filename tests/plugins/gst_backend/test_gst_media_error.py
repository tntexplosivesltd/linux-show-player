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

"""GstMedia's ERROR branch must release per-element resources.

Regression for the compositor review (Phase 7, Tier 1 #1): VideoSink
registers with the projection compositor in play(); an ERROR that tore
down the pipeline without calling element.stop() left the registration
behind, so VideoExclusiveManager refused every later video cue.
"""

import wave
from unittest.mock import MagicMock, patch

import pytest

from lisp.backend.media import MediaState
from lisp.plugins.gst_backend import elements as gst_elements
from lisp.plugins.gst_backend import video_compositor as vc
from lisp.plugins.gst_backend.gi_repository import Gst
from lisp.plugins.gst_backend.gst_media import GstMedia
from lisp.plugins.gst_backend.video_exclusive import (
    VideoExclusiveManager,
    active_video_sinks,
)

_CM = "lisp.plugins.gst_backend.gst_backend.GstBackend.video_compositor"


@pytest.fixture(scope="module", autouse=True)
def load_elements():
    gst_elements.load()


@pytest.fixture(scope="module")
def short_wav(tmp_path_factory):
    path = tmp_path_factory.mktemp("media") / "tone.wav"
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(48000)
        w.writeframes(b"\x00\x00" * 48000)
    return path


def _error_message():
    message = MagicMock()
    message.type = Gst.MessageType.ERROR
    message.src = object()  # not the pipeline
    error = MagicMock()
    error.message = "simulated failure"
    message.parse_error.return_value = (error, "debug info")
    return message


def test_error_calls_stop_on_every_element(short_wav):
    media = GstMedia()
    media.pipe = ("UriInput", "AutoSink")
    media.elements[0].uri = f"file://{short_wav}"

    stopped = []
    for element in media.elements:
        element.stop = (lambda e=element: stopped.append(e))

    media._GstMedia__on_message(None, _error_message())

    assert stopped == list(media.elements)
    assert media.state == MediaState.Null


def test_error_still_emits_error_when_an_element_stop_raises(short_wav):
    media = GstMedia()
    media.pipe = ("UriInput", "AutoSink")
    media.elements[0].uri = f"file://{short_wav}"

    def boom():
        raise RuntimeError("element stop failed")

    media.elements[0].stop = boom
    received = []

    def on_error(m):
        received.append(m)

    media.error.connect(on_error)
    media._GstMedia__on_message(None, _error_message())

    assert received == [media]
    assert media.state == MediaState.Null


def test_error_releases_video_exclusivity(short_wav):
    """The regression itself, with no element stubbed: a real
    UriAvInput + VideoSink cue that errors must leave the active video
    sinks, unregister from the compositor once, and stop blocking the
    next video cue. Never leaves NULL, so no device is opened."""
    comp = MagicMock()
    comp.clock.return_value = Gst.SystemClock.obtain()
    comp.register.side_effect = lambda _sink: vc.Registration()

    def video_cue():
        media = GstMedia()
        media.pipe = ("UriAvInput", "VideoSink")
        media.elements[0].uri = f"file://{short_wav}"
        cue = MagicMock()
        cue.media = media
        return cue

    with patch(_CM, return_value=comp):
        failing, other = video_cue(), video_cue()
        sink = failing.media.element("VideoSink")
        sink.play()  # as GstMedia.play() does
        exclusive = VideoExclusiveManager(MagicMock())
        assert active_video_sinks.contains(sink)
        assert exclusive.is_start_blocked(other) is True

        failing.media._GstMedia__on_message(None, _error_message())

        assert not active_video_sinks.contains(sink)
        comp.unregister.assert_called_once_with(sink)
        assert exclusive.is_start_blocked(other) is False
