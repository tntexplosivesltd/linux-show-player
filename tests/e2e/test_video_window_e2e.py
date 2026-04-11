#!/usr/bin/env python3
"""End-to-end tests for the video output window.

Verifies that video/image cues render into the shared
VideoOutputWindow (no stray windows), and that the window
shows/hides on play/stop.

Run:
    poetry run python tests/e2e/test_video_window_e2e.py

Options:
    --no-launch    Don't start/stop LiSP (attach to existing)
    --host HOST    Harness host (default: 127.0.0.1)
    --port PORT    Harness port (default: 8070)
"""

import argparse
import os
import subprocess
import sys
import time

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


def window_state():
    return call("video_window.state")


# -- Media file generation --------------------------------------------

def make_test_video(filename, duration_s=10):
    """Generate a WebM video with audio."""
    video_frames = int(duration_s * 30)
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
    result = subprocess.run(cmd, capture_output=True, timeout=60)
    return result.returncode == 0


def make_test_image(filename, width=320, height=240):
    """Generate a test PNG image."""
    cmd = [
        "gst-launch-1.0", "-e",
        "videotestsrc", "num-buffers=1", "!",
        f"video/x-raw,width={width},height={height}", "!",
        "pngenc", "!",
        "filesink", f"location={filename}",
    ]
    result = subprocess.run(cmd, capture_output=True, timeout=30)
    return result.returncode == 0


def create_test_media():
    os.makedirs(MEDIA_DIR, exist_ok=True)

    video_path = os.path.join(MEDIA_DIR, "test_video.webm")
    if not os.path.exists(video_path):
        if not make_test_video(video_path, duration_s=10):
            print("ERROR: Cannot generate test video",
                  file=sys.stderr)
            sys.exit(2)

    image_path = os.path.join(MEDIA_DIR, "test_image.png")
    if not os.path.exists(image_path):
        if not make_test_image(image_path):
            print("ERROR: Cannot generate test image",
                  file=sys.stderr)
            sys.exit(2)


# -- Setup ------------------------------------------------------------

def clear_cues():
    for cue in call("cue.list"):
        call("cue.remove", {"id": cue["id"]})
    time.sleep(0.3)


# -- Tests ------------------------------------------------------------

def test_1_window_exists():
    """VideoOutputWindow should be created at startup."""
    print("\n=== Test 1: Video Window Exists ===")

    ws = window_state()
    check("1a: Window exists", ws["exists"] is True)
    check("1b: Window has valid handle",
          ws["handle"] != 0)
    check("1c: Window hidden at startup",
          ws["visible"] is False)


def test_2_window_shows_when_video_cue_added():
    """Window should show when a video cue is added."""
    print("\n=== Test 2: Window Shows When Video Cue Added ===")
    clear_cues()

    ws = window_state()
    check("2a: Window hidden with no cues",
          ws["visible"] is False)

    video_path = os.path.join(MEDIA_DIR, "test_video.webm")
    call("cue.add_video_from_uri", {"uri": video_path})
    time.sleep(1)

    cues = call("cue.list")
    check("2b: Video cue added", len(cues) == 1)

    ws = window_state()
    check("2c: Window visible after cue added",
          ws["visible"] is True)

    if not cues:
        print("  SKIP: No cue")
        return

    cue_id = cues[0]["id"]

    # Remove the cue — window should hide
    call("cue.remove", {"id": cue_id})
    time.sleep(0.5)

    ws = window_state()
    check("2d: Window hidden after cue removed",
          ws["visible"] is False)


def test_3_window_shows_for_image_cues():
    """Window should show when an image cue is added."""
    print("\n=== Test 3: Window Shows for Image Cues ===")
    clear_cues()

    image_path = os.path.join(MEDIA_DIR, "test_image.png")
    call("cue.add_image_from_uri", {
        "uri": image_path, "duration": 3000,
    })
    time.sleep(1)

    cues = call("cue.list")
    check("3a: Image cue added", len(cues) == 1)

    ws = window_state()
    check("3b: Window visible for image cue",
          ws["visible"] is True)

    if not cues:
        print("  SKIP: No cue")
        return

    cue_id = cues[0]["id"]

    # Window should stay visible even after image plays and stops
    call("cue.start", {"id": cue_id})
    check("3c: Cue reaches Running",
          wait_state(cue_id, "Running", timeout=5))
    check("3d: Image cue auto-stops",
          wait_state(cue_id, "Stop", timeout=8))

    ws = window_state()
    check("3e: Window still visible after cue stops",
          ws["visible"] is True)


