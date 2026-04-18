#!/usr/bin/env python3
"""End-to-end tests for image cue support via the test harness.

Tests image cue lifecycle (add, play, auto-stop by duration),
slideshow via GroupCue playlist mode, parallel audio+image,
pause/resume, and error handling for missing files.

Run:
    poetry run python tests/e2e/test_image_e2e.py

Options:
    --no-launch    Don't start/stop LiSP (attach to existing)
    --host HOST    Harness host (default: 127.0.0.1)
    --port PORT    Harness port (default: 8070)
"""

import os
import subprocess
import sys
import time

from helpers import (
    call,
    clear_cues,
    cue_signal,
    cue_state,
    make_tone,
    run_suite,
    signal_sub,
    stop_all,
    wait_for_signal,
    wait_state,
)

MEDIA_DIR = "/tmp/lisp_test_image"


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


# -- Helpers ----------------------------------------------------------

def _add_image(uri, duration=None):
    """Add an image cue (waiting on item_added) and return the dict."""
    params = {"uri": uri}
    if duration is not None:
        params["duration"] = duration
    with signal_sub("cue_model.item_added") as sub:
        call("cue.add_image_from_uri", params)
        event = wait_for_signal(sub, timeout=5)
    assert event is not None, "cue_model.item_added did not fire"
    return call("cue.list")[-1]


# -- Tests ------------------------------------------------------------

def test_1_image_cue_lifecycle(t):
    """Add an image cue, verify play and auto-stop by duration."""
    print("\n=== Test 1: Image Cue Lifecycle ===")
    clear_cues()

    image_path = os.path.join(MEDIA_DIR, "test_image.png")
    cue = _add_image(image_path, duration=3000)
    t.check("1a: Image cue added", cue is not None)
    cue_id = cue["id"]
    t.check("1b: Cue is GstMediaCue",
            cue["_type_"] == "GstMediaCue")

    # Play — subscribe to started AND end in parallel.  Natural
    # EOS (the image timer firing) emits the 'end' signal via
    # Cue._ended(); only explicit cue.stop() emits 'stopped'.
    with cue_signal(cue_id, "started") as start_sub, \
            cue_signal(cue_id, "end") as end_sub:
        call("cue.start", {"id": cue_id})
        t.check("1c: Cue reaches Running",
                wait_for_signal(start_sub, timeout=5) is not None)

        # Auto-stops after 3s (duration enforcement via EOS timer).
        t.check("1d: Cue ends after duration",
                wait_for_signal(end_sub, timeout=8) is not None)


def test_2_image_cue_manual_stop(t):
    """Play an image cue and stop it manually before duration."""
    print("\n=== Test 2: Image Cue Manual Stop ===")
    clear_cues()

    image_path = os.path.join(MEDIA_DIR, "test_image.png")
    cue = _add_image(image_path, duration=10000)
    t.check("2a: Image cue added", cue is not None)
    cue_id = cue["id"]

    with cue_signal(cue_id, "started") as sub:
        call("cue.start", {"id": cue_id})
        t.check("2b: Cue reaches Running",
                wait_for_signal(sub, timeout=5) is not None)

    # Verify time is advancing
    time.sleep(0.5)
    state = call("cue.state", {"id": cue_id})
    t.check("2c: current_time > 0",
            state["current_time"] > 0)

    # Manual stop before duration
    with cue_signal(cue_id, "stopped") as sub:
        call("cue.stop", {"id": cue_id})
        t.check("2d: Cue reaches Stop",
                wait_for_signal(sub, timeout=3) is not None)


