#!/usr/bin/env python3
"""End-to-end tests for video cue support via the test harness.

Starts LiSP automatically, tests video cue lifecycle (add, play,
pause, resume, stop, seek, loop) and verifies audio-only backward
compatibility.

Run:
    poetry run python tests/e2e/test_video_e2e.py

Options:
    --no-launch    Don't start/stop LiSP (attach to existing)
    --host HOST    Harness host (default: 127.0.0.1)
    --port PORT    Harness port (default: 8070)
"""

import os
import subprocess
import sys
import time

from helpers import (
    call,
    clear_cues,
    cue_signal,
    cue_state,
    make_tone,
    run_suite,
    signal_sub,
    stop_all,
    wait_for_signal,
    wait_state,
)

MEDIA_DIR = "/tmp/lisp_test_video"


# ── Media file generation ────────────────────────────────────

def make_test_video(filename, duration_s=10):
    """Generate a WebM video with audio using gst-launch-1.0.

    Audio and video durations are matched to avoid muxer issues.
    At 30fps: 300 frames = 10s. audiotestsrc at default buffer
    size (1024 samples @ 44100 Hz): ~431 buffers = 10s.
    """
    video_frames = int(duration_s * 30)
    # audiotestsrc default: 1024 samples/buffer at 44100 Hz
    audio_buffers = int(duration_s * 44100 / 1024) + 1
    cmd = [
        "gst-launch-1.0", "-e",
        "videotestsrc", f"num-buffers={video_frames}", "!",
        "videoconvert", "!",
        "vp8enc", "deadline=1", "!",
        "queue", "!",
        "mux.",
        "audiotestsrc", f"num-buffers={audio_buffers}",
        "freq=440", "!",
        "audioconvert", "!",
        "vorbisenc", "!",
        "queue", "!",
        "mux.",
        "webmmux", "name=mux", "!",
        "filesink", f"location={filename}",
    ]
    result = subprocess.run(
        cmd, capture_output=True, timeout=60
    )
    if result.returncode != 0:
        print(f"WARNING: Failed to generate test video: "
              f"{result.stderr.decode()}", file=sys.stderr)
        return False
    return True


def create_test_media():
    """Create test audio and video files."""
    os.makedirs(MEDIA_DIR, exist_ok=True)

    audio_path = os.path.join(MEDIA_DIR, "tone_A.wav")
    if not os.path.exists(audio_path):
        make_tone(audio_path, 440, 4.0)

    # 10-second video for lifecycle tests (play/pause/resume/stop)
    video_path = os.path.join(MEDIA_DIR, "test_video.webm")
    if not os.path.exists(video_path):
        if not make_test_video(video_path, duration_s=10):
            print("ERROR: Cannot generate test video",
                  file=sys.stderr)
            sys.exit(2)

    # 2-second video for natural EOS test
    short_path = os.path.join(MEDIA_DIR, "short_video.webm")
    if not os.path.exists(short_path):
        if not make_test_video(short_path, duration_s=2):
            print("ERROR: Cannot generate short test video",
                  file=sys.stderr)
            sys.exit(2)


# ── Tests ────────────────────────────────────────────────────

def _add_video(uri):
    """Add a video cue and wait for item_added before returning id."""
    with signal_sub("cue_model.item_added") as sub:
        call("cue.add_video_from_uri", {"uri": uri})
        event = wait_for_signal(sub, timeout=5)
    assert event is not None, "cue_model.item_added did not fire"
    cues = call("cue.list")
    return cues[-1]


def test_1_video_cue_lifecycle(t):
    """Add a video cue, verify play/pause/resume/stop."""
    print("\n=== Test 1: Video Cue Lifecycle ===")
    clear_cues()

    video_path = os.path.join(MEDIA_DIR, "test_video.webm")
    cue = _add_video(video_path)
    t.check("1a: Video cue added", cue is not None)
    cue_id = cue["id"]
    t.check("1b: Cue is GstMediaCue",
            cue["_type_"] == "GstMediaCue")

    # Play — subscribe BEFORE the triggering call so the signal is
    # guaranteed to be captured even if the state transition is fast.
    with cue_signal(cue_id, "started") as sub:
        call("cue.start", {"id": cue_id})
        started = wait_for_signal(sub, timeout=5)
    t.check("1c: cue.started signal fired", started is not None)

    # Verify current_time advances (inherent wait — time must pass)
    time.sleep(0.5)
    state = call("cue.state", {"id": cue_id})
    t.check("1d: current_time > 0",
            state["current_time"] > 0)

    # Pause
    with cue_signal(cue_id, "paused") as sub:
        call("cue.pause", {"id": cue_id})
        paused = wait_for_signal(sub, timeout=3)
    t.check("1e: cue.paused signal fired", paused is not None)

    # Resume — cue.started fires again on resume
    with cue_signal(cue_id, "started") as sub:
        call("cue.resume", {"id": cue_id})
        resumed = wait_for_signal(sub, timeout=3)
    t.check("1f: cue.started fired on resume",
            resumed is not None)

    # Stop
    with cue_signal(cue_id, "stopped") as sub:
        call("cue.stop", {"id": cue_id})
        stopped = wait_for_signal(sub, timeout=3)
    t.check("1g: cue.stopped signal fired", stopped is not None)


