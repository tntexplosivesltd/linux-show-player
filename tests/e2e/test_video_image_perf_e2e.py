#!/usr/bin/env python3
# This file is part of Linux Show Player
#
# Copyright 2026 Francesco Ceruti <ceppofrancy@gmail.com>
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

"""E2E: a huge still image cue shows quickly and plays smoothly.

Backdrop stills straight from a designer are often far larger than the
projector (6000x3375, 8000x5333). Each one plays as an image cue
(silent) and is measured:

  * time to first frame: cue.start -> the cue's first frame pushed into
    the projection (video.stats frame_seen);
  * smoothness while it is shown: the projection sink's rendered /
    dropped frames and average rate over HOLD_S;
  * LiSP's CPU use over the same window (printed, not judged).

The hard check is the cause, not the timing: the frames the cue pushes
into the projection must already fit the canvas. Timing and smoothness
are judged against a canvas-sized control still measured first in the
same run (first frame: the control's + an allowance for decoding the
bigger file), so a slow machine (CI, software GL) does not fail them
by itself.

Synthetic images (generated with GStreamer) by default;
IMAGE_PERF_FILES=<path>:<path>... measures real ones instead.

Run:
    poetry run python tests/e2e/test_video_image_perf_e2e.py
"""

import os
import shutil
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from tests.e2e import helpers  # noqa: E402
from tests.e2e.helpers import call, run_suite  # noqa: E402

HOLD_S = 5.0
FIRST_FRAME_TIMEOUT_S = 15.0
UNREGISTER_TIMEOUT_S = 5.0
# A huge still must play at least this fraction of the control's fps
# (before the fix: ~4%; loose, as both are single 5 s windows), and
# drop at most MAX_EXTRA_DROPPED more.
MIN_FPS_RATIO = 0.75
MAX_EXTRA_DROPPED = 5
# First frame may take this much longer than the control's. Decoding
# dominates (~1 s for an 8000x5333 JPEG on the dev host); before the
# fix the first frame was not the problem, the frame rate was.
FIRST_FRAME_ALLOWANCE_S = 4.0

CONTROL = ("control-1920x1080.png", 1920, 1080, "pngenc")
SYNTHETIC = [
    ("6000x3375.png", 6000, 3375, "pngenc"),
    # Y444 like the real 8000x5333 backdrop JPEG.
    ("8000x5333.jpg", 8000, 5333, "video/x-raw,format=Y444 ! jpegenc"),
]


def make_image(path, width, height, encoder):
    """A busy still (not a flat colour, so decoding costs something)."""
    subprocess.run(
        ["gst-launch-1.0", "-q", "videotestsrc", "num-buffers=1",
         "pattern=pinwheel", "!",
         f"video/x-raw,width={width},height={height}", "!",
         "videoconvert", "!", *encoder.split(), "!",
         "filesink", f"location={path}"],
        check=True,
    )


def cpu_seconds(pid):
    """utime + stime of `pid`, in seconds."""
    with open(f"/proc/{pid}/stat") as f:
        fields = f.read().rsplit(")", 1)[1].split()
    ticks = int(fields[11]) + int(fields[12])
    return ticks / os.sysconf("SC_CLK_TCK")


def stats():
    result = call("video.stats")
    if not result.get("exists"):
        raise RuntimeError("video.stats: no projection compositor")
    return result


def wait_unregistered():
    """True once no cue is registered with the projection, so the
    next cue's stats are its own."""
    deadline = time.monotonic() + UNREGISTER_TIMEOUT_S
    while time.monotonic() < deadline:
        if not stats()["cues"]:
            return True
        time.sleep(0.05)
    return False


def wait_first_frame(t0, cue_id):
    """(seconds from t0 until cue_id pushed its first frame, its
    stats entry), or (None, None) on timeout."""
    while time.monotonic() - t0 < FIRST_FRAME_TIMEOUT_S:
        for entry in stats()["cues"]:
            if entry["cue_id"] == cue_id and entry["frame_seen"]:
                return time.monotonic() - t0, entry
        time.sleep(0.01)
    return None, None


def caps_size(caps):
    """(width, height) from a caps string, or None."""
    def get(key):
        part = caps.split(f"{key}=(int)", 1)
        return int(part[1].split(",", 1)[0]) if len(part) == 2 else None

    w, h = get("width"), get("height")
    return None if w is None or h is None else (w, h)


