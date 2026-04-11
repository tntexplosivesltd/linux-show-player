#!/usr/bin/env python3
"""End-to-end tests for image cue support via the test harness.

Tests image cue lifecycle (add, play, auto-stop by duration),
slideshow via GroupCue playlist mode, and parallel audio+image.

Run:
    poetry run python tests/e2e/test_image_e2e.py

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
MEDIA_DIR = "/tmp/lisp_test_image"

_pass = 0
_fail = 0
_errors = []


# -- Helpers ----------------------------------------------------------

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


# -- Media file generation --------------------------------------------

def make_test_image(filename, width=320, height=240):
    """Generate a test PNG image using gst-launch-1.0."""
    cmd = [
        "gst-launch-1.0", "-e",
        "videotestsrc", "num-buffers=1", "!",
        f"video/x-raw,width={width},height={height}", "!",
        "pngenc", "!",
        "filesink", f"location={filename}",
    ]
    result = subprocess.run(cmd, capture_output=True, timeout=30)
    if result.returncode != 0:
        print(
            f"WARNING: Failed to generate test image: "
            f"{result.stderr.decode()}",
            file=sys.stderr,
        )
        return False
    return True


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


def create_test_media():
    """Create test image and audio files."""
    os.makedirs(MEDIA_DIR, exist_ok=True)

    image_path = os.path.join(MEDIA_DIR, "test_image.png")
    if not os.path.exists(image_path):
        if not make_test_image(image_path):
            print("ERROR: Cannot generate test image",
                  file=sys.stderr)
            sys.exit(2)

    # Additional images for slideshow test
    for name in ["slide_1.png", "slide_2.png", "slide_3.png"]:
        path = os.path.join(MEDIA_DIR, name)
        if not os.path.exists(path):
            if not make_test_image(path):
                print(f"ERROR: Cannot generate {name}",
                      file=sys.stderr)
                sys.exit(2)

    # Audio file for parallel test
    audio_path = os.path.join(MEDIA_DIR, "tone.wav")
    if not os.path.exists(audio_path):
        make_tone(audio_path, 440, 8.0)


# -- Setup ------------------------------------------------------------

def clear_cues():
    """Remove all cues from the session."""
    for cue in call("cue.list"):
        call("cue.remove", {"id": cue["id"]})
    time.sleep(0.3)


# -- Tests ------------------------------------------------------------

def test_1_image_cue_lifecycle():
    """Add an image cue, verify play and auto-stop by duration."""
    print("\n=== Test 1: Image Cue Lifecycle ===")
    clear_cues()

    image_path = os.path.join(MEDIA_DIR, "test_image.png")
    # 3-second display duration for faster test
    call("cue.add_image_from_uri", {
        "uri": image_path, "duration": 3000,
    })
    time.sleep(1)

    cues = call("cue.list")
    check("1a: Image cue added", len(cues) == 1)

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

    # Verify it auto-stops after ~3 seconds (duration enforcement)
    check("1d: Cue auto-stops after duration",
          wait_state(cue_id, "Stop", timeout=8))


def test_2_image_cue_manual_stop():
    """Play an image cue and stop it manually before duration."""
    print("\n=== Test 2: Image Cue Manual Stop ===")
    clear_cues()

    image_path = os.path.join(MEDIA_DIR, "test_image.png")
    call("cue.add_image_from_uri", {
        "uri": image_path, "duration": 10000,
    })
    time.sleep(1)

    cues = call("cue.list")
    check("2a: Image cue added", len(cues) == 1)

    if not cues:
        print("  SKIP: No cue to test")
        return

    cue_id = cues[0]["id"]

    # Play
    call("cue.start", {"id": cue_id})
    check("2b: Cue reaches Running",
          wait_state(cue_id, "Running", timeout=5))

    # Verify time is advancing
    time.sleep(0.5)
    state = call("cue.state", {"id": cue_id})
    check("2c: current_time > 0",
          state["current_time"] > 0)

    # Manual stop before duration
    call("cue.stop", {"id": cue_id})
    check("2d: Cue reaches Stop",
          wait_state(cue_id, "Stop", timeout=3))


def test_3_slideshow_playlist():
    """GroupCue playlist mode with image cues = slideshow."""
    print("\n=== Test 3: Slideshow via Playlist GroupCue ===")
    clear_cues()

    # Add 3 image cues with short durations
    for name, dur in [
        ("slide_1.png", 2000),
        ("slide_2.png", 2000),
        ("slide_3.png", 2000),
    ]:
        path = os.path.join(MEDIA_DIR, name)
        call("cue.add_image_from_uri", {
            "uri": path, "duration": dur,
        })
        time.sleep(0.5)

    time.sleep(0.5)
    cues = call("cue.list")
    check("3a: Three image cues exist", len(cues) == 3)

    if len(cues) < 3:
        print("  SKIP: Not enough cues")
        return

    # Select cues and group them
    cue_ids = [c["id"] for c in cues]
    call("layout.select_cues", {"indices": [0, 1, 2]})
    time.sleep(0.3)
    call("layout.context_action", {
        "action": "Group selected",
        "cue_ids": cue_ids,
    })
    time.sleep(1)

    # Find the group cue
    all_cues = call("cue.list")
    group_cues = [
        c for c in all_cues if c["_type_"] == "GroupCue"
    ]
    check("3b: GroupCue created", len(group_cues) == 1)

    if not group_cues:
        print("  SKIP: No group cue")
        return

    group_id = group_cues[0]["id"]

    # Set playlist mode (mode=1)
    call("cue.set_property", {
        "id": group_id,
        "property": "group_mode",
        "value": 1,
    })
    time.sleep(0.3)

    # Play the group
    start_time = time.time()
    call("cue.start", {"id": group_id})
    check("3c: Group reaches Running",
          wait_state(group_id, "Running", timeout=5))

    # Wait for group to finish (3 x 2s = ~6s plus overhead)
    check("3d: Group finishes after all slides",
          wait_state(group_id, "Stop", timeout=15))

    elapsed = time.time() - start_time
    # Should take roughly 6 seconds (3 slides x 2s each)
    check("3e: Total time reasonable (4-12s)",
          4 < elapsed < 12)


def test_4_parallel_audio_and_image():
    """GroupCue parallel mode: audio + image simultaneously."""
    print("\n=== Test 4: Parallel Audio + Image ===")
    clear_cues()

    audio_path = os.path.join(MEDIA_DIR, "tone.wav")
    image_path = os.path.join(MEDIA_DIR, "test_image.png")

    call("cue.add_from_uri", {"uri": audio_path})
    time.sleep(0.5)
    call("cue.add_image_from_uri", {
        "uri": image_path, "duration": 3000,
    })
    time.sleep(1)

    cues = call("cue.list")
    check("4a: Two cues exist", len(cues) == 2)

    if len(cues) < 2:
        print("  SKIP: Not enough cues")
        return

    audio_id = cues[0]["id"]
    image_id = cues[1]["id"]

    # Group them (parallel is default mode=0)
    cue_ids = [audio_id, image_id]
    call("layout.select_cues", {"indices": [0, 1]})
    time.sleep(0.3)
    call("layout.context_action", {
        "action": "Group selected",
        "cue_ids": cue_ids,
    })
    time.sleep(1)

    all_cues = call("cue.list")
    group_cues = [
        c for c in all_cues if c["_type_"] == "GroupCue"
    ]
    check("4b: GroupCue created", len(group_cues) == 1)

    if not group_cues:
        print("  SKIP: No group cue")
        return

    group_id = group_cues[0]["id"]

    # Play the group (parallel mode starts both)
    call("cue.start", {"id": group_id})
    time.sleep(1)

    # Both children should be Running
    check("4c: Audio cue Running",
          cue_state(audio_id) == "Running")
    check("4d: Image cue Running",
          cue_state(image_id) == "Running")

    # Image auto-stops after 3s, audio continues
    check("4e: Image auto-stops",
          wait_state(image_id, "Stop", timeout=8))

    # Audio should still be going
    check("4f: Audio still Running after image stops",
          cue_state(audio_id) == "Running")

    # Stop the group
    call("cue.stop", {"id": group_id})
    check("4g: Audio cue stopped",
          wait_state(audio_id, "Stop", timeout=3))


def test_5_stop_and_replay():
    """Stop an image cue mid-display, then play it again.

    Regression test: uridecodebin removes dynamic pads on READY
    transition.  If _linked is not reset in stop(), the second
    play fails with 'not-linked'.
    """
    print("\n=== Test 5: Image Stop and Replay ===")
    clear_cues()

    image_path = os.path.join(MEDIA_DIR, "test_image.png")
    call("cue.add_image_from_uri", {
        "uri": image_path, "duration": 10000,
    })
    time.sleep(1)

    cues = call("cue.list")
    check("5a: Image cue added", len(cues) == 1)

    if not cues:
        print("  SKIP: No cue to test")
        return

    cue_id = cues[0]["id"]

    # First play, let it display briefly, then stop
    call("cue.start", {"id": cue_id})
    check("5b: First play reaches Running",
          wait_state(cue_id, "Running", timeout=5))
    time.sleep(1)
    call("cue.stop", {"id": cue_id})
    check("5c: First play reaches Stop",
          wait_state(cue_id, "Stop", timeout=3))

    # Second play — must not error
    time.sleep(0.5)
    call("cue.start", {"id": cue_id})
    check("5d: Second play reaches Running",
          wait_state(cue_id, "Running", timeout=5))

    time.sleep(0.5)
    state = call("cue.state", {"id": cue_id})
    check("5e: current_time advancing on replay",
          state["current_time"] > 0)

    call("cue.stop", {"id": cue_id})
    check("5f: Second play reaches Stop",
          wait_state(cue_id, "Stop", timeout=3))


def test_6_interrupt_mid_playback():
    """Interrupt (ESC) an image cue mid-display.

    Regression test: ImageInput's threading.Timer may fire EOS
    after interrupt() has already set the cue to Stop.  The old
    code in _on_eos called _ended() unconditionally, XOR-ing
    CueState.Running onto an already-Stop state and creating a
    stuck Stop|Running bitmask.
    """
    print("\n=== Test 6: Interrupt Image Cue Mid-Playback ===")
    clear_cues()

    image_path = os.path.join(MEDIA_DIR, "test_image.png")
    call("cue.add_image_from_uri", {
        "uri": image_path, "duration": 5000,
    })
    time.sleep(1)

    cues = call("cue.list")
    check("6a: Image cue added", len(cues) == 1)

    if not cues:
        print("  SKIP: No cue to test")
        return

    cue_id = cues[0]["id"]

    # Play the cue and let it run for 2-3 seconds
    call("cue.start", {"id": cue_id})
    check("6b: Cue reaches Running",
          wait_state(cue_id, "Running", timeout=5))

    time.sleep(2.5)

    # Interrupt (same as pressing ESC in the UI)
    call("cue.interrupt", {"id": cue_id})

    # Must reach Stop cleanly within a couple of seconds
    check("6c: Cue reaches Stop after interrupt",
          wait_state(cue_id, "Stop", timeout=5))

    # Wait for the EOS timer to fire (it was set for 5s total,
    # ~2.5s remain).  The cue must stay in Stop, not get stuck.
    time.sleep(4)
    check("6d: Cue still in Stop after EOS timer",
          cue_state(cue_id) == "Stop")

    # Verify the cue can be replayed (not stuck)
    call("cue.start", {"id": cue_id})
    check("6e: Cue replays after interrupt",
          wait_state(cue_id, "Running", timeout=5))

    call("cue.stop", {"id": cue_id})
    check("6f: Cue stops after replay",
          wait_state(cue_id, "Stop", timeout=3))


def test_7_indefinite_duration():
    """Image cue with duration=-1 displays until manually stopped."""
    print("\n=== Test 7: Indefinite Duration Image Cue ===")
    clear_cues()

    image_path = os.path.join(MEDIA_DIR, "test_image.png")
    call("cue.add_image_from_uri", {
        "uri": image_path, "duration": -1,
    })
    time.sleep(1)

    cues = call("cue.list")
    check("7a: Image cue added", len(cues) == 1)

    if not cues:
        print("  SKIP: No cue to test")
        return

    cue_id = cues[0]["id"]

    # Play the cue
    call("cue.start", {"id": cue_id})
    check("7b: Cue reaches Running",
          wait_state(cue_id, "Running", timeout=5))

    # Wait longer than a normal 5s image would display —
    # cue must still be Running (no EOS timer).
    time.sleep(7)
    check("7c: Still Running after 7s (no auto-stop)",
          cue_state(cue_id) == "Running")

    # Manual stop
    call("cue.stop", {"id": cue_id})
    check("7d: Cue reaches Stop after manual stop",
          wait_state(cue_id, "Stop", timeout=3))


# -- Main -------------------------------------------------------------

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
        test_1_image_cue_lifecycle()
        stop_all()
        test_2_image_cue_manual_stop()
        stop_all()
        test_3_slideshow_playlist()
        stop_all()
        test_4_parallel_audio_and_image()
        stop_all()
        test_5_stop_and_replay()
        stop_all()
        test_6_interrupt_mid_playback()
        stop_all()
        test_7_indefinite_duration()
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
