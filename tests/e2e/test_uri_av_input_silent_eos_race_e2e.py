#!/usr/bin/env python3
"""E2E: regression for the UriAvInput silent-EOS pad-added race.

Builds the canonical reproducer from the bug write-up:

    outer (parallel):
        audio_cue   (tone_A.wav)
        inner       (playlist, loop=true):
            video_1 (test_video.webm — has audio + video)
            video_2 (test_video.webm)

Starts via ``layout.go`` (the keyboard-Go dispatch path; ``cue.start``
RPC was observed not to reliably trigger the race per
``docs/bugs/2026-05-03-uri-av-input-silent-eos-false-positive.md``)
and asserts:

  - the audio cue's ``started`` signal fires within 5 seconds;
  - its ``current_time`` advances (rules out the variant-A hard
    stall at 00:00.00);
  - no ``UriAvInput: no audio stream found`` log line was emitted
    during the run for any cue with a real audio stream;
  - no ``gst_segment_to_running_time`` / ``gst_segment_to_stream_time``
    GStreamer-CRITICAL assertions were emitted (those fire when the
    silent-EOS source has been spliced upstream of a real audio
    pad — the smoking gun for the race even when ``current_time``
    happens to advance, i.e. variant B in the bug doc).

Run a handful of iterations: the race is timing-sensitive, and
even with the fix in place we want to exercise the canonical
shape repeatedly to surface any regressions to the structure
itself (not just the splice decision, which is covered by
``tests/plugins/gst_backend/test_uri_av_input.py``).

Run:
    poetry run python tests/e2e/test_uri_av_input_silent_eos_race_e2e.py
"""

import os
import re
import subprocess
import sys
import time

from helpers import (
    call,
    clear_cues,
    cue_signal,
    make_tone,
    run_suite,
    signal_sub,
    stop_all,
    wait_current_time,
    wait_for_signal,
)

MEDIA_DIR = "/tmp/lisp_test_video"
LOG_PATH = "/tmp/lisp_silent_eos_race_e2e.log"
# 20 default keeps the suite under a minute on developer machines
# while giving the timing-sensitive race a real chance to fire if
# regressed.  The bug doc's verification-path target was 100×; a
# CI nightly run can override via RACE_E2E_ITERATIONS=100.
ITERATIONS = int(os.environ.get("RACE_E2E_ITERATIONS", 20))
# Cold-start warmup cap: the first starts of the heavy 3-pipeline
# structure can report a 0 audio position until caches/registry/JIT are
# warm; the count scales with machine slowness (~2 on a dev box, ~15 on
# a shared CI runner). Cap generously so a genuine hard stall still
# fails rather than looping forever.
WARMUP_CAP = 30

_SMOKING_GUN_AUDIO = re.compile(
    r"UriAvInput: no audio stream found"
)
_SMOKING_GUN_VIDEO = re.compile(
    r"UriAvInput: no video stream found"
)
_GST_SEGMENT_ASSERT = re.compile(
    r"gst_segment_to_(?:running|stream)_time: assertion"
)


def _make_test_video(filename, duration_s=4):
    """Generate a webm with audio + video (mirrors test_video_e2e)."""
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


def _ensure_media():
    os.makedirs(MEDIA_DIR, exist_ok=True)
    audio_path = os.path.join(MEDIA_DIR, "tone_A.wav")
    if not os.path.exists(audio_path):
        make_tone(audio_path, 440, 4.0)
    video_path = os.path.join(MEDIA_DIR, "race_video.webm")
    if not os.path.exists(video_path):
        if not _make_test_video(video_path, duration_s=4):
            print(
                "ERROR: gst-launch-1.0 failed to generate webm",
                file=sys.stderr,
            )
            sys.exit(2)
    return audio_path, video_path


def _build_canonical_structure(audio_path, video_path):
    """Return ``(audio_id, inner_id, outer_id)``."""
    clear_cues()

    # Add the leaves.
    with signal_sub("cue_model.item_added") as added:
        call("cue.add_from_uri", {"uri": audio_path})
        wait_for_signal(added, timeout=5)
        call("cue.add_video_from_uri", {"uri": video_path})
        wait_for_signal(added, timeout=5)
        call("cue.add_video_from_uri", {"uri": video_path})
        wait_for_signal(added, timeout=5)

    cues = call("cue.list")
    audio_id = cues[0]["id"]
    video_1_id = cues[1]["id"]
    video_2_id = cues[2]["id"]

    # Group [video_1, video_2] -> inner playlist with loop=true.
    call("layout.context_action", {
        "action": "Group selected",
        "cue_ids": [video_1_id, video_2_id],
    })
    time.sleep(0.3)
    inner_id = next(
        c["id"] for c in call("cue.list") if c["_type_"] == "GroupCue"
    )
    call("cue.set_property", {
        "id": inner_id, "property": "group_mode",
        "value": "playlist",
    })
    call("cue.set_property", {
        "id": inner_id, "property": "loop", "value": True,
    })

    # Group [audio, inner] -> outer parallel.
    call("layout.context_action", {
        "action": "Group selected",
        "cue_ids": [audio_id, inner_id],
    })
    time.sleep(0.3)
    outer_id = next(
        c["id"] for c in call("cue.list")
        if c["_type_"] == "GroupCue" and c["id"] != inner_id
    )

    return audio_id, inner_id, outer_id


