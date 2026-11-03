#!/usr/bin/env python3
"""E2E: seeking a paused video cue updates the projection.

The old per-cue glimagesink showed the frame a paused pipeline
prerolled after a seek. With the VideoCompositor the frame has to be
pumped explicitly (VideoSink's new-preroll path), so this guards that
parity, and that the video is live again after resume (a stale first
sample after a pulled preroll once froze the pad).

The clip's position is readable from the projection pixels: it is dark
grey for its first 3s and bright for the next 3s.

  1. Pause in the dark half → projection shows dark grey.
  2. Seek (still paused) into the bright half → projection turns bright.
  3. Seek (still paused) back to the dark half → dark grey again.
  4. Resume → still dark at first, bright once playback crosses 3s
     (the video is live, not frozen on the preroll frame).

Requires an X display and ffmpeg (x11grab + lavfi); SKIPs cleanly
otherwise. Helpers are copied from the parity test (E2E scripts stay
standalone).

Run: poetry run python tests/e2e/test_video_paused_seek_e2e.py
"""

import os
import shutil
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))
from helpers import call, cue_state, run_suite, wait_state  # noqa: E402

MEDIA_DIR = "/tmp/lisp_test_paused_seek"
CLIP = os.path.join(MEDIA_DIR, "dark_then_bright.mp4")
HALF_S = 3          # dark for [0, 3s), bright for [3s, 6s)
DARK_LUMA = 60      # clip luma in the dark half
BRIGHT_LUMA = 220   # clip luma in the bright half
SETTLE = 0.8        # s for a paused-seek frame to reach the screen


# ── media ──────────────────────────────────────────────────────

def make_clip():
    if os.path.exists(CLIP):
        return
    os.makedirs(MEDIA_DIR, exist_ok=True)
    video = (
        f"color=c=black:s=640x360:r=30:d={2 * HALF_S},format=yuv420p,"
        f"geq=lum='if(lt(T,{HALF_S}),{DARK_LUMA},{BRIGHT_LUMA})'"
        ":cb=128:cr=128"
    )
    subprocess.run([
        "ffmpeg", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", video,
        "-f", "lavfi", "-i", f"sine=f=440:d={2 * HALF_S}",
        # Built-in encoders only (no libx264 needed); short GOP so a
        # seek lands on the requested half.
        "-c:v", "mpeg4", "-q:v", "3", "-g", "10",
        "-c:a", "aac", "-shortest", CLIP,
    ], capture_output=True, timeout=120, check=True)


# ── capture ────────────────────────────────────────────────────

def have_tools():
    return bool(os.environ.get("DISPLAY") and shutil.which("ffmpeg"))


def grab_gray(handle, width=64):
    """One full frame of the window, downscaled, as gray pixel values."""
    return subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-f", "x11grab",
         "-window_id", str(handle), "-i", os.environ["DISPLAY"],
         "-frames:v", "1", "-vf", f"scale={width}:-2",
         "-f", "rawvideo", "-pix_fmt", "gray", "pipe:1"],
        capture_output=True,
    ).stdout


def classify(pixels):
    """(grey fraction, bright fraction) of the projection. Letterbox
    bars are black and count as neither."""
    n = len(pixels) or 1
    grey = sum(1 for p in pixels if 35 <= p <= 110) / n
    bright = sum(1 for p in pixels if p >= 160) / n
    return grey, bright


def shows(handle, label):
    grey, bright = classify(grab_gray(handle))
    print(f"  {label}: grey={grey:.2f} bright={bright:.2f}")
    return grey, bright


def is_dark_half(grey, bright):
    return grey > 0.3 and bright < 0.05


def is_bright_half(grey, bright):
    return bright > 0.3


# ── checks ─────────────────────────────────────────────────────

def run_tests(t):
    if not have_tools():
        print("  SKIP: need X display + ffmpeg")
        return
    make_clip()
    call("cue.add_video_from_uri", {"uri": CLIP})
    time.sleep(1.5)
    cues = [c for c in call("cue.list") if c["_type_"] != "GroupCue"]
    t.check("video cue added", len(cues) == 1)
    if not cues:
        return
    cue_id = cues[0]["id"]
    handle = call("video_window.state").get("handle", 0)
    t.check("projection handle valid", handle != 0)
    if not handle:
        return

    print("\n-- 1: pause in the dark half --")
    call("cue.start", {"id": cue_id})
    t.check("cue running", wait_state(cue_id, "Running", timeout=5))
    time.sleep(1.0)
    call("cue.pause", {"id": cue_id})
    t.check("cue paused", wait_state(cue_id, "Pause", timeout=5))
    time.sleep(SETTLE)
    t.check("paused: projection shows the dark half",
            is_dark_half(*shows(handle, "paused at ~1s")))

    print("\n-- 2: paused seek into the bright half --")
    call("cue.seek", {"id": cue_id, "position": 4500})
    time.sleep(SETTLE)
    t.check("still paused after seek", cue_state(cue_id) == "Pause")
    t.check("paused seek updates the projection (bright half)",
            is_bright_half(*shows(handle, "paused at 4.5s")))

    print("\n-- 3: paused seek back to the dark half --")
    call("cue.seek", {"id": cue_id, "position": 1000})
    time.sleep(SETTLE)
    t.check("second paused seek updates the projection (dark half)",
            is_dark_half(*shows(handle, "paused at 1s")))

    print("\n-- 4: resume plays on (not frozen) --")
    call("cue.resume", {"id": cue_id})
    t.check("cue running again", wait_state(cue_id, "Running", timeout=5))
    time.sleep(0.5)
    t.check("resumed: still in the dark half (~1.5s)",
            is_dark_half(*shows(handle, "resumed ~1.5s")))
    time.sleep(2.5)
    t.check("video live after resume (reached the bright half)",
            is_bright_half(*shows(handle, "resumed ~4s")))

    call("cue.stop", {"id": cue_id})
    wait_state(cue_id, "Stop", timeout=5)


if __name__ == "__main__":
    run_suite("Video Paused Seek", run_tests)
