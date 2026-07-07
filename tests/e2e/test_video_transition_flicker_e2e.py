#!/usr/bin/env python3
"""E2E regression for Symptom B: video→video first-transition black flicker.

Covers ``docs/bugs/2026-05-29-video-cross-sink-gl-surface-wedge.md``
(Symptom B).  In a looping playlist GroupCue the FIRST inter-cue
boundary used to show a brief (~2 frame / ~33ms) black flicker while
every subsequent transition was clean — because each ``glimagesink``
paints a couple of black frames the first time *it* presents to the
shared projection XID, and cue B's first present lands on the first
live transition (cue A's is masked by the startup black).

Two properties make this test unusual:

  * **It must LOAD a session file, not add cues at runtime.**  The
    flicker only reproduces when the sinks are constructed during
    session load (before the video window is fully realised).  Adding
    the same cues to an already-running instance does NOT reproduce it.
    So the test builds the session in one LiSP instance, saves it, then
    relaunches LiSP with ``-f`` on the saved file.
  * **It reads pixels.**  Cue state and current_time advance normally
    through the flicker; only the projection surface goes black.  We
    grab the render-widget XID at 60fps with ``ffmpeg -window_id``
    (XGetImage — occlusion independent; a screen-region grab gives
    false blacks from occlusion and must not be used).

This is a CHARACTERIZATION test, not a regression guard (yet).  Symptom
B is deliberately left unfixed — the planned video-mixing/compositor
rearchitecture (a single persistent glimagesink fed by glvideomixer)
eliminates the whole cross-sink hand-off class, so the throwaway
"warm the sink at load" fix was not applied.  The test measures and
reports the flicker and always exits 0; when the compositor lands, flip
the commented assertion near the end into a real ``t.check`` and it
becomes the regression guard proving mixing fixed B.  See the bug doc
and ``docs/todo.md`` (Video pipeline → video mixing).

Requires an X display, ffmpeg (with x11grab) and xwininfo.  Skips
cleanly otherwise.

Run:
    poetry run python tests/e2e/test_video_transition_flicker_e2e.py
"""

import os
import re
import shutil
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(
    0, os.path.join(os.path.dirname(__file__), "..", "..",
                    "lisp", "plugins", "test_harness"))
from client import send_request  # noqa: E402
from helpers import (  # noqa: E402
    HOST, PORT, TestTracker, call, start_lisp, stop_lisp,
    wait_cues_loaded,
)

MEDIA_DIR = "/tmp/lisp_test_flicker"
CLIP_A = os.path.join(MEDIA_DIR, "flicker_a.mp4")
CLIP_B = os.path.join(MEDIA_DIR, "flicker_b.mp4")
SESSION = os.path.join(MEDIA_DIR, "flicker_loop.lsp")
FPS = 60
CUE_SECONDS = 4
DARK = 45          # luma below this = black
SETTLE_FRAMES = 30  # ignore first ~0.5s (widget just mapped)


# ── media ──────────────────────────────────────────────────────

def make_motion_h264(path, videotestsrc_args, seconds=CUE_SECONDS):
    """1080p H.264 clip with real inter-frame motion + audio.

    Motion + 1080p matters: this is what faithfully reproduces the
    ~2-frame first-transition flicker.  Static/solid-colour clips
    trigger a different (harder, warm-resistant) wedge instead — see
    the bug doc — so do not simplify this to a solid pattern.
    """
    if os.path.exists(path):
        return
    vframes = seconds * 30
    abuffers = int(seconds * 44100 / 1024) + 1
    subprocess.run([
        "gst-launch-1.0", "-e",
        "videotestsrc", *videotestsrc_args, f"num-buffers={vframes}",
        "!", "video/x-raw,width=1920,height=1080,framerate=30/1", "!",
        "videoconvert", "!", "x264enc", "tune=zerolatency", "!",
        "queue", "!", "mux.",
        "audiotestsrc", f"num-buffers={abuffers}", "freq=440", "!",
        "audioconvert", "!", "avenc_aac", "!", "queue", "!", "mux.",
        "mp4mux", "name=mux", "!", "filesink", f"location={path}",
    ], capture_output=True, timeout=120, check=True)


