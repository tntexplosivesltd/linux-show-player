#!/usr/bin/env python3
"""E2E: cross-pipeline A/V sync acceptance test.

Video cues no longer render in their own pipeline: decoded frames are
pumped into the persistent VideoCompositor pipeline while the cue's
audio stays in the cue pipeline. This test proves the two stay in
sync on the real output.

A grey clip carries a 2-frame white flash and a sample-exact 1 kHz
beep at t = 1, 2, 3, 4, 5 s. Two ffmpeg processes capture the
projection window (x11grab by XID) and LiSP's audio. Both demuxers
stamp packets with the absolute wall clock (av_gettime) and -copyts
keeps those stamps, so the two files share a time base without any
start-up skew. (One process with both inputs does NOT work: x11grab
paces itself by sleeping in the shared read loop, which starves the
pulse input — dropped video frames and bunched audio timestamps.)
Each flash onset is paired with the nearest beep onset and
|flash − beep| must be within TOL_MS.

The same analysis is first run on the source clip itself, which must
show ~0 skew — this validates the measurement before it judges LiSP.

LiSP's audio is routed to a private PulseAudio null sink (PULSE_SINK,
set before LiSP is spawned) and captured from its monitor. This is
independent of the user's default-sink mute/volume (a muted sink's
monitor is silent) and inaudible; the module is unloaded at exit.

Without a PulseAudio monitor the audio half cannot run; the test then
says so explicitly and checks only the flash cadence (a coarse proxy).
SKIPs cleanly without X / ffmpeg / ffprobe / xwininfo.

Run: poetry run python tests/e2e/test_video_av_sync_e2e.py
"""

import atexit
import os
import shutil
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))
from helpers import call, run_suite, wait_state  # noqa: E402

MEDIA_DIR = "/tmp/lisp_test_avsync"
CLIP = os.path.join(MEDIA_DIR, "beep_flash.mp4")
CAPTURE_VIDEO = os.path.join(MEDIA_DIR, "capture_video.nut")
CAPTURE_AUDIO = os.path.join(MEDIA_DIR, "capture_audio.nut")
FLASH_TIMES_S = (1, 2, 3, 4, 5)
CLIP_SECONDS = 6
# The pulse demuxer stamps packets as wall clock minus a latency
# estimate that is wrong for its first ~1-2s (measured: beep intervals
# 1418/954/1000/1000ms for a 1000ms source). Start both captures this
# long before the cue so every beep lands after the stamps settle.
CAPTURE_WARMUP_S = 3.0
CAPTURE_SECONDS = int(CAPTURE_WARMUP_S) + CLIP_SECONDS + 2
TOL_MS = 66        # ~2 frames at 30fps; Phase-1 spike measured <=25ms
BEEP_DB = -20.0    # astats peak above this = beep (silence is -inf)
MIN_PAIRS = 3
NULL_SINK = "lisp_test_avsync"

# Set in __main__ before run_suite() spawns LiSP; None → proxy only.
MONITOR = None


# ── media ──────────────────────────────────────────────────────

def have_tools():
    return bool(
        os.environ.get("DISPLAY")
        and shutil.which("ffmpeg")
        and shutil.which("ffprobe")
        and shutil.which("xwininfo"))


def make_clip():
    """Grey 30fps clip: 2-frame white flash + sample-exact beep at each
    FLASH_TIMES_S. aevalsrc keys the beep on the sample's own time, so
    it is not quantised to audio-frame boundaries like `volume=enable`.
    """
    os.makedirs(MEDIA_DIR, exist_ok=True)
    if os.path.exists(CLIP):
        return
    on = "gte(t,1)*lt(mod(t,1),0.066)"
    subprocess.run([
        "ffmpeg", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i",
        f"color=c=0x404040:s=640x360:r=30:d={CLIP_SECONDS},"
        f"drawbox=x=0:y=0:w=iw:h=ih:color=white:t=fill:enable='{on}'",
        "-f", "lavfi", "-i",
        f"aevalsrc='if({on},0.8*sin(2*PI*1000*t),0)'"
        f":s=48000:d={CLIP_SECONDS}",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k", "-shortest", CLIP,
    ], check=True, timeout=120)


# ── analysis ───────────────────────────────────────────────────

def _probe(lavfi_graph, entry):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-f", "lavfi", "-i", lavfi_graph,
         "-show_entries", f"frame=pts_time:frame_tags={entry}",
         "-of", "csv=p=0"],
        capture_output=True, text=True, timeout=120,
    ).stdout
    rows = []
    for line in out.splitlines():
        parts = line.split(",")
        if len(parts) < 2:
            continue
        try:
            rows.append((float(parts[0]), float(parts[1])))
        except ValueError:
            continue  # e.g. "-inf" peak level on pure silence
    return rows


def _rising_edges(rows, threshold, min_gap_s=0.5):
    edges, prev_on, last = [], False, None
    for t, v in rows:
        on = v > threshold
        if on and not prev_on and (last is None or t - last >= min_gap_s):
            edges.append(t)
            last = t
        prev_on = on
    return edges


