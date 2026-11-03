#!/usr/bin/env python3
"""E2E tests: replacing the session must stop the cues still running.

Regression for running cues being orphaned on session teardown:
``Session.finalize()`` -> ``CueModel.reset()`` cleared the model without
interrupting its cues (unlike ``CueModel.pop()``), so a cue running when
a new session was created or loaded kept playing with no way to stop it
from the UI. For video/image cues the orphan also kept its projection
sink active, so ``VideoExclusiveManager`` blocked every video/image cue
in the new session until LiSP was restarted.

Run:
    poetry run python tests/e2e/test_session_teardown_e2e.py

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

MEDIA_DIR = "/tmp/lisp_test_session_teardown"
AUDIO = os.path.join(AUDIO_DIR, "tone_A.wav")
IMAGE_A = os.path.join(MEDIA_DIR, "image_a.png")
IMAGE_B = os.path.join(MEDIA_DIR, "image_b.png")
SESSION_WITH_IMAGE = os.path.join(MEDIA_DIR, "with_image.lsp")

# Long enough that an orphaned image is still "playing" when the
# next session tries to start its own image cue, short enough to
# drain (see drain_orphans) so one failing test can't poison the next.
IMAGE_HOLD_MS = 8000


# -- Media / helpers ---------------------------------------------------

def make_test_image(filename, pattern):
    cmd = [
        "gst-launch-1.0", "-e",
        "videotestsrc", f"pattern={pattern}", "num-buffers=1", "!",
        "video/x-raw,width=320,height=240", "!",
        "pngenc", "!",
        "filesink", f"location={filename}",
    ]
    result = subprocess.run(cmd, capture_output=True, timeout=30)
    if result.returncode != 0:
        print(
            f"ERROR: cannot generate {filename}: "
            f"{result.stderr.decode()}",
            file=sys.stderr,
        )
        sys.exit(2)


def create_test_media():
    os.makedirs(MEDIA_DIR, exist_ok=True)
    for path, pattern in ((IMAGE_A, "smpte"), (IMAGE_B, "ball")):
        if not os.path.exists(path):
            make_test_image(path, pattern)


def new_session():
    call("session.new", {"layout_type": "ListLayout"})
    deadline = time.time() + 10
    while time.time() < deadline:
        if call("session.info").get("has_session"):
            return
        time.sleep(0.2)
    raise RuntimeError("session.new did not produce a session")


def add_image(path):
    """Add one image cue; return its id."""
    before = {c["id"] for c in call("cue.list")}
    call("cue.add_image_from_uri", {
        "uri": path, "duration": IMAGE_HOLD_MS,
    })
    deadline = time.time() + 10
    while time.time() < deadline:
        new = {c["id"] for c in call("cue.list")} - before
        if new:
            return new.pop()
        time.sleep(0.2)
    raise RuntimeError(f"image cue for {path} was not added")


def add_audio(path):
    before = {c["id"] for c in call("cue.list")}
    call("cue.add_from_uri", {"uri": path})
    deadline = time.time() + 10
    while time.time() < deadline:
        new = {c["id"] for c in call("cue.list")} - before
        if new:
            return new.pop()
        time.sleep(0.2)
    raise RuntimeError(f"audio cue for {path} was not added")


def drain_orphans():
    """Outlast any image orphaned by an unfixed teardown so the next
    test starts with the projection free."""
    time.sleep(IMAGE_HOLD_MS / 1000 + 1)


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
    add_image(IMAGE_B)
    call("session.save", {"path": SESSION_WITH_IMAGE})

    # Fresh session with a different image, left running.
    new_session()
    old_image = add_image(IMAGE_A)
    call("cue.start", {"id": old_image})
    t.check("2: first image running", wait_state(old_image, "Running"))

    def load():
        call("session.load", {"path": SESSION_WITH_IMAGE})
        time.sleep(1.0)

    t.check(
        "2: old image interrupted/stopped by session.load",
        stopped_by_teardown(old_image, load),
    )

    loaded = call("cue.list")
    t.check("2: loaded session has its image cue", len(loaded) == 1)
    if len(loaded) != 1:
        return
    new_image = loaded[0]["id"]

    # execute(), not cue.start: the video-exclusivity block lives in
    # Cue.execute (the GO path); Cue.start bypasses it.
    call("cue.execute", {"id": new_image, "action": "Start"})
    running = wait_state(new_image, "Running", timeout=3.0)
    t.check(
        "2: loaded image starts (not blocked by an orphan)", running,
    )
    if not running:
        print(f"    state after start: {cue_state(new_image)}")
    call("cue.stop", {"id": new_image})
    drain_orphans()


def test_3_new_session_releases_projection(t):
    """Same as test 2 but via session.new (File > New)."""
    print("\n=== Test 3: session.new releases a running image ===")

    new_session()
    old_image = add_image(IMAGE_A)
    call("cue.start", {"id": old_image})
    t.check("3: first image running", wait_state(old_image, "Running"))

    t.check(
        "3: old image interrupted/stopped by session.new",
        stopped_by_teardown(old_image, new_session),
    )

    new_image = add_image(IMAGE_B)
    # execute(), not cue.start: the video-exclusivity block lives in
    # Cue.execute (the GO path); Cue.start bypasses it.
    call("cue.execute", {"id": new_image, "action": "Start"})
    running = wait_state(new_image, "Running", timeout=3.0)
    t.check(
        "3: new session's image starts (not blocked by an orphan)",
        running,
    )
    if not running:
        print(f"    state after start: {cue_state(new_image)}")
    call("cue.stop", {"id": new_image})
    drain_orphans()


def test_4_fading_image_does_not_wedge_projection(t):
    """The field failure: an image still fading in when another
    session is loaded. A bare orphan is garbage-collected (its media
    finalizer happens to release the projection), but the running
    fade thread holds the cue alive, so without an explicit stop on
    teardown the orphan keeps the projection and blocks the loaded
    session's video/image cues until LiSP restarts."""
    print("\n=== Test 4: image mid-fade-in + session.load ===")

    new_session()
    add_image(IMAGE_B)
    call("session.save", {"path": SESSION_WITH_IMAGE})

    new_session()
    fading = add_image(IMAGE_A)
    # Seconds — Cue.fadein_duration is in seconds, not ms.
    call("cue.set_property", {
        "id": fading, "property": "fadein_duration", "value": 30,
    })
    call("cue.execute", {"id": fading, "action": "FadeInStart"})
    t.check("4: fading image running", wait_state(fading, "Running"))
    time.sleep(1.0)  # well inside the 30s fade

    def load():
        call("session.load", {"path": SESSION_WITH_IMAGE})
        time.sleep(1.0)

    t.check(
        "4: fading image interrupted/stopped by session.load",
        stopped_by_teardown(fading, load),
    )

    loaded = call("cue.list")
    t.check("4: loaded session has its image cue", len(loaded) == 1)
    if len(loaded) != 1:
        return
    new_image = loaded[0]["id"]

    # execute(), not cue.start: the video-exclusivity block lives in
    # Cue.execute (the GO path); Cue.start bypasses it.
    call("cue.execute", {"id": new_image, "action": "Start"})
    running = wait_state(new_image, "Running", timeout=3.0)
    t.check(
        "4: loaded image starts (not blocked by a fading orphan)",
        running,
    )
    if not running:
        print(f"    state after start: {cue_state(new_image)}")
    call("cue.stop", {"id": new_image})


def run_tests(t):
    create_test_media()
    test_1_new_session_stops_running_audio(t)
    test_2_load_session_releases_projection(t)
    test_3_new_session_releases_projection(t)
    # Last: on unfixed code its orphan outlives the drain window
    # (held by a 30s fade), so it would poison any later test.
    test_4_fading_image_does_not_wedge_projection(t)
    clear_cues()


if __name__ == "__main__":
    run_suite(
        "E2E tests for stopping running cues on session teardown",
        run_tests,
    )
