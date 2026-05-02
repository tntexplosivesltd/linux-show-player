# This file is part of Linux Show Player
#
# Copyright 2023 Francesco Ceruti <ceppofrancy@gmail.com>
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

import logging
import wave

import pytest

from lisp.backend.media import MediaState
from lisp.plugins.gst_backend import elements as gst_elements
from lisp.plugins.gst_backend.gst_media import GstMedia


@pytest.fixture(scope="module", autouse=True)
def load_elements():
    """Load GStreamer element classes into the registry."""
    gst_elements.load()


@pytest.fixture(scope="module")
def short_wav(tmp_path_factory):
    """Generate a 1-second 48kHz mono WAV. Returns absolute file path."""
    path = tmp_path_factory.mktemp("media") / "tone.wav"
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(48000)
        w.writeframes(b"\x00\x00" * 48000)
    return path


@pytest.fixture
def gst_media(short_wav):
    media = GstMedia()
    media.pipe = ("UriInput", "AutoSink")
    media.elements[0].uri = f"file://{short_wav}"
    yield media
    # Cleanup: ensure pipeline is in NULL when the test ends
    try:
        media.disarm()
    except Exception:
        pass


def test_prearm_from_null(gst_media):
    # After assigning media.pipe, GstMedia initialises to Ready
    assert gst_media.state == MediaState.Ready
    received = []

    def _handler(m):
        received.append(m)

    gst_media.armed.connect(_handler)
    assert gst_media.prearm() is True
    assert gst_media.state == MediaState.Armed
    assert len(received) == 1


def test_prearm_idempotent_when_already_armed(gst_media):
    gst_media.prearm()
    received = []

    def _handler(m):
        received.append(m)

    gst_media.armed.connect(_handler)
    assert gst_media.prearm() is True
    assert gst_media.state == MediaState.Armed
    assert received == []  # already-armed call should not re-fire


def test_disarm_from_armed(gst_media):
    gst_media.prearm()
    received = []

    def _handler(m):
        received.append(m)

    gst_media.disarmed.connect(_handler)
    gst_media.disarm()
    assert gst_media.state == MediaState.Null
    assert len(received) == 1


def test_disarm_when_not_armed_is_noop(gst_media):
    # Pipeline starts in Ready after pipe assignment; disarm on non-Armed is noop
    received = []

    def _handler(m):
        received.append(m)

    gst_media.disarmed.connect(_handler)
    gst_media.disarm()
    assert gst_media.state == MediaState.Ready
    assert received == []


def test_reseek_while_armed(gst_media):
    gst_media.prearm()
    gst_media.reseek(500)  # ms
    assert gst_media.state == MediaState.Armed


def test_stop_on_armed_disarms(gst_media):
    """stop() on an Armed pipeline must release resources via disarm,
    not silently no-op (regression guard for code review finding).
    """
    gst_media.prearm()
    assert gst_media.state == MediaState.Armed
    received = []

    def _handler(m):
        received.append(m)

    gst_media.disarmed.connect(_handler)
    gst_media.stop()
    assert gst_media.state == MediaState.Null
    assert len(received) == 1


def test_play_from_armed_skips_paused_transition(gst_media, monkeypatch):
    """Once armed, play() should go straight to PLAYING without a
    second PAUSED transition (that's the latency we're saving).
    """
    from lisp.plugins.gst_backend.gi_repository import Gst

    gst_media.prearm()
    assert gst_media.state == MediaState.Armed

    pipeline = gst_media._GstMedia__pipeline
    calls = []
    real_set_state = pipeline.set_state

    def recording_set_state(state):
        calls.append(state)
        return real_set_state(state)

    monkeypatch.setattr(pipeline, "set_state", recording_set_state)

    gst_media.play()

    # We should see exactly one set_state call, to PLAYING.
    # No additional PAUSED transition.
    assert calls == [Gst.State.PLAYING], (
        f"expected only PLAYING transition; got {calls}"
    )
    gst_media.stop()


def test_play_clears_armed_flag(gst_media):
    """After play() returns, the cue is no longer armed; state must
    report Playing, not Armed (regression guard against the state
    property override leaking through).
    """
    gst_media.prearm()
    assert gst_media.state == MediaState.Armed
    gst_media.play()
    assert gst_media.state == MediaState.Playing
    gst_media.stop()


def test_play_from_ready_still_prerolls(gst_media):
    """Regression: non-armed play() must still preroll itself.
    The fixture starts in Ready state (media.pipe = (...) triggers
    __init_pipeline → READY), so this verifies the existing path.
    """
    assert gst_media.state == MediaState.Ready
    gst_media.play()
    assert gst_media.state == MediaState.Playing
    gst_media.stop()


def test_prearm_failed_uri_returns_false(short_wav, caplog):
    media = GstMedia()
    media.pipe = ("UriInput", "AutoSink")
    media.elements[0].uri = "file:///does/not/exist.wav"
    with caplog.at_level(logging.WARNING):
        result = media.prearm()
    assert result is False
    assert media.state == MediaState.Null
    # Spec requires WARNING log on failure
    assert any(
        r.levelno >= logging.WARNING
        and "prearm" in r.message.lower()
        for r in caplog.records
    ), f"no WARNING about prearm logged; got {caplog.records}"