def create_media():
    os.makedirs(MEDIA_DIR, exist_ok=True)
    make_motion_h264(CLIP_A, ["pattern=smpte", "horizontal-speed=6"])
    make_motion_h264(CLIP_B, ["pattern=snow"])


# ── capture ────────────────────────────────────────────────────

def have_tools():
    return bool(
        os.environ.get("DISPLAY")
        and shutil.which("ffmpeg") and shutil.which("xwininfo")
        and shutil.which("gst-launch-1.0"))


def geometry(handle):
    out = subprocess.run(["xwininfo", "-id", str(handle)],
                         capture_output=True, text=True).stdout
    return int(re.search(r"Width:\s+(\d+)", out).group(1))  # sanity only


def record_rgb(handle, seconds):
    """60fps whole-window average RGB per frame via XGetImage."""
    raw = subprocess.run(
        ["ffmpeg", "-y", "-f", "x11grab", "-framerate", str(FPS),
         "-window_id", str(handle), "-i", ":0.0", "-t", str(seconds),
         "-vf", "scale=1:1", "-f", "rawvideo", "-pix_fmt", "rgb24",
         "pipe:1"],
        capture_output=True,
    ).stdout
    return [(raw[i], raw[i + 1], raw[i + 2])
            for i in range(0, len(raw) - 2, 3)]


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


# ── phase 1: build + save the session ──────────────────────────

def build_session():
    start_lisp("ListLayout")
    try:
        call("cue.add_video_from_uri", {"uri": CLIP_A})
        call("cue.add_video_from_uri", {"uri": CLIP_B})
        time.sleep(1.0)
        cues = sorted(call("cue.list"), key=lambda c: c["index"])
        a_id, b_id = cues[0]["id"], cues[1]["id"]
        call("layout.context_action",
             {"action": "Group selected", "cue_ids": [a_id, b_id]})
        time.sleep(0.5)
        group = next(
            c for c in sorted(call("cue.list"), key=lambda c: c["index"])
            if c["_type_"] == "GroupCue")["id"]
        call("cue.set_property",
             {"id": group, "property": "group_mode", "value": "playlist"})
        call("cue.set_property",
             {"id": group, "property": "loop", "value": True})
        call("cue.set_property",
             {"id": group, "property": "crossfade", "value": 0.0})
        call("session.save", {"path": SESSION})
        time.sleep(1.0)
    finally:
        stop_lisp()
    time.sleep(1.0)
    return os.path.exists(SESSION)


# ── phase 2: launch on the saved session, measure ──────────────

def _rpc(method, params=None):
    r = send_request(HOST, PORT, method, params or {})
    if "error" in r:
        raise RuntimeError(f"{method}: {r['error']['message']}")
    return r.get("result")