def test_3_slideshow_playlist(t):
    """GroupCue playlist mode with image cues = slideshow."""
    print("\n=== Test 3: Slideshow via Playlist GroupCue ===")
    clear_cues()

    # Add 3 image cues with short durations, each gated on
    # item_added so we don't race the layout.
    for name, dur in [
        ("slide_1.png", 2000),
        ("slide_2.png", 2000),
        ("slide_3.png", 2000),
    ]:
        path = os.path.join(MEDIA_DIR, name)
        _add_image(path, duration=dur)

    cues = call("cue.list")
    t.check("3a: Three image cues exist", len(cues) == 3)

    if len(cues) < 3:
        print("  SKIP: Not enough cues")
        return

    # Select cues and group them (Group selected waits for the
    # model reset implied by the new GroupCue's item_added).
    cue_ids = [c["id"] for c in cues]
    call("layout.select_cues", {"indices": [0, 1, 2]})
    with signal_sub("cue_model.item_added") as sub:
        call("layout.context_action", {
            "action": "Group selected",
            "cue_ids": cue_ids,
        })
        wait_for_signal(sub, timeout=5)

    # Find the group cue
    all_cues = call("cue.list")
    group_cues = [
        c for c in all_cues if c["_type_"] == "GroupCue"
    ]
    t.check("3b: GroupCue created", len(group_cues) == 1)

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

    # Play the group — wait for the overall group's end
    # signal, which fires when the playlist completes all
    # children and the group itself reaches EOS.
    start_time = time.time()
    with cue_signal(group_id, "started") as start_sub, \
            cue_signal(group_id, "end") as end_sub:
        call("cue.start", {"id": group_id})
        t.check("3c: Group reaches Running",
                wait_for_signal(start_sub, timeout=5) is not None)
        t.check("3d: Group finishes after all slides",
                wait_for_signal(end_sub, timeout=15) is not None)

    elapsed = time.time() - start_time
    # Should take roughly 6 seconds (3 slides x 2s each)
    t.check("3e: Total time reasonable (4-12s)",
            4 < elapsed < 12)


def test_4_parallel_audio_and_image(t):
    """GroupCue parallel mode: audio + image simultaneously."""
    print("\n=== Test 4: Parallel Audio + Image ===")
    clear_cues()

    audio_path = os.path.join(MEDIA_DIR, "tone.wav")
    image_path = os.path.join(MEDIA_DIR, "test_image.png")

    with signal_sub("cue_model.item_added") as sub:
        call("cue.add_from_uri", {"uri": audio_path})
        call("cue.add_image_from_uri", {
            "uri": image_path, "duration": 3000,
        })
        wait_for_signal(sub, timeout=5)
        wait_for_signal(sub, timeout=5)

    cues = call("cue.list")
    t.check("4a: Two cues exist", len(cues) == 2)

    if len(cues) < 2:
        print("  SKIP: Not enough cues")
        return

    audio_id = cues[0]["id"]
    image_id = cues[1]["id"]

    # Group them (parallel is default mode=0)
    cue_ids = [audio_id, image_id]
    call("layout.select_cues", {"indices": [0, 1]})
    with signal_sub("cue_model.item_added") as sub:
        call("layout.context_action", {
            "action": "Group selected",
            "cue_ids": cue_ids,
        })
        wait_for_signal(sub, timeout=5)

    all_cues = call("cue.list")
    group_cues = [
        c for c in all_cues if c["_type_"] == "GroupCue"
    ]
    t.check("4b: GroupCue created", len(group_cues) == 1)

    if not group_cues:
        print("  SKIP: No group cue")
        return

    group_id = group_cues[0]["id"]

    # Start the group and wait for both children to be Running
    with cue_signal(audio_id, "started") as a_sub, \
            cue_signal(image_id, "started") as i_sub:
        call("cue.start", {"id": group_id})
        a_started = wait_for_signal(a_sub, timeout=5)
        i_started = wait_for_signal(i_sub, timeout=5)
    t.check("4c: Audio cue Running", a_started is not None)
    t.check("4d: Image cue Running", i_started is not None)

    # Image auto-stops after 3s; wait on its 'end' signal
    # (image timer EOS path — see test 1's note).
    with cue_signal(image_id, "end") as sub:
        t.check("4e: Image auto-stops",
                wait_for_signal(sub, timeout=8) is not None)

    # Audio should still be going
    t.check("4f: Audio still Running after image stops",
            cue_state(audio_id) == "Running")

    # Stop the group
    with cue_signal(audio_id, "stopped") as sub:
        call("cue.stop", {"id": group_id})
        t.check("4g: Audio cue stopped",
                wait_for_signal(sub, timeout=3) is not None)


