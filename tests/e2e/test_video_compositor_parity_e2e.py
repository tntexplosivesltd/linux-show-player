#!/usr/bin/env python3
"""E2E: behaviour parity after the VideoCompositor rearchitecture.

Confirms the "no operator-visible behaviour change" contract by
reading projection pixels:

  1. Standalone stop → black. After a playing video cue is stopped
     the WHOLE projection must be black — every sampled pixel, not an
     average (a partly-black window must fail).
  2. Playlist loop seamless over many iterations. A 2-child looping
     playlist GroupCue runs through >= MIN_ADVANCES auto-advances
     (counted from cue.started events) with no dark run at any
     boundary — stronger than the first-transition flicker guard.
  3. One video at a time. With one video cue Running, starting a
     second one must not take effect (VideoExclusiveManager, now
     backed by the compositor). The operator notification is covered
     by the unit tests; the harness cannot observe it.

Requires an X display, ffmpeg (x11grab) and gst-launch-1.0; SKIPs
cleanly otherwise. Helpers are copied from the flicker test (E2E
scripts stay standalone).

Run: poetry run python tests/e2e/test_video_compositor_parity_e2e.py
"""

import os
import shutil
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))
from helpers import (  # noqa: E402
    call, cue_state, make_media, media_cache_dir, media_path, run_suite,
    wait_state,
)

MEDIA_DIR = media_cache_dir("parity")
FPS = 60
CUE_SECONDS = 2
MIN_ADVANCES = 5
DARK = 45           # luma below this = black
SETTLE_FRAMES = 30  # ignore the first ~0.5s of a capture


# ── media ──────────────────────────────────────────────────────

def _motion_h264_cmd(out, videotestsrc_args, seconds=CUE_SECONDS):
    """1080p H.264 clip with inter-frame motion + audio."""
    vframes = seconds * 30
    abuffers = int(seconds * 44100 / 1024) + 1
    return [
        "gst-launch-1.0", "-e",
        "videotestsrc", *videotestsrc_args, f"num-buffers={vframes}",
        "!", "video/x-raw,width=1920,height=1080,framerate=30/1", "!",
        "videoconvert", "!", "x264enc", "tune=zerolatency", "!",
        "queue", "!", "mux.",
        "audiotestsrc", f"num-buffers={abuffers}", "freq=440", "!",
        "audioconvert", "!", "avenc_aac", "!", "queue", "!", "mux.",
        "mp4mux", "name=mux", "!", "filesink", f"location={out}",
    ]


ARGS_A = ["pattern=smpte", "horizontal-speed=6"]
ARGS_B = ["pattern=snow"]
CLIP_A = media_path(
    MEDIA_DIR, "parity_a.mp4", _motion_h264_cmd(None, ARGS_A))
CLIP_B = media_path(
    MEDIA_DIR, "parity_b.mp4", _motion_h264_cmd(None, ARGS_B))


def make_motion_h264(path, videotestsrc_args):
    make_media(path, lambda out: subprocess.run(
        _motion_h264_cmd(out, videotestsrc_args),
        capture_output=True, timeout=120, check=True))


def create_media():
    make_motion_h264(CLIP_A, ARGS_A)
    make_motion_h264(CLIP_B, ARGS_B)


# ── capture ────────────────────────────────────────────────────

def have_tools():
    return bool(
        os.environ.get("DISPLAY")
        and shutil.which("ffmpeg") and shutil.which("gst-launch-1.0"))


def record_rgb(handle, seconds):
    """60fps whole-window average RGB per frame via XGetImage."""
    raw = subprocess.run(
        ["ffmpeg", "-y", "-f", "x11grab", "-framerate", str(FPS),
         "-window_id", str(handle), "-i", os.environ["DISPLAY"],
         "-t", str(seconds), "-vf", "scale=1:1", "-f", "rawvideo",
         "-pix_fmt", "rgb24", "pipe:1"],
        capture_output=True,
    ).stdout
    return [(raw[i], raw[i + 1], raw[i + 2])
            for i in range(0, len(raw) - 2, 3)]


def grab_gray(handle, width=64):
    """One full frame of the window, downscaled, as gray pixel values."""
    return subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-f", "x11grab",
         "-window_id", str(handle), "-i", os.environ["DISPLAY"],
         "-frames:v", "1", "-vf", f"scale={width}:-2",
         "-f", "rawvideo", "-pix_fmt", "gray", "pipe:1"],
        capture_output=True,
    ).stdout


def luma(rgb):
    r, g, b = rgb
    return 0.3 * r + 0.59 * g + 0.11 * b