def measure(t, path):
    """Play `path` as an image cue; returns its result dict, or None."""
    name = os.path.basename(path)
    t.check(f"{name}: no cue left registered",
            wait_unregistered())
    before = {c["id"] for c in call("cue.list")}
    call("cue.add_image_from_uri", {"uri": path, "duration": 60000})
    new = [c["id"] for c in call("cue.list") if c["id"] not in before]
    t.check(f"{name}: image cue added", len(new) == 1)
    if not new:
        return None
    cue_id = new[0]
    try:
        t0 = time.monotonic()
        call("cue.start", {"id": cue_id})
        first, entry = wait_first_frame(t0, cue_id)
        if first is None:
            t.check(f"{name}: first frame within "
                    f"{FIRST_FRAME_TIMEOUT_S}s", False)
            return None
        caps = entry["caps"]

        # Let the first second's catch-up settle, then measure.
        time.sleep(1.0)
        pid = helpers._lisp_proc.pid
        a = stats()["projection"]
        cpu_a, wall_a = cpu_seconds(pid), time.monotonic()
        time.sleep(HOLD_S)
        b = stats()
        cpu_b, wall_b = cpu_seconds(pid), time.monotonic()
    finally:
        call("cue.stop", {"id": cue_id})
        call("cue.remove", {"id": cue_id})

    p = b["projection"]
    if a is None or p is None:
        t.check(f"{name}: projection sink reports stats", False)
        return None
    wall = wall_b - wall_a
    result = {
        "name": name,
        "first": first,
        "fps": (p["rendered"] - a["rendered"]) / wall,
        "dropped": p["dropped"] - a["dropped"],
        "cpu": 100 * (cpu_b - cpu_a) / wall,
        "canvas": tuple(b["canvas"]),
        "size": caps_size(caps or ""),
    }
    print(f"  RESULT {name}: first_frame={first:.3f}s "
          f"fps={result['fps']:.1f} dropped={result['dropped']} "
          f"cpu={result['cpu']:.0f}% canvas={b['canvas']}")
    print(f"    cue caps: {caps}")
    return result


def judge(t, r, control):
    name, size, canvas = r["name"], r["size"], r["canvas"]
    # The cause, deterministically: what the cue pushes fits the canvas.
    t.check(f"{name}: pushed frames {size} fit the canvas {canvas}",
            size is not None
            and size[0] <= canvas[0] and size[1] <= canvas[1])
    if control is None:
        # The baseline itself: only meaningful if it actually played.
        t.check(f"{name}: control plays ({r['fps']:.1f} fps > 0)",
                r["fps"] > 0)
        return
    most_s = control["first"] + FIRST_FRAME_ALLOWANCE_S
    t.check(f"{name}: first frame in {r['first']:.2f}s (<= {most_s:.2f}s:"
            f" the control's + {FIRST_FRAME_ALLOWANCE_S}s)",
            r["first"] <= most_s)
    floor = MIN_FPS_RATIO * control["fps"]
    t.check(f"{name}: projection {r['fps']:.1f} fps (>= {floor:.1f}, "
            f"{MIN_FPS_RATIO:.0%} of the control's)", r["fps"] >= floor)
    most = control["dropped"] + MAX_EXTRA_DROPPED
    t.check(f"{name}: {r['dropped']} projection frames dropped "
            f"(<= {most}: the control's + {MAX_EXTRA_DROPPED})",
            r["dropped"] <= most)


def run_tests(t):
    if not os.environ.get("DISPLAY"):
        print("  SKIP: need an X display")
        return
    t.check("gst-launch-1.0 available (generates the stills)",
            bool(shutil.which("gst-launch-1.0")))
    tmp = tempfile.mkdtemp(prefix="lisp-imgperf-")
    try:
        def synth(spec):
            name, width, height, encoder = spec
            path = os.path.join(tmp, name)
            make_image(path, width, height, encoder)
            return path

        control = measure(t, synth(CONTROL))
        if control is not None:
            judge(t, control, None)
            if control["fps"] <= 0:
                control = None  # no baseline: judge only the caps
        files = [f for f in
                 os.environ.get("IMAGE_PERF_FILES", "").split(":") if f]
        if not files:
            files = [synth(spec) for spec in SYNTHETIC]
        for path in files:
            r = measure(t, path)
            if r is not None:
                judge(t, r, control)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    run_suite("Huge image cue performance", run_tests)
