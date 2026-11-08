#!/usr/bin/env python3
"""E2E tests: replacing the session must stop the cues still running.

Regression for running cues being orphaned on session teardown:
``Session.finalize()`` -> ``CueModel.reset()`` cleared the model without
interrupting its cues (unlike ``CueModel.pop()``), so a cue running when
a new session was created or loaded kept playing with no way to stop it
from the UI. For video/image cues the orphan also kept its projection
sink active, so ``VideoExclusiveManager`` blocked every video/image cue
in the new session until LiSP was restarted.

``reset()`` now waits (bounded) for the halted cues to stop, so the
loaded session's video/image cue can be GOne the moment ``session.load``
returns -- these tests GO it immediately, with no settling sleep.

Run:
    poetry run python tests/e2e/test_session_teardown_e2e.py

Options:
    --no-launch    Don't start/stop LiSP (attach to existing; skips
                   the quit test, which needs to own the process)
    --host HOST    Harness host (default: 127.0.0.1)
    --port PORT    Harness port (default: 8070)
"""

import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time

import helpers
from helpers import (
    AUDIO_DIR,
    call,
    clear_cues,
    cue_state,
    run_suite,
    subscribe_cue,
    unsubscribe,
    wait_current_time,
    wait_for_signal,
    wait_state,
)

AUDIO = os.path.join(AUDIO_DIR, "tone_A.wav")

# Fresh per run (see __main__), so stale or half-written media from an
# earlier run can never be picked up.
MEDIA_DIR = None

# Long enough that an orphaned image is still "playing" when the
# next session tries to start its own image cue, short enough to
# drain (see drain_orphans) so one failing test can't poison the next.
IMAGE_HOLD_MS = 8000

# How long LiSP may take to exit on SIGTERM with cues playing. reset()
# waits at most CueModel.HALT_TIMEOUT (2s); the rest is plugin and
# GStreamer teardown.
QUIT_TIMEOUT = 15


def media(name):
    return os.path.join(MEDIA_DIR, name)


# -- Media / helpers ---------------------------------------------------

def _gst(cmd, filename):
    result = subprocess.run(
        ["gst-launch-1.0", "-e", *cmd, "filesink", f"location={filename}"],
        capture_output=True,
        timeout=60,
    )
    if result.returncode != 0:
        print(
            f"ERROR: cannot generate {filename}: "
            f"{result.stderr.decode()}",
            file=sys.stderr,
        )
        sys.exit(2)


def make_test_image(filename, pattern):
    _gst([
        "videotestsrc", f"pattern={pattern}", "num-buffers=1", "!",
        "video/x-raw,width=320,height=240", "!",
        "pngenc", "!",
    ], filename)


def make_test_video(filename, duration_s=15):
    """WebM with video and audio, as test_video_e2e generates."""
    audio_buffers = int(duration_s * 44100 / 1024) + 1
    _gst([
        "videotestsrc", f"num-buffers={duration_s * 30}", "!",
        "video/x-raw,width=320,height=240,framerate=30/1", "!",
        "videoconvert", "!", "vp8enc", "deadline=1", "!",
        "queue", "!", "mux.",
        "audiotestsrc", f"num-buffers={audio_buffers}", "freq=440", "!",
        "audioconvert", "!", "vorbisenc", "!", "queue", "!", "mux.",
        "webmmux", "name=mux", "!",
    ], filename)


def create_test_media():
    make_test_image(media("image_a.png"), "smpte")
    make_test_image(media("image_b.png"), "ball")
    make_test_video(media("video.webm"))


def new_session():
    call("session.new", {"layout_type": "ListLayout"})
    deadline = time.time() + 10
    while time.time() < deadline:
        if call("session.info").get("has_session"):
            return
        time.sleep(0.2)
    raise RuntimeError("session.new did not produce a session")


def _add(method, params):
    """Add one cue via ``method``; return its id."""
    before = {c["id"] for c in call("cue.list")}
    call(method, params)
    deadline = time.time() + 10
    while time.time() < deadline:
        new = {c["id"] for c in call("cue.list")} - before
        if new:
            return new.pop()
        time.sleep(0.2)
    raise RuntimeError(f"{method} {params} added no cue")


def add_image(path):
    return _add(
        "cue.add_image_from_uri", {"uri": path, "duration": IMAGE_HOLD_MS}
    )


def add_audio(path):
    return _add("cue.add_from_uri", {"uri": path})


def add_video(path):
    return _add("cue.add_video_from_uri", {"uri": path})