def test_5_stop_and_replay(t):
    """Stop an image cue mid-display, then play it again.

    Regression test: uridecodebin removes dynamic pads on READY
    transition.  If _linked is not reset in stop(), the second
    play fails with 'not-linked'.
    """
    print("\n=== Test 5: Image Stop and Replay ===")
    clear_cues()

    image_path = os.path.join(MEDIA_DIR, "test_image.png")
    cue = _add_image(image_path, duration=10000)
    t.check("5a: Image cue added", cue is not None)
    cue_id = cue["id"]

    # First play, let it display briefly, then stop
    with cue_signal(cue_id, "started") as sub:
        call("cue.start", {"id": cue_id})
        t.check("5b: First play reaches Running",
                wait_for_signal(sub, timeout=5) is not None)

    time.sleep(1)

    with cue_signal(cue_id, "stopped") as sub:
        call("cue.stop", {"id": cue_id})
        t.check("5c: First play reaches Stop",
                wait_for_signal(sub, timeout=3) is not None)

    # Second play — must not error
    with cue_signal(cue_id, "started") as sub:
        call("cue.start", {"id": cue_id})
        t.check("5d: Second play reaches Running",
                wait_for_signal(sub, timeout=5) is not None)

    time.sleep(0.5)
    state = call("cue.state", {"id": cue_id})
    t.check("5e: current_time advancing on replay",
            state["current_time"] > 0)

    with cue_signal(cue_id, "stopped") as sub:
        call("cue.stop", {"id": cue_id})
        t.check("5f: Second play reaches Stop",
                wait_for_signal(sub, timeout=3) is not None)


def test_6_interrupt_mid_playback(t):
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
    cue = _add_image(image_path, duration=5000)
    t.check("6a: Image cue added", cue is not None)
    cue_id = cue["id"]

    with cue_signal(cue_id, "started") as sub:
        call("cue.start", {"id": cue_id})
        t.check("6b: Cue reaches Running",
                wait_for_signal(sub, timeout=5) is not None)

    time.sleep(2.5)

    # Interrupt (same as pressing ESC in the UI)
    with cue_signal(cue_id, "interrupted") as sub:
        call("cue.interrupt", {"id": cue_id})
        t.check("6c: Cue reaches Stop after interrupt",
                wait_for_signal(sub, timeout=5) is not None)

    # Wait for the EOS timer to fire (it was set for 5s total,
    # ~2.5s remain).  The cue must stay in Stop, not get stuck.
    time.sleep(4)
    t.check("6d: Cue still in Stop after EOS timer",
            cue_state(cue_id) == "Stop")

    # Verify the cue can be replayed (not stuck)
    with cue_signal(cue_id, "started") as sub:
        call("cue.start", {"id": cue_id})
        t.check("6e: Cue replays after interrupt",
                wait_for_signal(sub, timeout=5) is not None)

    with cue_signal(cue_id, "stopped") as sub:
        call("cue.stop", {"id": cue_id})
        t.check("6f: Cue stops after replay",
                wait_for_signal(sub, timeout=3) is not None)


def test_7_indefinite_duration(t):
    """Image cue with duration=-1 displays until manually stopped."""
    print("\n=== Test 7: Indefinite Duration Image Cue ===")
    clear_cues()

    image_path = os.path.join(MEDIA_DIR, "test_image.png")
    cue = _add_image(image_path, duration=-1)
    t.check("7a: Image cue added", cue is not None)
    cue_id = cue["id"]

    with cue_signal(cue_id, "started") as sub:
        call("cue.start", {"id": cue_id})
        t.check("7b: Cue reaches Running",
                wait_for_signal(sub, timeout=5) is not None)

    # Wait longer than a normal 5s image would display —
    # cue must still be Running (no EOS timer).
    time.sleep(7)
    t.check("7c: Still Running after 7s (no auto-stop)",
            cue_state(cue_id) == "Running")

    # Manual stop
    with cue_signal(cue_id, "stopped") as sub:
        call("cue.stop", {"id": cue_id})
        t.check("7d: Cue reaches Stop after manual stop",
                wait_for_signal(sub, timeout=3) is not None)