def test_2_audio_backward_compat(t):
    """Verify audio-only cues still work unchanged."""
    print("\n=== Test 2: Audio Backward Compatibility ===")
    clear_cues()

    audio_path = os.path.join(MEDIA_DIR, "tone_A.wav")
    with signal_sub("cue_model.item_added") as sub:
        call("cue.add_from_uri", {"uri": audio_path})
        added = wait_for_signal(sub, timeout=5)
    t.check("2a: Audio cue added", added is not None)

    cues = call("cue.list")
    if not cues:
        print("  SKIP: No cue to test")
        return

    cue_id = cues[0]["id"]

    with cue_signal(cue_id, "started") as sub:
        call("cue.start", {"id": cue_id})
        started = wait_for_signal(sub, timeout=5)
    t.check("2b: Audio cue reaches Running", started is not None)

    time.sleep(0.5)
    state = call("cue.state", {"id": cue_id})
    t.check("2c: Audio current_time > 0",
            state["current_time"] > 0)

    with cue_signal(cue_id, "stopped") as sub:
        call("cue.stop", {"id": cue_id})
        stopped = wait_for_signal(sub, timeout=3)
    t.check("2d: Audio cue reaches Stop", stopped is not None)


def test_3_video_and_audio_coexist(t):
    """Verify video and audio cues can coexist in the same session."""
    print("\n=== Test 3: Video + Audio Coexistence ===")
    clear_cues()

    audio_path = os.path.join(MEDIA_DIR, "tone_A.wav")
    video_path = os.path.join(MEDIA_DIR, "test_video.webm")

    with signal_sub("cue_model.item_added") as sub:
        call("cue.add_from_uri", {"uri": audio_path})
        call("cue.add_video_from_uri", {"uri": video_path})
        # Wait for both adds to complete
        first = wait_for_signal(sub, timeout=5)
        second = wait_for_signal(sub, timeout=5)
    t.check("3a: Two cues added",
            first is not None and second is not None)

    cues = call("cue.list")
    if len(cues) < 2:
        print("  SKIP: Not enough cues")
        return

    audio_id = cues[0]["id"]
    video_id = cues[1]["id"]

    # Subscribe to both started signals before starting either
    with cue_signal(audio_id, "started") as a_sub, \
            cue_signal(video_id, "started") as v_sub:
        call("cue.start", {"id": audio_id})
        call("cue.start", {"id": video_id})
        a_started = wait_for_signal(a_sub, timeout=5)
        v_started = wait_for_signal(v_sub, timeout=5)

    t.check("3b: Audio cue Running", a_started is not None)
    t.check("3c: Video cue Running", v_started is not None)

    with cue_signal(audio_id, "stopped") as a_sub, \
            cue_signal(video_id, "stopped") as v_sub:
        call("cue.stop", {"id": audio_id})
        call("cue.stop", {"id": video_id})
        a_stopped = wait_for_signal(a_sub, timeout=3)
        v_stopped = wait_for_signal(v_sub, timeout=3)
    t.check("3d: Audio cue stopped", a_stopped is not None)
    t.check("3e: Video cue stopped", v_stopped is not None)


def test_4_natural_eos(t):
    """Verify a video cue plays to completion and reaches Stop."""
    print("\n=== Test 4: Natural EOS (Video Plays to End) ===")
    clear_cues()

    short_path = os.path.join(MEDIA_DIR, "short_video.webm")
    cue = _add_video(short_path)
    t.check("4a: Short video cue added", cue is not None)
    cue_id = cue["id"]

    # Subscribe to 'end' (fires on natural EOS) and 'stopped' in
    # parallel.  Natural EOS produces both 'end' and a state
    # transition — 'end' is the signal dedicated to EOS paths.
    with cue_signal(cue_id, "started") as start_sub, \
            cue_signal(cue_id, "end") as end_sub:
        call("cue.start", {"id": cue_id})
        t.check("4b: Cue reaches Running",
                wait_for_signal(start_sub, timeout=5) is not None)
        t.check("4c: cue.end fires on natural EOS",
                wait_for_signal(end_sub, timeout=8) is not None)