def go(cue_id):
    """GO a cue the way the layout does.

    ``cue.execute``, not ``cue.start``: the video-exclusivity block
    lives in ``Cue.execute`` (the GO path); ``Cue.start`` bypasses it.
    """
    call("cue.execute", {"id": cue_id, "action": "Start"})


def drain_orphans(probe_id):
    """Wait until an orphan (from unfixed teardown) frees the
    projection, so the next test starts clean.

    Polls the real exclusivity check: GO ``probe_id`` (a video/image
    cue of the current session) until it is no longer blocked, then
    stop it. Returns at once when nothing is orphaned.
    """
    deadline = time.time() + IMAGE_HOLD_MS / 1000 + 3
    while time.time() < deadline:
        go(probe_id)
        if wait_state(probe_id, "Running", timeout=0.5):
            call("cue.stop", {"id": probe_id})
            wait_state(probe_id, "Stop")
            return
    print("    WARNING: projection still blocked after drain window")


def stopped_by_teardown(cue_id, replace_session, timeout=3.0):
    """Run ``replace_session`` and report whether the (old) cue
    emitted ``interrupted`` or ``stopped`` because of it."""
    subs = [
        subscribe_cue(cue_id, "interrupted"),
        subscribe_cue(cue_id, "stopped"),
    ]
    try:
        replace_session()
        deadline = time.time() + timeout
        while time.time() < deadline:
            for sub in subs:
                if wait_for_signal(sub, timeout=0.1) is not None:
                    return True
        return False
    finally:
        for sub in subs:
            unsubscribe(sub)


def check_new_image_starts(t, label, new_image):
    """GO the new session's image straight away; it must not be
    blocked by the old session's (halted) image."""
    go(new_image)
    running = wait_state(new_image, "Running", timeout=3.0)
    t.check(label, running)
    if running:
        call("cue.stop", {"id": new_image})
        wait_state(new_image, "Stop")
    else:
        print(f"    state after start: {cue_state(new_image)}")
        drain_orphans(new_image)


# -- Tests -------------------------------------------------------------

def test_1_new_session_stops_running_audio(t):
    """A playing audio cue is stopped when a new session is created."""
    print("\n=== Test 1: session.new stops a running audio cue ===")

    new_session()
    cue_id = add_audio(AUDIO)
    call("cue.start", {"id": cue_id})
    t.check("1: audio cue running", wait_state(cue_id, "Running"))
    t.check("1: audio cue advancing", wait_current_time(cue_id, 200))

    t.check(
        "1: old audio cue interrupted/stopped by session.new",
        stopped_by_teardown(cue_id, new_session),
    )


def test_2_load_session_releases_projection(t):
    """An image left up when another session is loaded must not
    block the loaded session's image cue (the show-day case:
    switching from one show's session file to the next)."""
    print("\n=== Test 2: session.load releases a running image ===")

    # Build and save the session we will switch *to*.
    new_session()
    add_image(media("image_b.png"))
    call("session.save", {"path": media("with_image.lsp")})

    # Fresh session with a different image, left running.
    new_session()
    old_image = add_image(media("image_a.png"))
    call("cue.start", {"id": old_image})
    t.check("2: first image running", wait_state(old_image, "Running"))

    # session.load blocks until the load (teardown included) is done.
    t.check(
        "2: old image interrupted/stopped by session.load",
        stopped_by_teardown(
            old_image,
            lambda: call("session.load", {"path": media("with_image.lsp")}),
        ),
    )

    loaded = call("cue.list")
    t.check("2: loaded session has its image cue", len(loaded) == 1)
    if len(loaded) != 1:
        return
    check_new_image_starts(
        t, "2: loaded image starts (not blocked by an orphan)",
        loaded[0]["id"],
    )


def test_3_new_session_releases_projection(t):
    """Same as test 2 but via session.new (File > New)."""
    print("\n=== Test 3: session.new releases a running image ===")

    new_session()
    old_image = add_image(media("image_a.png"))
    call("cue.start", {"id": old_image})
    t.check("3: first image running", wait_state(old_image, "Running"))

    t.check(
        "3: old image interrupted/stopped by session.new",
        stopped_by_teardown(old_image, new_session),
    )

    check_new_image_starts(
        t, "3: new session's image starts (not blocked by an orphan)",
        add_image(media("image_b.png")),
    )