def flash_onsets(path):
    rows = _probe(f"movie={path},signalstats", "lavfi.signalstats.YAVG")
    if not rows:
        return []
    values = sorted(v for _t, v in rows)
    median, peak = values[len(values) // 2], values[-1]
    # Letterbox bars lower the window average, so threshold relative
    # to this capture's own grey (median) and white (peak) levels.
    return _rising_edges(rows, (median + peak) / 2)


def beep_onsets(path):
    rows = _probe(
        f"amovie={path},asetnsamples=n=48,astats=metadata=1:reset=1",
        "lavfi.astats.Overall.Peak_level")
    return _rising_edges(rows, BEEP_DB)


def pair_skews_ms(flashes, beeps):
    skews = []
    for f in flashes:
        if beeps:
            b = min(beeps, key=lambda x: abs(x - f))
            if abs(b - f) < 0.5:
                skews.append((f - b) * 1000)
    return skews


# ── capture ────────────────────────────────────────────────────

def setup_null_sink():
    """Load a private null sink and route LiSP (spawned later, inheriting
    this environment) to it. Returns its monitor source, or None."""
    if not shutil.which("pactl"):
        return None
    loaded = subprocess.run(
        ["pactl", "load-module", "module-null-sink",
         f"sink_name={NULL_SINK}"],
        capture_output=True, text=True)
    module = loaded.stdout.strip()
    if loaded.returncode != 0 or not module:
        return None
    atexit.register(subprocess.run, ["pactl", "unload-module", module],
                    capture_output=True)
    os.environ["PULSE_SINK"] = NULL_SINK
    return f"{NULL_SINK}.monitor"


def start_capture(handle, monitor):
    """Separate video/audio ffmpeg processes; -copyts keeps each
    demuxer's absolute wall-clock timestamps (shared time base). The
    duration is an INPUT -t: an output -t would be compared against
    those absolute stamps and end the capture at once."""
    dur = str(CAPTURE_SECONDS)
    procs = [subprocess.Popen(
        ["ffmpeg", "-loglevel", "error", "-y",
         "-f", "x11grab", "-framerate", "60",
         "-window_id", str(handle), "-t", dur,
         "-i", os.environ.get("DISPLAY", ":0"),
         "-copyts", "-vf", "scale=64:-2",
         "-c:v", "rawvideo", "-pix_fmt", "gray", CAPTURE_VIDEO])]
    if monitor:
        procs.append(subprocess.Popen(
            ["ffmpeg", "-loglevel", "error", "-y",
             "-f", "pulse", "-t", dur, "-i", monitor,
             "-copyts", "-c:a", "pcm_s16le", CAPTURE_AUDIO]))
    return procs


# ── test ───────────────────────────────────────────────────────

def run_tests(t):
    if not have_tools():
        print("  SKIP: need X + ffmpeg + ffprobe + xwininfo")
        return
    make_clip()

    # Validate the measurement on the source clip first.
    src_skews = pair_skews_ms(flash_onsets(CLIP), beep_onsets(CLIP))
    print(f"  source clip skew ms: {[round(s, 1) for s in src_skews]}")
    t.check("source clip flashes/beeps detected",
            len(src_skews) == len(FLASH_TIMES_S))
    t.check("source clip is aligned (measurement sound)",
            bool(src_skews) and max(abs(s) for s in src_skews) <= 5)

    call("cue.add_video_from_uri", {"uri": CLIP})
    time.sleep(1.5)
    cues = call("cue.list")
    t.check("clip added", len(cues) == 1)
    if not cues:
        return
    cue_id = cues[0]["id"]
    handle = call("video_window.state").get("handle", 0)
    t.check("projection handle valid", handle != 0)
    if not handle:
        return

    monitor = MONITOR
    if monitor is None:
        print("  NOTE: no PulseAudio monitor — running the flash-cadence "
              "proxy only, NOT the full A/V correlation.")
    procs = start_capture(handle, monitor)
    time.sleep(CAPTURE_WARMUP_S)
    call("cue.start", {"id": cue_id})
    for proc in procs:
        try:
            proc.wait(timeout=CAPTURE_SECONDS + 20)
        except subprocess.TimeoutExpired:
            proc.kill()
    t.check("capture finished",
            all(p.returncode == 0 for p in procs)
            and os.path.getsize(CAPTURE_VIDEO) > 100_000)
    call("cue.stop", {"id": cue_id})
    wait_state(cue_id, "Stop", timeout=3)

    flashes = flash_onsets(CAPTURE_VIDEO)
    print(f"  projected flashes: {len(flashes)}")
    t.check("projected flashes detected", len(flashes) >= MIN_PAIRS)

    if monitor is None:
        gaps = [(b - a) * 1000 for a, b in zip(flashes, flashes[1:])]
        print(f"  flash intervals ms: {[round(g) for g in gaps]}")
        t.check("flash cadence within tolerance (proxy)",
                bool(gaps) and all(abs(g - 1000) <= TOL_MS for g in gaps))
        return

    beeps = beep_onsets(CAPTURE_AUDIO)
    skews = pair_skews_ms(flashes, beeps)
    print(f"  captured beeps: {len(beeps)}")
    print(f"  A/V skew ms (video − audio): {[round(s, 1) for s in skews]}")
    t.check("flash/beep pairs found", len(skews) >= MIN_PAIRS)
    t.check(f"A/V sync within {TOL_MS} ms",
            bool(skews) and max(abs(s) for s in skews) <= TOL_MS)


if __name__ == "__main__":
    MONITOR = setup_null_sink()
    run_suite("A/V Sync (cross-pipeline)", run_tests)
