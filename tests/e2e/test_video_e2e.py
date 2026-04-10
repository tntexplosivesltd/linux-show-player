#!/usr/bin/env python3
"""End-to-end tests for video cue support via the test harness.

Starts LiSP automatically, tests video cue lifecycle (add, play,
pause, resume, stop) and verifies audio-only backward compatibility.

Run:
    poetry run python tests/e2e/test_video_e2e.py

Options:
    --no-launch    Don't start/stop LiSP (attach to existing)
    --host HOST    Harness host (default: 127.0.0.1)
    --port PORT    Harness port (default: 8070)
"""

import argparse
import math
import os
import struct
import subprocess
import sys
import time
import wave

# Allow importing the test harness client without installing
sys.path.insert(
    0,
    os.path.join(
        os.path.dirname(__file__), "..", "..", "lisp", "plugins",
        "test_harness",
    ),
)
from client import send_request  # noqa: E402

# Reuse LiSP lifecycle helpers from the groups E2E suite
sys.path.insert(0, os.path.dirname(__file__))
from test_groups_e2e import (  # noqa: E402
    start_lisp,
    stop_lisp,
    stop_all,
)

_HOST = "127.0.0.1"
_PORT = 8070
MEDIA_DIR = "/tmp/lisp_test_video"

_pass = 0
_fail = 0
_errors = []


# ── Helpers ──────────────────────────────────────────────────

def call(method, params=None):
    resp = send_request(_HOST, _PORT, method, params or {})
    if "error" in resp:
        raise RuntimeError(
            f"{method}: {resp['error']['message']}"
        )
    return resp.get("result")


def check(name, condition):
    global _pass, _fail
    if condition:
        _pass += 1
        print(f"  PASS: {name}")
    else:
        _fail += 1
        _errors.append(name)
        print(f"  FAIL: {name}")


def cue_state(cue_id):
    return call("cue.state", {"id": cue_id})["state_name"]