def test_5_stop_and_replay(t):
    """Stop a video mid-playback, then play it again.

    Regression test: uridecodebin removes dynamic pads on READY
    transition.  If _audio_linked/_video_linked flags are not
    reset in stop(), the second play fails with 'not-linked'.
    """
    print("\n=== Test 5: Stop and Replay ===")
    clear_cues()

    video_path = os.path.join(MEDIA_DIR, "test_video.webm")
    cue = _add_video(video_path)
    t.check("5a: Video cue added", cue is not None)
    cue_id = cue["id"]

    # First play, let it run briefly, then stop
    with cue_signal(cue_id, "started") as sub:
        call("cue.start", {"id": cue_id})
        t.check("5b: First play reaches Running",
                wait_for_signal(sub, timeout=5) is not None)

    time.sleep(1)

    with cue_signal(cue_id, "stopped") as sub:
        call("cue.stop", {"id": cue_id})
        t.check("5c: First play reaches Stop",
                wait_for_signal(sub, timeout=3) is not None)

    # Second play — must not error
    with cue_signal(cue_id, "started") as sub:
        call("cue.start", {"id": cue_id})
        t.check("5d: Second play reaches Running",
                wait_for_signal(sub, timeout=5) is not None)

    time.sleep(0.5)
    state = call("cue.state", {"id": cue_id})
    t.check("5e: current_time advancing on replay",
            state["current_time"] > 0)

    with cue_signal(cue_id, "stopped") as sub:
        call("cue.stop", {"id": cue_id})
        t.check("5f: Second play reaches Stop",
                wait_for_signal(sub, timeout=3) is not None)


def test_6_seek(t):
    """Seek a video cue mid-playback and verify the new position.

    QA-P1c: exercise the seek path for video cues to guard against
    regressions in uridecodebin flush/seek handling across the
    split A/V pipeline.
    """
    print("\n=== Test 6: Video Seek ===")
    clear_cues()

    video_path = os.path.join(MEDIA_DIR, "test_video.webm")
    cue = _add_video(video_path)
    cue_id = cue["id"]

    with cue_signal(cue_id, "started") as sub:
        call("cue.start", {"id": cue_id})
        t.check("6a: Cue reaches Running",
                wait_for_signal(sub, timeout=5) is not None)

    # Let it run briefly so the pipeline is fully preroll'd
    time.sleep(0.5)

    # Seek to 5000ms (midway through a 10s clip)
    call("cue.seek", {"id": cue_id, "position": 5000})

    # Allow time for the seek flush/preroll
    time.sleep(0.8)
    state = call("cue.state", {"id": cue_id})
    # current_time is reported in ms from the pipeline; after a
    # seek to 5s, it should be >= 4500ms (allowing for clock drift
    # and the brief continued playback after seek completes).
    t.check("6b: current_time advanced past seek target "
            f"(got {state['current_time']} ms)",
            state["current_time"] >= 4500)

    # Must still be running — seek should not stop the cue
    t.check("6c: Cue still Running after seek",
            cue_state(cue_id) == "Running")

    with cue_signal(cue_id, "stopped") as sub:
        call("cue.stop", {"id": cue_id})
        wait_for_signal(sub, timeout=3)


def test_7_loop(t):
    """Loop a short video cue and verify it restarts.

    QA-P1c: exercise the loop path.  The short video is 2s; we
    set loop=1 (one repeat, total ~4s) and verify the cue is
    still running after the first natural EOS point.

    `loop` is a property on ``cue.media`` (not the cue itself),
    so it's set via the nested "media" sub-dict — see
    ``HasProperties.update_properties`` which recurses when the
    current value is itself a ``HasProperties``.
    """
    print("\n=== Test 7: Video Loop ===")
    clear_cues()

    short_path = os.path.join(MEDIA_DIR, "short_video.webm")
    cue = _add_video(short_path)
    cue_id = cue["id"]

    # Set loop on the nested Media via the "media" key.
    call("cue.set_property", {
        "id": cue_id,
        "property": "media",
        "value": {"loop": 1},
    })

    with cue_signal(cue_id, "started") as sub:
        call("cue.start", {"id": cue_id})
        t.check("7a: Cue reaches Running",
                wait_for_signal(sub, timeout=5) is not None)

    # Without looping the 2s clip would EOS around t=2s.  With
    # loop=1 it should still be playing at t=2.5s (mid-second
    # iteration).
    time.sleep(2.5)
    t.check("7b: Still Running during second iteration",
            cue_state(cue_id) == "Running")

    # loop=1 means one repeat — total playback ~4s.  Wait up to
    # 4 more seconds for the natural stop.
    t.check("7c: Cue stops after loop count exhausted",
            wait_state(cue_id, "Stop", timeout=4))


# ── Main ─────────────────────────────────────────────────────

def run_tests(t):
    create_test_media()

    test_1_video_cue_lifecycle(t)
    stop_all()
    test_2_audio_backward_compat(t)
    stop_all()
    test_3_video_and_audio_coexist(t)
    stop_all()
    test_4_natural_eos(t)
    stop_all()
    test_5_stop_and_replay(t)
    stop_all()
    test_6_seek(t)
    stop_all()
    test_7_loop(t)
    stop_all()


if __name__ == "__main__":
    run_suite("Video Cue E2E Tests", run_tests)