def test_4_shared_window_for_sequential_cues():
    """Multiple cues should reuse the same window."""
    print("\n=== Test 4: Shared Window for Sequential Cues ===")
    clear_cues()

    video_path = os.path.join(MEDIA_DIR, "test_video.webm")
    call("cue.add_video_from_uri", {"uri": video_path})
    call("cue.add_video_from_uri", {"uri": video_path})
    time.sleep(1)

    cues = call("cue.list")
    check("4a: Two video cues exist", len(cues) == 2)

    if len(cues) < 2:
        print("  SKIP: Not enough cues")
        return

    # Play first cue, get window handle
    cue1_id = cues[0]["id"]
    call("cue.start", {"id": cue1_id})
    wait_state(cue1_id, "Running", timeout=5)
    ws1 = window_state()
    handle1 = ws1["handle"]

    call("cue.stop", {"id": cue1_id})
    wait_state(cue1_id, "Stop", timeout=3)
    time.sleep(0.3)

    # Play second cue, verify same window handle
    cue2_id = cues[1]["id"]
    call("cue.start", {"id": cue2_id})
    wait_state(cue2_id, "Running", timeout=5)
    ws2 = window_state()
    handle2 = ws2["handle"]

    check("4b: Same window handle for both cues",
          handle1 == handle2)

    call("cue.stop", {"id": cue2_id})
    wait_state(cue2_id, "Stop", timeout=3)


def test_5_render_hidden_after_stop():
    """Render widget should hide when a cue stops."""
    print("\n=== Test 5: Render Hidden After Stop ===")
    clear_cues()

    video_path = os.path.join(MEDIA_DIR, "test_video.webm")
    call("cue.add_video_from_uri", {"uri": video_path})
    time.sleep(1)

    cues = call("cue.list")
    cue_id = cues[0]["id"]

    # Play — render surface should be visible
    call("cue.start", {"id": cue_id})
    wait_state(cue_id, "Running", timeout=5)
    ws = window_state()
    check("5a: Render visible during playback",
          ws["render_visible"] is True)

    # Stop — render surface should be hidden
    call("cue.stop", {"id": cue_id})
    wait_state(cue_id, "Stop", timeout=3)
    time.sleep(0.3)
    ws = window_state()
    check("5b: Render hidden after stop",
          ws["render_visible"] is False)


def test_6_image_then_video_sequence():
    """Video cue must play correctly after an image cue.

    Regression test: the image cue's glimagesink holds a GL
    context on the shared window.  Without releasing it, the
    video cue's sink cannot render — it shows the stale image.
    """
    print("\n=== Test 6: Image Then Video Sequence ===")
    clear_cues()

    image_path = os.path.join(MEDIA_DIR, "test_image.png")
    video_path = os.path.join(MEDIA_DIR, "test_video.webm")

    call("cue.add_image_from_uri", {
        "uri": image_path, "duration": 2000,
    })
    call("cue.add_video_from_uri", {"uri": video_path})
    time.sleep(1)

    cues = call("cue.list")
    check("6a: Two cues exist", len(cues) == 2)
    if len(cues) < 2:
        print("  SKIP: Not enough cues")
        return

    image_id = cues[0]["id"]
    video_id = cues[1]["id"]

    # Play image and let it auto-stop
    call("cue.start", {"id": image_id})
    check("6b: Image reaches Running",
          wait_state(image_id, "Running", timeout=5))
    check("6c: Image auto-stops",
          wait_state(image_id, "Stop", timeout=8))

    # Render should be hidden after image stops
    time.sleep(0.3)
    ws = window_state()
    check("6d: Render hidden after image stops",
          ws["render_visible"] is False)

    # Now play the video
    call("cue.start", {"id": video_id})
    check("6e: Video reaches Running",
          wait_state(video_id, "Running", timeout=5))

    # Render should be visible during video playback
    ws = window_state()
    check("6f: Render visible during video",
          ws["render_visible"] is True)

    # Verify video is actually progressing (not stuck)
    time.sleep(1)
    state = call("cue.state", {"id": video_id})
    check("6g: Video current_time > 500ms",
          state["current_time"] > 500)

    call("cue.stop", {"id": video_id})
    wait_state(video_id, "Stop", timeout=3)