def test_4_fading_image_does_not_wedge_projection(t):
    """The field failure: an image still fading in when another
    session is loaded. A bare orphan is garbage-collected (its media
    finalizer happens to release the projection), but the running
    fade thread holds the cue alive, so without an explicit stop on
    teardown the orphan keeps the projection and blocks the loaded
    session's video/image cues until LiSP restarts."""
    print("\n=== Test 4: image mid-fade-in + session.load ===")

    new_session()
    add_image(media("image_b.png"))
    call("session.save", {"path": media("with_image.lsp")})

    new_session()
    fading = add_image(media("image_a.png"))
    # Seconds — Cue.fadein_duration is in seconds, not ms.
    call("cue.set_property", {
        "id": fading, "property": "fadein_duration", "value": 30,
    })
    call("cue.execute", {"id": fading, "action": "FadeInStart"})
    t.check("4: fading image running", wait_state(fading, "Running"))
    # Well inside the 30s fade.
    t.check("4: fading image advancing", wait_current_time(fading, 500))

    t.check(
        "4: fading image interrupted/stopped by session.load",
        stopped_by_teardown(
            fading,
            lambda: call("session.load", {"path": media("with_image.lsp")}),
        ),
    )

    loaded = call("cue.list")
    t.check("4: loaded session has its image cue", len(loaded) == 1)
    if len(loaded) != 1:
        return
    check_new_image_starts(
        t, "4: loaded image starts (not blocked by a fading orphan)",
        loaded[0]["id"],
    )


def test_5_quit_while_playing(t, log_file):
    """Quitting (SIGTERM -> qt_app.quit -> finalize_plugins ->
    Application.finalize -> CueModel.reset) with audio, video and a
    fading cue playing: the halts now run during app teardown, after
    the plugins are finalized. LiSP must still exit cleanly, promptly
    and without a traceback."""
    print("\n=== Test 5: quit with audio, video and a fade playing ===")

    new_session()
    audio = add_audio(AUDIO)
    video = add_video(media("video.webm"))
    fading = add_audio(AUDIO)
    call("cue.set_property", {
        "id": fading, "property": "fadein_duration", "value": 30,
    })

    call("cue.start", {"id": audio})
    go(video)
    call("cue.execute", {"id": fading, "action": "FadeInStart"})
    for name, cue_id in (("audio", audio), ("video", video),
                         ("fading", fading)):
        t.check(
            f"5: {name} cue advancing", wait_current_time(cue_id, 300)
        )

    with open(log_file) as f:
        f.seek(0, os.SEEK_END)
        log_start = f.tell()

    proc = helpers._lisp_proc
    began = time.monotonic()
    proc.send_signal(signal.SIGTERM)
    try:
        code = proc.wait(timeout=QUIT_TIMEOUT)
    except subprocess.TimeoutExpired:
        proc.kill()
        code = proc.wait()
        t.check(f"5: LiSP exits within {QUIT_TIMEOUT}s of SIGTERM", False)
    else:
        print(f"    exited in {time.monotonic() - began:.1f}s")
        t.check(f"5: LiSP exits within {QUIT_TIMEOUT}s of SIGTERM", True)
    helpers._lisp_proc = None

    with open(log_file) as f:
        f.seek(log_start)
        log = f.read()
    t.check(f"5: exit code 0 (got {code})", code == 0)
    for needle in ("Traceback", "Failed to halt cue", "still active"):
        found = needle in log
        t.check(f"5: no {needle!r} in the shutdown log", not found)
        if found:
            print("    --- shutdown log ---\n" + log[-3000:])
            break

    # run_suite's teardown talks to LiSP, so bring it back.
    helpers.start_lisp(log_file=log_file)


def run_tests(t, log_file, owns_lisp):
    create_test_media()
    test_1_new_session_stops_running_audio(t)
    test_2_load_session_releases_projection(t)
    test_3_new_session_releases_projection(t)
    # On unfixed code its orphan outlives the drain window (held by a
    # 30s fade), so it would poison any later projection test.
    test_4_fading_image_does_not_wedge_projection(t)
    if owns_lisp:
        test_5_quit_while_playing(t, log_file)
    else:
        print("\n=== Test 5: SKIPPED (--no-launch: LiSP not ours) ===")
    clear_cues()


if __name__ == "__main__":
    MEDIA_DIR = tempfile.mkdtemp(prefix="lisp_teardown_")
    log_file = media("lisp.log")
    owns_lisp = "--no-launch" not in sys.argv
    try:
        run_suite(
            "E2E tests for stopping running cues on session teardown",
            lambda t: run_tests(t, log_file, owns_lisp),
            log_file=log_file if owns_lisp else None,
        )
    finally:
        shutil.rmtree(MEDIA_DIR, ignore_errors=True)
