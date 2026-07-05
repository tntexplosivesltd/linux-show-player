#!/usr/bin/env python3
"""End-to-end regression test for the image→video GL-surface wedge.

Covers ``docs/bugs/2026-05-29-video-cross-sink-gl-surface-wedge.md``
(Symptom A): after an ``ImageInput`` cue reaches natural EOS, the very
next video cue triggered on the cold hand-off would play its audio and
advance its clock while the projection surface stayed frozen on the
image's last frame.

Why this test captures pixels instead of cue state
--------------------------------------------------
The wedge is *presentation-only*.  During it the video cue reaches
``Running`` and its ``current_time`` advances exactly as if all were
well — the freeze is entirely on the GL surface.  So the state-level
checks in ``test_video_window_e2e.py`` (``test_6_image_then_video_sequence``)
pass whether or not the bug is present.  The only way to catch a
regression is to read the actual pixels of the projection render
surface.  This test does that via ImageMagick's ``import -window
<xid>`` (the XID is ``VideoOutputWindow._render_widget.winId()``, the
same handle glimagesink binds) and checks two independent signals that
agree:

  * **mean colour** — a solid-red image left frozen makes the surface
    red; the video content is not red.
  * **frame-to-frame motion** — a frozen image shows zero motion; the
    live video (television-snow pattern) changes every frame.

A wedge is reported only when BOTH agree (red *and* frozen), and the
test additionally asserts the positive: the video is not red *and*
shows motion.

The cue add order is load-bearing: the video cue is added FIRST so its
sink binds the shared projection XID *before* the image's.  The wedge
only manifests when the incoming (video) sink holds the older bind and
the outgoing (image) sink the newer one — mirroring ``test_3.lsp``,
where the video cue precedes the image in the list.

Requires an X display and ImageMagick (``import``, ``convert``).
Skips cleanly if either is unavailable.

Run:
    poetry run python tests/e2e/test_video_wedge_e2e.py

Options:
    --no-launch    Don't start/stop LiSP (attach to existing)
    --host HOST    Harness host (default: 127.0.0.1)
    --port PORT    Harness port (default: 8070)
"""

import os
import shutil
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))
from helpers import (  # noqa: E402
    call,
    clear_cues,
    cue_signal,
    run_suite,
    wait_for_signal,
    wait_state,
)

MEDIA_DIR = "/tmp/lisp_test_wedge"
IMAGE_PATH = os.path.join(MEDIA_DIR, "wedge_red.png")
VIDEO_PATH = os.path.join(MEDIA_DIR, "wedge_snow.webm")

# ``redness`` of a captured frame is ``mean.r - max(mean.g, mean.b)``
# (channels normalised 0..1).  A solid-red frozen image scores ~1.0;
# the television-snow video is grey and scores ~0.
RED_THRESHOLD = 0.35
# Mean of the per-pixel difference image between two captures.  A frozen
# frame scores ~0; television snow changes every pixel every frame and
# scores well above this.
MOTION_THRESHOLD = 0.02


# ── Media generation ───────────────────────────────────────────

def _run_gst(args, timeout):
    return subprocess.run(
        ["gst-launch-1.0", "-e", *args],
        capture_output=True, timeout=timeout,
    ).returncode == 0


def make_red_image(path, width=320, height=240):
    """A solid-red still PNG (the frame the wedge freezes on)."""
    return _run_gst([
        "videotestsrc", "pattern=red", "num-buffers=1", "!",
        f"video/x-raw,width={width},height={height}", "!",
        "pngenc", "!",
        "filesink", f"location={path}",
    ], timeout=30)


def make_snow_video(path, width=320, height=240, duration_s=6):
    """A television-snow WebM with audio — every frame differs, so a
    frozen projection is unmistakable, and the mean colour is grey
    (never red)."""
    video_frames = int(duration_s * 30)
    audio_buffers = int(duration_s * 44100 / 1024) + 1
    return _run_gst([
        "videotestsrc", "pattern=snow", f"num-buffers={video_frames}",
        "!", f"video/x-raw,width={width},height={height}", "!",
        "videoconvert", "!", "vp8enc", "deadline=1", "!",
        "queue", "!", "mux.",
        "audiotestsrc", f"num-buffers={audio_buffers}", "freq=440",
        "!", "audioconvert", "!", "vorbisenc", "!",
        "queue", "!", "mux.",
        "webmmux", "name=mux", "!",
        "filesink", f"location={path}",
    ], timeout=120)


def create_wedge_media():
    os.makedirs(MEDIA_DIR, exist_ok=True)
    if not os.path.exists(IMAGE_PATH):
        if not make_red_image(IMAGE_PATH):
            print("ERROR: cannot generate red image", file=sys.stderr)
            sys.exit(2)
    if not os.path.exists(VIDEO_PATH):
        if not make_snow_video(VIDEO_PATH):
            print("ERROR: cannot generate snow video", file=sys.stderr)
            sys.exit(2)


# ── Pixel capture (ImageMagick) ────────────────────────────────