def measure_first_transition(t):
    proc = subprocess.Popen(
        [sys.executable, "-m", "lisp.main", "-l", "warning",
         "-f", SESSION],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    frames = []
    try:
        deadline = time.time() + 20
        loaded = False
        while time.time() < deadline:
            try:
                info = send_request(HOST, PORT, "session.info")
                if (info.get("result") or {}).get("has_session"):
                    loaded = True
                    break
            except Exception:
                pass
            time.sleep(0.5)
        t.check("session loaded from file", loaded)
        if not loaded:
            return

        # has_session flips True before cues finish loading from the
        # file; wait for the 2 videos + 1 GroupCue to be in the model.
        wait_cues_loaded(3)
        cues = sorted(_rpc("cue.list"), key=lambda c: c["index"])
        group = next(
            (c for c in cues if c["_type_"] == "GroupCue"), None)
        t.check("playlist group present after load", group is not None)
        if group is None:
            return
        children = [c for c in cues if c["_type_"] != "GroupCue"]
        b_id = sorted(children, key=lambda c: c["index"])[1]["id"]
        handle = _rpc("video_window.state")["handle"]
        t.check("projection handle valid", handle != 0)
        if not handle:
            return
        geometry(handle)

        # Subscribe to cue B's start so we can confirm (authoritatively,
        # via the harness) that the playlist actually advanced A→B —
        # independent of what the pixels show.
        sub = _rpc("signals.subscribe",
                   {"signal": "cue.started", "cue_id": b_id})
        sub_id = sub["subscription_id"]

        # Start the group, wait for cue A to actually be on screen
        # (render widget mapped) before grabbing by XID.
        _rpc("cue.execute", {"id": group["id"], "action": "Start"})
        vis_deadline = time.time() + 6
        while time.time() < vis_deadline:
            if _rpc("video_window.state").get("render_visible"):
                break
            time.sleep(0.1)
        time.sleep(0.2)

        # Record across the first A→B boundary (cue A ~CUE_SECONDS long).
        frames = record_rgb(handle, CUE_SECONDS + 3)
        try:
            ev = send_request(HOST, PORT, "signals.wait_for",
                              {"subscription_id": sub_id, "timeout": 1.0})
            b_started = "result" in ev
        except Exception:
            b_started = False
        try:
            _rpc("layout.stop_all")
        except Exception:
            pass
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()

    t.check("captured projection frames", len(frames) > SETTLE_FRAMES)
    if len(frames) <= SETTLE_FRAMES:
        return

    body = frames[SETTLE_FRAMES:]
    bright = sum(1 for f in body if luma(f) >= DARK)
    dark_run = max_dark_run(body)
    ms = dark_run / FPS * 1000
    print(f"  b_started={b_started} bright_frames={bright}/{len(body)} "
          f"max_dark_run={dark_run} frames ({ms:.1f} ms)")

    # Sanity: the playlist actually advanced A→B (harness truth), and we
    # captured live content (not an all-black grab).  These are the only
    # hard assertions — the test PASSES whether or not the flicker is
    # present, on purpose (see below).
    t.check("transition A→B occurred (cue B started)", b_started)
    t.check("captured live video (mostly bright)", bright > len(body) // 2)

    # CHARACTERIZATION (not a regression assertion yet).
    #
    # Symptom B is a ~2-frame black at the FIRST video→video transition
    # (see docs/bugs/2026-05-29-video-cross-sink-gl-surface-wedge.md).
    # We deliberately do NOT fix it with the throwaway "warm the sink at
    # load" hack, because the planned video-mixing/compositor
    # rearchitecture (single persistent glimagesink fed by glvideomixer)
    # eliminates the whole cross-sink hand-off class — A and B both — for
    # free.  So this test just measures and reports the flicker today and
    # always exits 0.
    #
    # >>> WHEN THE COMPOSITOR REARCHITECTURE LANDS <<<
    # the first transition should be clean; replace this report with the
    # commented assertion below and this becomes the regression guard
    # that proves mixing fixed Symptom B:
    #     t.check("no black flicker at first transition", dark_run <= 1)
    if dark_run >= 2:
        print(f"  CHARACTERIZATION: Symptom B present — {dark_run}-frame "
              f"({ms:.1f} ms) black at first transition (expected until "
              "the video-mixing/compositor rearchitecture lands).")
    else:
        print("  CHARACTERIZATION: no first-transition flicker detected — "
              "if the compositor rearchitecture has landed, flip the "
              "commented assertion above into a real regression check.")


def main():
    t = TestTracker()
    if not have_tools():
        print("  SKIP: need X display + ffmpeg + xwininfo + gstreamer")
        sys.exit(0)
    print("Generating test media (1920x1080 H.264, motion)...")
    create_media()
    print("Phase 1: building + saving session...")
    if not build_session():
        t.check("session file saved", False)
        sys.exit(t.summary())
    print("Phase 2: launching on saved session, measuring transition...")
    measure_first_transition(t)
    sys.exit(t.summary())


if __name__ == "__main__":
    main()