def _read_log_since(offset):
    """Read /tmp log from byte ``offset`` to current end.

    The log file is opened in ``w`` mode by ``start_lisp`` and
    written append-only by the LiSP subprocess for the rest of
    its lifetime, so byte offsets remain stable across iterations
    — there is no rotation or truncation between iterations to
    invalidate the offset.
    """
    if not os.path.exists(LOG_PATH):
        return ""
    with open(LOG_PATH) as f:
        f.seek(offset)
        return f.read()


def _log_size():
    return os.path.getsize(LOG_PATH) if os.path.exists(LOG_PATH) else 0


def run_tests(t):
    audio_path, video_path = _ensure_media()
    audio_id, inner_id, outer_id = _build_canonical_structure(
        audio_path, video_path
    )

    # Standby cursor must point at the outer group so layout.go
    # starts it (mirrors keyboard "Space" with cursor on outer).
    # ``layout.go`` advances the cursor with each call, so reset
    # before every iteration.
    cues = call("cue.list")
    outer_index = next(
        i for i, c in enumerate(cues) if c["id"] == outer_id
    )

    seen_smoking_gun = []
    seen_assertions = []

    def _go_and_scan(label, advance_timeout):
        """Run one ``layout.go`` start→stop cycle of the outer group.

        Returns ``(started, current_time)``.  Scans the per-cycle log
        window for the variant-B markers (splice-misfire smoking gun and
        GStreamer-CRITICAL segment assertions) and records the label if
        seen — so warmup cycles contribute to race coverage too, not
        just the measured ones.
        """
        call("layout.set_standby_index", {"index": outer_index})
        log_before = _log_size()
        with cue_signal(audio_id, "started") as sub_a:
            call("layout.go", {})
            started = wait_for_signal(sub_a, timeout=5) is not None
        current_time = 0
        if started:
            wait_current_time(
                audio_id, min_ms=100, timeout=advance_timeout
            )
            current_time = call(
                "cue.state", {"id": audio_id}
            ).get("current_time", 0)
        new_log = _read_log_since(log_before)
        if _SMOKING_GUN_AUDIO.search(new_log):
            seen_smoking_gun.append(label)
        if _GST_SEGMENT_ASSERT.search(new_log):
            seen_assertions.append(label)
        stop_all()
        time.sleep(0.5)
        return started, current_time

    # Warm up before measuring.  The first starts of this heavy structure
    # construct three GStreamer pipelines (audio + two VP8 decoders); on
    # a cold, software-rendered runner the audio position can read 0 for
    # the first several starts until warm, and the count scales with
    # machine slowness — so a fixed sleep/poll flakes the per-iteration
    # variant-A check below.  Cycle until audio actually advances first.
    # A genuine variant-A hard stall never warms up, so the cap fails the
    # test loudly (and we skip the measured loop to stay in budget).
    warmed = False
    for _ in range(WARMUP_CAP):
        _, current_time = _go_and_scan("warmup", advance_timeout=3)
        if current_time > 100:
            warmed = True
            break
    t.check(
        f"structure warmed up within {WARMUP_CAP} starts "
        "(audio position advances)",
        warmed,
    )

    if warmed:
        for i in range(ITERATIONS):
            started, current_time = _go_and_scan(i, advance_timeout=5)
            t.check(
                f"iter {i}: audio cue started via layout.go",
                started,
            )
            if not started:
                continue
            # Variant A guard: clock must advance from 0 (rules out the
            # hard-stall presentation).
            t.check(
                f"iter {i}: audio current_time advanced "
                f"(got {current_time} ms)",
                current_time > 100,
            )

    # Variant B guard: even when current_time advances, the smoking-gun
    # log line + GStreamer-CRITICAL segment assertions mean the splice
    # mis-fired.  Checked across warmup + measured cycles.
    t.check(
        f"no spurious 'no audio stream found' across warmup + "
        f"{ITERATIONS} iterations (saw at: {seen_smoking_gun})",
        not seen_smoking_gun,
    )
    t.check(
        f"no gst_segment_to_*_time assertions across warmup + "
        f"{ITERATIONS} iterations (saw at: {seen_assertions})",
        not seen_assertions,
    )


if __name__ == "__main__":
    # log_level=info surfaces the UriAvInput logger.info lines;
    # GStreamer-CRITICAL warnings go to stderr regardless of the
    # Python log level so they'll show up in the same file.
    if os.path.exists(LOG_PATH):
        os.remove(LOG_PATH)
    run_suite(
        "URI A/V Input silent-EOS race E2E",
        run_tests,
        log_level="info",
        log_file=LOG_PATH,
    )