# ImageMagick 7 renames ``convert`` to ``magick``; fall back to the
# legacy name so the test runs on either.  ``import`` is unchanged.
_MAGICK = "magick" if shutil.which("magick") else "convert"


def have_capture_tools():
    return bool(shutil.which("import")
                and (shutil.which("magick") or shutil.which("convert")))


def capture(handle, path):
    """Grab the render-surface window by XID; True on a non-empty PNG."""
    try:
        rc = subprocess.run(
            ["import", "-silent", "-window", str(handle), path],
            capture_output=True, timeout=10,
        ).returncode
    except (subprocess.TimeoutExpired, OSError):
        return False
    return rc == 0 and os.path.exists(path) and os.path.getsize(path) > 0


def mean_rgb(path):
    """Mean per-channel colour (0..1).

    Forces sRGB TrueColor first: ImageMagick stores an all-gray capture
    (e.g. television snow, where R==G==B) as a single-channel grayscale
    PNG, which would make ``fx:mean.g``/``fx:mean.b`` report 0 and
    spuriously inflate "redness".  Expanding to three channels makes a
    gray frame score r==g==b (redness 0) while a genuinely red frozen
    image still scores r≫g,b.
    """
    out = subprocess.run(
        [_MAGICK, path, "-colorspace", "sRGB", "-type", "TrueColor",
         "-format", "%[fx:mean.r] %[fx:mean.g] %[fx:mean.b]", "info:"],
        capture_output=True, text=True, timeout=10,
    ).stdout.strip()
    r, g, b = (float(x) for x in out.split())
    return r, g, b


def frame_diff(path_a, path_b):
    """Mean per-pixel difference (0..1) between two captures."""
    out = subprocess.run(
        [_MAGICK, path_a, path_b, "-compose", "difference",
         "-composite", "-format", "%[fx:mean]", "info:"],
        capture_output=True, text=True, timeout=10,
    ).stdout.strip()
    return float(out)


# ── Test ───────────────────────────────────────────────────────

def run_tests(t):
    if not have_capture_tools():
        print("  SKIP: ImageMagick (import/convert) not available")
        return

    create_wedge_media()
    clear_cues()

    # Order matters: video FIRST so its sink binds the projection XID
    # before the image's (see module docstring / bug doc).
    call("cue.add_video_from_uri", {"uri": VIDEO_PATH})
    call("cue.add_image_from_uri", {"uri": IMAGE_PATH, "duration": 2000})
    time.sleep(1)

    cues = call("cue.list")
    t.check("both cues added", len(cues) == 2)
    if len(cues) < 2:
        return
    video_id = cues[0]["id"]
    image_id = cues[1]["id"]

    win = call("video_window.state")
    handle = win.get("handle", 0)
    t.check("projection window handle is valid", handle != 0)
    if not handle:
        return

    # Cold hand-off: play the image, and the instant it reaches natural
    # EOS start the video — this is the transition that used to wedge.
    with cue_signal(image_id, "end") as end_sub:
        call("cue.start", {"id": image_id})
        t.check("image reaches Running",
                wait_state(image_id, "Running", timeout=5))
        ended = wait_for_signal(end_sub, timeout=8)
        t.check("image reaches natural EOS", ended is not None)

    call("cue.start", {"id": video_id})
    t.check("video reaches Running",
            wait_state(video_id, "Running", timeout=5))

    # The wedge illusion: cue state advances normally even when frozen.
    time.sleep(0.8)
    state = call("cue.state", {"id": video_id})
    t.check("video clock advances (state-level looks fine)",
            state["current_time"] > 300)

    # The pixel truth: capture the projection surface several times.
    time.sleep(0.3)  # let the sink present its first buffers
    frames = []
    for i in range(4):
        p = os.path.join(MEDIA_DIR, f"cap_{i}.png")
        if capture(handle, p):
            frames.append(p)
        time.sleep(0.35)

    t.check("captured projection frames", len(frames) >= 2)
    if len(frames) < 2:
        return

    rednesses = []
    for f in frames:
        r, g, b = mean_rgb(f)
        rednesses.append(r - max(g, b))
    motions = [
        frame_diff(frames[i], frames[i + 1])
        for i in range(len(frames) - 1)
    ]
    max_redness = max(rednesses)
    max_motion = max(motions)
    print(f"  redness per frame: {[round(x, 3) for x in rednesses]}")
    print(f"  motion per gap:    {[round(x, 4) for x in motions]}")

    wedged = max_redness > RED_THRESHOLD and max_motion < MOTION_THRESHOLD
    t.check("projection NOT wedged on the image's red frame", not wedged)
    t.check("projection is not red (video content rendering)",
            max_redness <= RED_THRESHOLD)
    t.check("projection shows motion (video is live)",
            max_motion >= MOTION_THRESHOLD)

    call("cue.stop", {"id": video_id})
    wait_state(video_id, "Stop", timeout=3)


if __name__ == "__main__":
    run_suite("Image→Video Wedge (pixel regression)", run_tests)