def wait_state(cue_id, target, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if cue_state(cue_id) == target:
            return True
        time.sleep(0.2)
    return False


# ── Media file generation ───────────────────────────────────

def make_tone(filename, freq, duration_s, sample_rate=44100):
    """Generate a WAV tone file."""
    n_samples = int(sample_rate * duration_s)
    with wave.open(filename, "w") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        for i in range(n_samples):
            t = i / sample_rate
            env = min(t / 0.1, 1.0, (duration_s - t) / 0.1)
            val = int(
                32767 * 0.5 * max(0, env)
                * math.sin(2 * math.pi * freq * t)
            )
            w.writeframes(struct.pack("<h", val))


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


# ── Setup ────────────────────────────────────────────────────

def clear_cues():
    """Remove all cues from the session."""
    for cue in call("cue.list"):
        call("cue.remove", {"id": cue["id"]})
    time.sleep(0.3)


# ── Tests ────────────────────────────────────────────────────

def test_1_video_cue_lifecycle():
    """Add a video cue, verify play/pause/resume/stop."""
    print("\n=== Test 1: Video Cue Lifecycle ===")
    clear_cues()

    video_path = os.path.join(MEDIA_DIR, "test_video.webm")
    call("cue.add_video_from_uri", {"uri": video_path})
    time.sleep(1)

    cues = call("cue.list")
    check("1a: Video cue added", len(cues) == 1)

    if not cues:
        print("  SKIP: No cue to test")
        return

    cue_id = cues[0]["id"]
    check("1b: Cue is GstMediaCue",
          cues[0]["_type_"] == "GstMediaCue")

    # Play
    call("cue.start", {"id": cue_id})
    check("1c: Cue reaches Running",
          wait_state(cue_id, "Running", timeout=5))

    # Verify current_time advances
    time.sleep(0.5)
    state = call("cue.state", {"id": cue_id})
    check("1d: current_time > 0",
          state["current_time"] > 0)

    # Pause
    call("cue.pause", {"id": cue_id})
    check("1e: Cue reaches Pause",
          wait_state(cue_id, "Pause", timeout=3))

    # Resume
    call("cue.resume", {"id": cue_id})
    check("1f: Cue resumes to Running",
          wait_state(cue_id, "Running", timeout=3))

    # Stop
    call("cue.stop", {"id": cue_id})
    check("1g: Cue reaches Stop",
          wait_state(cue_id, "Stop", timeout=3))


def test_2_audio_backward_compat():
    """Verify audio-only cues still work unchanged."""
    print("\n=== Test 2: Audio Backward Compatibility ===")
    clear_cues()

    audio_path = os.path.join(MEDIA_DIR, "tone_A.wav")
    call("cue.add_from_uri", {"uri": audio_path})
    time.sleep(1)

    cues = call("cue.list")
    check("2a: Audio cue added", len(cues) == 1)

    if not cues:
        print("  SKIP: No cue to test")
        return

    cue_id = cues[0]["id"]

    # Play
    call("cue.start", {"id": cue_id})
    check("2b: Audio cue reaches Running",
          wait_state(cue_id, "Running", timeout=5))

    time.sleep(0.5)
    state = call("cue.state", {"id": cue_id})
    check("2c: Audio current_time > 0",
          state["current_time"] > 0)

    # Stop
    call("cue.stop", {"id": cue_id})
    check("2d: Audio cue reaches Stop",
          wait_state(cue_id, "Stop", timeout=3))


def test_3_video_and_audio_coexist():
    """Verify video and audio cues can coexist in the same session."""
    print("\n=== Test 3: Video + Audio Coexistence ===")
    clear_cues()

    audio_path = os.path.join(MEDIA_DIR, "tone_A.wav")
    video_path = os.path.join(MEDIA_DIR, "test_video.webm")

    call("cue.add_from_uri", {"uri": audio_path})
    time.sleep(0.5)
    call("cue.add_video_from_uri", {"uri": video_path})
    time.sleep(1)

    cues = call("cue.list")
    check("3a: Two cues exist", len(cues) == 2)

    if len(cues) < 2:
        print("  SKIP: Not enough cues")
        return

    audio_id = cues[0]["id"]
    video_id = cues[1]["id"]

    # Start both
    call("cue.start", {"id": audio_id})
    call("cue.start", {"id": video_id})
    time.sleep(0.5)

    check("3b: Audio cue Running",
          cue_state(audio_id) == "Running")
    check("3c: Video cue Running",
          cue_state(video_id) == "Running")

    # Stop both
    call("cue.stop", {"id": audio_id})
    call("cue.stop", {"id": video_id})
    check("3d: Audio cue stopped",
          wait_state(audio_id, "Stop", timeout=3))
    check("3e: Video cue stopped",
          wait_state(video_id, "Stop", timeout=3))


def test_4_natural_eos():
    """Verify a video cue plays to completion and reaches Stop."""
    print("\n=== Test 4: Natural EOS (Video Plays to End) ===")
    clear_cues()

    short_path = os.path.join(MEDIA_DIR, "short_video.webm")
    call("cue.add_video_from_uri", {"uri": short_path})
    time.sleep(1)

    cues = call("cue.list")
    check("4a: Short video cue added", len(cues) == 1)

    if not cues:
        print("  SKIP: No cue to test")
        return

    cue_id = cues[0]["id"]

    # Play and let it run to natural end (~2 seconds)
    call("cue.start", {"id": cue_id})
    check("4b: Cue reaches Running",
          wait_state(cue_id, "Running", timeout=5))

    # Wait for natural EOS — the cue should stop on its own
    check("4c: Cue reaches Stop after EOS",
          wait_state(cue_id, "Stop", timeout=8))


# ── Main ─────────────────────────────────────────────────────

def main():
    global _HOST, _PORT

    parser = argparse.ArgumentParser()
    parser.add_argument("--no-launch", action="store_true")
    parser.add_argument("--host", default=_HOST)
    parser.add_argument("--port", type=int, default=_PORT)
    args = parser.parse_args()

    _HOST = args.host
    _PORT = args.port

    create_test_media()

    if not args.no_launch:
        start_lisp()

    try:
        test_1_video_cue_lifecycle()
        stop_all()
        test_2_audio_backward_compat()
        stop_all()
        test_3_video_and_audio_coexist()
        stop_all()
        test_4_natural_eos()
        stop_all()
    finally:
        if not args.no_launch:
            stop_lisp()

    print(f"\n{'=' * 40}")
    print(f"Results: {_pass} passed, {_fail} failed")
    if _errors:
        print("Failures:")
        for e in _errors:
            print(f"  - {e}")

    sys.exit(1 if _fail else 0)


if __name__ == "__main__":
    main()