def max_dark_run(frames):
    run = best = 0
    for f in frames:
        if luma(f) < DARK:
            run += 1
            best = max(best, run)
        else:
            run = 0
    return best


# ── checks ─────────────────────────────────────────────────────

def video_cues():
    cues = sorted(call("cue.list"), key=lambda c: c["index"])
    return [c["id"] for c in cues if c["_type_"] != "GroupCue"]


def check_standalone_stop_black(t, handle, cue_id):
    print("\n-- 1: standalone stop → black --")
    call("cue.start", {"id": cue_id})
    t.check("video cue running", wait_state(cue_id, "Running", timeout=5))
    time.sleep(1.0)
    playing = grab_gray(handle)
    t.check("projection shows video while playing",
            bool(playing) and sum(playing) / len(playing) >= DARK)

    call("cue.stop", {"id": cue_id})
    t.check("video cue stopped", wait_state(cue_id, "Stop", timeout=5))
    time.sleep(0.6)  # past the compositor's standalone linger
    stopped = grab_gray(handle)
    brightest = max(stopped) if stopped else 255
    print(f"  after stop: brightest pixel {brightest} "
          f"(of {len(stopped)} sampled)")
    t.check("whole projection black after stop (every pixel)",
            bool(stopped) and brightest < DARK)


def check_exclusive(t, a_id, b_id):
    print("\n-- 3: one video at a time --")
    call("cue.start", {"id": a_id})
    t.check("first video running", wait_state(a_id, "Running", timeout=5))
    # cue.execute, not cue.start: the exclusivity gate lives in
    # Cue.execute() (the GO / layout / trigger path); the harness's
    # cue.start calls Cue.start() directly and bypasses it.
    call("cue.execute", {"id": b_id, "action": "Start"})
    time.sleep(1.0)
    t.check("second video blocked", cue_state(b_id) != "Running")
    t.check("first video still running", cue_state(a_id) == "Running")
    call("cue.stop", {"id": a_id})
    wait_state(a_id, "Stop", timeout=5)
    time.sleep(0.6)


def check_playlist_seamless(t, handle, a_id, b_id):
    print("\n-- 2: playlist loop seamless --")
    call("layout.context_action",
         {"action": "Group selected", "cue_ids": [a_id, b_id]})
    time.sleep(0.5)
    group = next(c["id"] for c in call("cue.list")
                 if c["_type_"] == "GroupCue")
    for prop, value in (("group_mode", "playlist"), ("loop", True),
                        ("crossfade", 0.0)):
        call("cue.set_property",
             {"id": group, "property": prop, "value": value})
    subs = [call("signals.subscribe",
                 {"signal": "cue.started", "cue_id": cid})
            ["subscription_id"] for cid in (a_id, b_id)]

    call("cue.execute", {"id": group, "action": "Start"})
    seconds = CUE_SECONDS * (MIN_ADVANCES + 1) + 1
    frames = record_rgb(handle, seconds)
    starts = sum(
        len(call("signals.poll", {"subscription_id": s})["events"])
        for s in subs)
    call("cue.execute", {"id": group, "action": "Stop"})
    time.sleep(0.6)

    advances = starts - 1  # the first start is not an advance
    body = frames[SETTLE_FRAMES:]
    dark_run = max_dark_run(body)
    bright = sum(1 for f in body if luma(f) >= DARK)
    print(f"  advances={advances} bright={bright}/{len(body)} "
          f"max_dark_run={dark_run} frames "
          f"({dark_run / FPS * 1000:.1f} ms)")
    t.check(f">= {MIN_ADVANCES} playlist auto-advances",
            advances >= MIN_ADVANCES)
    t.check("captured live video (mostly bright)",
            bool(body) and bright > len(body) // 2)
    t.check("no black gap at any auto-advance", dark_run <= 1)


def run_tests(t):
    if not have_tools():
        print("  SKIP: need X display + ffmpeg + gstreamer")
        return
    create_media()
    call("cue.add_video_from_uri", {"uri": CLIP_A})
    call("cue.add_video_from_uri", {"uri": CLIP_B})
    time.sleep(1.5)
    ids = video_cues()
    t.check("two video cues added", len(ids) == 2)
    if len(ids) != 2:
        return
    a_id, b_id = ids
    handle = call("video_window.state").get("handle", 0)
    t.check("projection handle valid", handle != 0)
    if not handle:
        return

    check_standalone_stop_black(t, handle, a_id)
    check_exclusive(t, a_id, b_id)
    check_playlist_seamless(t, handle, a_id, b_id)


if __name__ == "__main__":
    run_suite("Compositor Behaviour Parity", run_tests)