def test_8_pause_resume(t):
    """Pause an image cue, verify current_time freezes, then resume.

    Phase 2 L1: the EOS timer is driven by the elapsed-time
    property on GstMedia, not a wall-clock deadline, so pausing
    must suspend the countdown.  Otherwise a long pause would
    burn through the image's duration while the cue is parked.
    """
    print("\n=== Test 8: Image Pause / Resume ===")
    clear_cues()

    image_path = os.path.join(MEDIA_DIR, "test_image.png")
    # 8s duration: enough runway to pause, wait, and resume
    # without hitting auto-stop.
    cue = _add_image(image_path, duration=8000)
    t.check("8a: Image cue added", cue is not None)
    cue_id = cue["id"]

    with cue_signal(cue_id, "started") as sub:
        call("cue.start", {"id": cue_id})
        t.check("8b: Cue reaches Running",
                wait_for_signal(sub, timeout=5) is not None)

    # Let it run ~1s so current_time is safely above 0
    time.sleep(1)
    t_before = call("cue.state", {"id": cue_id})["current_time"]
    t.check("8c: current_time advanced before pause "
            f"(got {t_before} ms)",
            t_before > 500)

    with cue_signal(cue_id, "paused") as sub:
        call("cue.pause", {"id": cue_id})
        t.check("8d: cue.paused signal fired",
                wait_for_signal(sub, timeout=3) is not None)

    # Park in Pause for 2s and confirm current_time did NOT drift
    # by anywhere near that amount (tolerance: 400ms for pipeline
    # settling — tight enough to catch a fully running clock).
    time.sleep(2)
    t_pause = call("cue.state", {"id": cue_id})["current_time"]
    t.check("8e: current_time frozen during pause "
            f"(before={t_before}, during={t_pause})",
            abs(t_pause - t_before) < 400)

    # Resume
    with cue_signal(cue_id, "started") as sub:
        call("cue.resume", {"id": cue_id})
        t.check("8f: cue.started fired on resume",
                wait_for_signal(sub, timeout=3) is not None)

    # Let it advance again
    time.sleep(0.7)
    t_after = call("cue.state", {"id": cue_id})["current_time"]
    t.check("8g: current_time advances after resume "
            f"(got {t_after} ms > {t_pause} ms)",
            t_after > t_pause + 300)

    # Clean stop
    with cue_signal(cue_id, "stopped") as sub:
        call("cue.stop", {"id": cue_id})
        wait_for_signal(sub, timeout=3)


def test_9_missing_file(t):
    """Add an image cue with a non-existent path.

    Phase 2 L2: GStreamer will emit an error message from the
    pipeline once start() flushes to PAUSED.  The cue must
    surface that error (via the 'error' signal) and end up in
    Stop — not wedge in Running forever.
    """
    print("\n=== Test 9: Missing Image File ===")
    clear_cues()

    missing_path = "/tmp/lisp_test_image/__does_not_exist__.png"
    # Make sure it really doesn't exist
    if os.path.exists(missing_path):
        os.unlink(missing_path)

    cue = _add_image(missing_path, duration=3000)
    t.check("9a: Cue still added for missing file",
            cue is not None)
    cue_id = cue["id"]

    # Subscribe BEFORE start — the error message may arrive
    # essentially synchronously with state PAUSED.
    with cue_signal(cue_id, "error") as err_sub, \
            cue_signal(cue_id, "stopped") as stop_sub:
        call("cue.start", {"id": cue_id})

        # Either the error signal fires OR the cue transitions
        # straight to Stop — both are acceptable because the
        # GStreamer error message paths through MediaCue's
        # _on_error → _ended.  We assert at least one fires
        # within a few seconds so the cue isn't wedged.
        err_event = wait_for_signal(err_sub, timeout=5)
        stop_event = (
            wait_for_signal(stop_sub, timeout=0.1)
            if err_event is None
            else None
        )
        got_signal = err_event is not None or stop_event is not None

    t.check("9b: Cue surfaces error or reaches Stop",
            got_signal)

    # Whatever path it took, it must NOT be stuck Running
    final_state = cue_state(cue_id)
    t.check("9c: Cue not stuck Running "
            f"(state={final_state})",
            final_state != "Running")


# -- Main -------------------------------------------------------------

def run_tests(t):
    create_test_media()

    test_1_image_cue_lifecycle(t)
    stop_all()
    test_2_image_cue_manual_stop(t)
    stop_all()
    test_3_slideshow_playlist(t)
    stop_all()
    test_4_parallel_audio_and_image(t)
    stop_all()
    test_5_stop_and_replay(t)
    stop_all()
    test_6_interrupt_mid_playback(t)
    stop_all()
    test_7_indefinite_duration(t)
    stop_all()
    test_8_pause_resume(t)
    stop_all()
    test_9_missing_file(t)
    stop_all()


if __name__ == "__main__":
    run_suite("Image Cue E2E Tests", run_tests)
