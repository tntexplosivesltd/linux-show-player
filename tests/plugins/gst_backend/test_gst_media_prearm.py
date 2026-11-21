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


# Real UriInputs: keep their duration probe off the Application.
pytestmark = pytest.mark.usefixtures("bypass_session_paths")

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


# --- Edits made while armed must reach the next play() ----------------
#
# Arming seeks once, with the start time, stop time and loop count in
# force at that moment, and play() on an armed pipeline skips the seek.
# The standby cue is the armed one, and it is also the cue the operator
# has selected and is editing.


@pytest.fixture(scope="module")
def long_wav(tmp_path_factory):
    """A 2-second silent WAV, to tell it apart from short_wav by
    duration."""
    path = tmp_path_factory.mktemp("media") / "long.wav"
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(48000)
        w.writeframes(b"\x00\x00" * 96000)
    return path


def _record_seeks(media, monkeypatch):
    """Record every seek on the live pipeline as (flags, start, stop),
    in ms."""
    from lisp.plugins.gst_backend.gi_repository import Gst

    pipeline = media._GstMedia__pipeline
    seeks = []
    real_seek = pipeline.seek

    def recording_seek(rate, fmt, flags, st, start, sp, stop):
        seeks.append((flags, start // Gst.MSECOND, stop // Gst.MSECOND))
        return real_seek(rate, fmt, flags, st, start, sp, stop)

    monkeypatch.setattr(pipeline, "seek", recording_seek)
    return seeks


def test_start_time_edit_while_armed_plays_from_new_start(gst_media):
    gst_media.prearm()
    gst_media.start_time = 500

    gst_media.play()

    assert gst_media.current_time() >= 450
    gst_media.stop()


def test_stop_time_edit_while_armed_ends_at_new_stop(
    gst_media, monkeypatch
):
    gst_media.prearm()
    seeks = _record_seeks(gst_media, monkeypatch)
    gst_media.stop_time = 300

    gst_media.play()

    assert seeks, "nothing applied the new stop time"
    assert seeks[-1][2] == 300
    gst_media.stop()


def test_loop_edit_while_armed_loops_the_first_play(
    gst_media, monkeypatch
):
    from lisp.plugins.gst_backend.gi_repository import Gst

    gst_media.prearm()
    seeks = _record_seeks(gst_media, monkeypatch)
    gst_media.loop = 2

    gst_media.play()

    # SEGMENT makes the pipeline post SEGMENT_DONE, which drives looping
    assert seeks, "nothing applied the new loop count"
    assert seeks[-1][0] & Gst.SeekFlags.SEGMENT
    gst_media.stop()


def test_file_edit_while_armed_plays_the_new_file(gst_media, long_wav):
    from lisp.plugins.gst_backend.gi_repository import Gst

    gst_media.prearm()
    gst_media.elements[0].uri = f"file://{long_wav}"

    gst_media.play()

    pipeline = gst_media._GstMedia__pipeline
    ok, duration = pipeline.query_duration(Gst.Format.TIME)
    assert ok and duration // Gst.MSECOND > 1500, (
        "the armed pipeline played the old (1 s) file"
    )
    gst_media.stop()


def test_seek_edits_are_applied_while_armed_not_at_go(
    gst_media, monkeypatch
):
    """The edit is applied when it is made, so GO keeps the pre-arm
    latency saving: play() has nothing left to seek."""
    gst_media.prearm()
    gst_media.start_time = 200
    gst_media.stop_time = 800
    seeks = _record_seeks(gst_media, monkeypatch)

    gst_media.play()

    assert seeks == []
    assert gst_media.current_time() >= 150
    gst_media.stop()


def test_edits_while_not_armed_do_not_seek(gst_media, monkeypatch):
    seeks = _record_seeks(gst_media, monkeypatch)

    gst_media.start_time = 200
    gst_media.stop_time = 800
    gst_media.loop = 1

    assert seeks == []


def _played_to(media, seconds):
    """Play for `seconds` of wall time; return the position reached."""
    import time

    media.play()
    time.sleep(seconds)
    position = media.current_time()
    media.stop()
    return position


def test_stop_time_edit_while_armed_stops_playback_there(gst_media):
    gst_media.prearm()
    gst_media.stop_time = 300

    assert _played_to(gst_media, 0.7) <= 400


def test_clearing_the_stop_time_while_armed_plays_past_it(gst_media):
    """A seek with SeekType.NONE keeps the segment's old stop, so
    clearing a stop time must set the stop explicitly."""
    gst_media.stop_time = 300
    gst_media.prearm()
    gst_media.stop_time = 0

    assert _played_to(gst_media, 0.7) >= 500


def test_a_failed_reseek_is_retried_at_play(gst_media, monkeypatch):
    gst_media.prearm()
    pipeline = gst_media._GstMedia__pipeline
    real_seek = pipeline.seek
    monkeypatch.setattr(pipeline, "seek", lambda *a: False)
    gst_media.start_time = 500  # this re-seek fails
    monkeypatch.setattr(pipeline, "seek", real_seek)

    gst_media.play()

    assert gst_media.current_time() >= 450
    gst_media.stop()


def test_file_and_start_edits_together_while_armed(gst_media, long_wav):
    from lisp.plugins.gst_backend.gi_repository import Gst

    gst_media.prearm()
    gst_media.elements[0].uri = f"file://{long_wav}"
    gst_media.start_time = 1500  # past the end of the old 1 s file

    gst_media.play()

    pipeline = gst_media._GstMedia__pipeline
    ok, duration = pipeline.query_duration(Gst.Format.TIME)
    assert ok and duration // Gst.MSECOND > 1500
    assert gst_media.current_time() >= 1450
    gst_media.stop()


def test_file_edit_while_armed_rearms_at_once(gst_media, long_wav):
    """The new file is prerolled when it is set, so the cue stays armed
    and GO keeps the latency saving."""
    from lisp.plugins.gst_backend.gi_repository import Gst

    gst_media.prearm()
    gst_media.elements[0].uri = f"file://{long_wav}"

    assert gst_media.state == MediaState.Armed
    pipeline = gst_media._GstMedia__pipeline
    ok, duration = pipeline.query_duration(Gst.Format.TIME)
    assert ok and duration // Gst.MSECOND > 1500


def test_edit_and_edit_back_while_armed_keeps_the_pipeline(
    gst_media, short_wav, long_wav, monkeypatch
):
    gst_media.prearm()
    gst_media.start_time = 300
    gst_media.start_time = 0
    seeks = _record_seeks(gst_media, monkeypatch)

    gst_media.play()

    assert seeks == []
    assert gst_media.current_time() < 200
    gst_media.stop()


def test_session_relative_uri_change_is_not_a_new_file(
    gst_media, monkeypatch
):
    """The uri property reads back relative to the session folder, so
    it changes when the session is saved elsewhere; the file does not.
    """
    from lisp.core.session_uri import SessionURI

    gst_media.prearm()
    monkeypatch.setattr(
        SessionURI, "relative_path", property(lambda self: "moved/x.wav")
    )
    seeks = _record_seeks(gst_media, monkeypatch)

    gst_media.play()

    assert seeks == [], "a session move was taken for a new file"
    gst_media.stop()


def test_a_file_edit_that_will_not_preroll_says_the_arm_is_lost(
    gst_media, short_wav
):
    """The manager lists the cue as armed; it must hear that the media
    is not (a preload cue reports the failure)."""
    gst_media.prearm()
    lost = []

    def _on_arm_lost(media):
        lost.append(media)

    gst_media.arm_lost.connect(_on_arm_lost)
    gst_media.elements[0].uri = "file:///does/not/exist.wav"

    assert lost == [gst_media]
    assert gst_media.state != MediaState.Armed
    gst_media.play()  # cold, and fails cleanly: no exception
    gst_media.stop()


def test_a_media_that_lost_its_arm_arms_again_once_fixed(
    gst_media, short_wav
):
    gst_media.prearm()
    gst_media.elements[0].uri = "file:///does/not/exist.wav"
    gst_media.elements[0].uri = f"file://{short_wav}"

    assert gst_media.prearm() is True
    assert gst_media.state == MediaState.Armed


def test_a_seek_edit_does_not_say_the_arm_is_lost(gst_media):
    gst_media.prearm()
    lost = []

    def _on_arm_lost(media):
        lost.append(media)

    gst_media.arm_lost.connect(_on_arm_lost)
    gst_media.start_time = 300

    assert lost == []


def test_a_reseek_failing_again_at_play_starts_from_start_time(
    gst_media, monkeypatch
):
    """When play() cannot catch up, the pipeline is still PAUSED at the
    old armed position; it must not be resumed from there."""
    gst_media.prearm()
    pipeline = gst_media._GstMedia__pipeline
    real_seek = pipeline.seek
    failures = [2]  # the edit's re-seek, then play()'s catch-up

    def flaky_seek(*args):
        if failures[0]:
            failures[0] -= 1
            return False
        return real_seek(*args)

    monkeypatch.setattr(pipeline, "seek", flaky_seek)
    gst_media.start_time = 500

    gst_media.play()

    assert failures == [0]
    assert gst_media.current_time() >= 450
    gst_media.stop()


def test_reseek_then_play_plays_from_start_time(gst_media):
    gst_media.prearm()
    gst_media.reseek(700)

    gst_media.play()

    assert gst_media.current_time() < 500
    gst_media.stop()


# --- __arm_lock: edits (main thread) against play()/prearm() (workers) --


def _run_with_timeout(target, timeout=5.0):
    import threading

    errors = []

    def _run():
        try:
            target()
        except Exception as exc:  # reported below
            errors.append(exc)

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    return thread, errors


def test_edits_racing_play_neither_deadlock_nor_raise(gst_media):
    import threading
    import time

    gst_media.prearm()
    done = threading.Event()

    def _edit_until_done():
        i = 0
        while not done.is_set():
            gst_media.start_time = (i % 5) * 100
            i += 1

    editor, edit_errors = _run_with_timeout(_edit_until_done)
    time.sleep(0.05)
    player, play_errors = _run_with_timeout(gst_media.play)
    player.join(timeout=5)
    done.set()
    editor.join(timeout=5)

    assert not player.is_alive() and not editor.is_alive(), "deadlock"
    assert edit_errors == [] and play_errors == []
    assert gst_media.state == MediaState.Playing
    gst_media.stop()


def test_prearm_racing_play_neither_deadlock_nor_raise(gst_media):
    armer, arm_errors = _run_with_timeout(gst_media.prearm)
    player, play_errors = _run_with_timeout(gst_media.play)
    armer.join(timeout=5)
    player.join(timeout=5)

    assert not armer.is_alive() and not player.is_alive(), "deadlock"
    assert arm_errors == [] and play_errors == []
    assert gst_media.state == MediaState.Playing
    gst_media.stop()