def test_7_second_video_blocked_while_first_playing():
    """Starting a video cue while another is playing should be
    blocked — the second cue stays stopped."""
    print(
        "\n=== Test 7: Second Video Blocked While First "
        "Playing ==="
    )
    clear_cues()

    video_path = os.path.join(MEDIA_DIR, "test_video.webm")
    call("cue.add_video_from_uri", {"uri": video_path})
    call("cue.add_video_from_uri", {"uri": video_path})
    time.sleep(1)

    cues = call("cue.list")
    check("7a: Two video cues exist", len(cues) == 2)
    if len(cues) < 2:
        print("  SKIP: Not enough cues")
        return

    vid1_id = cues[0]["id"]
    vid2_id = cues[1]["id"]

    # Start first video (via execute, as the UI does)
    call("cue.execute", {"id": vid1_id, "action": "Start"})
    check("7b: First video reaches Running",
          wait_state(vid1_id, "Running", timeout=5))

    # Try to start the second video — should be blocked
    call("cue.execute", {"id": vid2_id, "action": "Start"})
    time.sleep(0.5)
    check("7c: Second video stays stopped",
          cue_state(vid2_id) == "Stop")

    # First video should still be running
    check("7d: First video still running",
          cue_state(vid1_id) == "Running")

    # Stop the first video, then start the second
    call("cue.stop", {"id": vid1_id})
    wait_state(vid1_id, "Stop", timeout=3)
    time.sleep(0.3)

    call("cue.execute", {"id": vid2_id, "action": "Start"})
    check("7e: Second video runs after first stopped",
          wait_state(vid2_id, "Running", timeout=5))

    call("cue.stop", {"id": vid2_id})
    wait_state(vid2_id, "Stop", timeout=3)


def test_8_image_blocked_while_video_playing():
    """Starting an image cue while a video is playing should be
    blocked."""
    print(
        "\n=== Test 8: Image Blocked While Video Playing ==="
    )
    clear_cues()

    video_path = os.path.join(MEDIA_DIR, "test_video.webm")
    image_path = os.path.join(MEDIA_DIR, "test_image.png")

    call("cue.add_video_from_uri", {"uri": video_path})
    call("cue.add_image_from_uri", {
        "uri": image_path, "duration": 3000,
    })
    time.sleep(1)

    cues = call("cue.list")
    check("8a: Video and image cues exist", len(cues) == 2)
    if len(cues) < 2:
        print("  SKIP: Not enough cues")
        return

    video_id = cues[0]["id"]
    image_id = cues[1]["id"]

    # Start the video (via execute, as the UI does)
    call("cue.execute", {"id": video_id, "action": "Start"})
    check("8b: Video reaches Running",
          wait_state(video_id, "Running", timeout=5))

    # Try to start the image — should be blocked
    call("cue.execute", {"id": image_id, "action": "Start"})
    time.sleep(0.5)
    check("8c: Image stays stopped",
          cue_state(image_id) == "Stop")

    call("cue.stop", {"id": video_id})
    wait_state(video_id, "Stop", timeout=3)


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
        test_1_window_exists()
        test_2_window_shows_when_video_cue_added()
        stop_all()
        test_3_window_shows_for_image_cues()
        stop_all()
        test_4_shared_window_for_sequential_cues()
        stop_all()
        test_5_render_hidden_after_stop()
        stop_all()
        test_6_image_then_video_sequence()
        stop_all()
        test_7_second_video_blocked_while_first_playing()
        stop_all()
        test_8_image_blocked_while_video_playing()
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
