#!/usr/bin/env python3
"""E2E tests for MediaCue playback lifecycle.

Tests the full playback state machine: Start, Pause, Resume, Stop,
FadeOutStop, FadeInStart, Interrupt, Seek, natural end, and
stop-then-restart.

Run:
    poetry run python tests/e2e/test_media_playback_e2e.py

Options:
    --no-launch    Don't start/stop LiSP (attach to existing)
    --host HOST    Harness host (default: 127.0.0.1)
    --port PORT    Harness port (default: 8070)
"""

import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from tests.e2e.helpers import (  # noqa: E402
    run_suite,
    call,
    cue_state,
    wait_state,
    stop_all,
    setup_with_tones,
)


def run_tests(t):
    print("\nSetting up test cues...")
    ids = setup_with_tones()
    A = ids["tone_A"]
    B = ids["tone_B"]
    C = ids["tone_C"]
    D = ids["tone_D"]

    # ── Test 1: Start → Running ───────────────────────────────
    print("\n═══ Test 1: Start → Running ═══")
    call("cue.execute", {"id": A, "action": "Start"})
    t.check(
        "1: Start transitions to Running",
        wait_state(A, "Running", timeout=5),
    )
    stop_all()

    # ── Test 2: Pause → Pause ─────────────────────────────────
    print("\n═══ Test 2: Pause → Pause ═══")
    call("cue.execute", {"id": A, "action": "Start"})
    t.check(
        "2a: Running before pause",
        wait_state(A, "Running", timeout=5),
    )
    call("cue.execute", {"id": A, "action": "Pause"})
    t.check(
        "2b: Pause transitions to Pause",
        wait_state(A, "Pause", timeout=5),
    )
    stop_all()

    # ── Test 3: Resume from pause → Running ───────────────────
    print("\n═══ Test 3: Resume from Pause → Running ═══")
    call("cue.execute", {"id": A, "action": "Start"})
    wait_state(A, "Running", timeout=5)
    call("cue.execute", {"id": A, "action": "Pause"})
    t.check(
        "3a: Paused before resume",
        wait_state(A, "Pause", timeout=5),
    )
    call("cue.execute", {"id": A, "action": "Resume"})
    t.check(
        "3b: Resume transitions to Running",
        wait_state(A, "Running", timeout=5),
    )
    stop_all()

    # ── Test 4: Stop → Stop ───────────────────────────────────
    print("\n═══ Test 4: Stop → Stop ═══")
    call("cue.execute", {"id": A, "action": "Start"})
    wait_state(A, "Running", timeout=5)
    call("cue.execute", {"id": A, "action": "Stop"})
    t.check(
        "4: Stop transitions to Stop",
        wait_state(A, "Stop", timeout=5),
    )

    # ── Test 5: FadeOutStop ───────────────────────────────────
    print("\n═══ Test 5: FadeOutStop ═══")
    call("cue.set_property", {
        "id": B, "property": "fadeout_duration", "value": 1.0,
    })
    call("cue.execute", {"id": B, "action": "Start"})
    t.check(
        "5a: Running before FadeOutStop",
        wait_state(B, "Running", timeout=5),
    )
    call("cue.execute", {"id": B, "action": "FadeOutStop"})
    # Cue should still be Running briefly while fading
    time.sleep(0.3)
    t.check(
        "5b: Still Running during fade",
        cue_state(B) == "Running",
    )
    # After fade completes (1s + margin), should be stopped
    t.check(
        "5c: Stopped after fade completes",
        wait_state(B, "Stop", timeout=4),
    )
    # Restore default fade duration
    call("cue.set_property", {
        "id": B, "property": "fadeout_duration", "value": 0.0,
    })
    stop_all()

    # ── Test 6: FadeInStart ───────────────────────────────────
    print("\n═══ Test 6: FadeInStart ═══")
    call("cue.set_property", {
        "id": C, "property": "fadein_duration", "value": 1.0,
    })
    call("cue.execute", {"id": C, "action": "FadeInStart"})
    t.check(
        "6: FadeInStart reaches Running",
        wait_state(C, "Running", timeout=5),
    )
    call("cue.set_property", {
        "id": C, "property": "fadein_duration", "value": 0.0,
    })
    stop_all()

    # ── Test 7: Interrupt → Stop immediately ──────────────────
    print("\n═══ Test 7: Interrupt → Stop ═══")
    call("cue.execute", {"id": D, "action": "Start"})
    t.check(
        "7a: Running before interrupt",
        wait_state(D, "Running", timeout=5),
    )
    call("cue.execute", {"id": D, "action": "Interrupt"})
    t.check(
        "7b: Interrupt transitions to Stop",
        wait_state(D, "Stop", timeout=3),
    )
    stop_all()

    # ── Test 8: Seek while playing ────────────────────────────
    print("\n═══ Test 8: Seek while playing ═══")
    call("cue.execute", {"id": A, "action": "Start"})
    t.check(
        "8a: Running before seek",
        wait_state(A, "Running", timeout=5),
    )
    call("cue.seek", {"id": A, "position": 5000})
    time.sleep(0.5)
    state = call("cue.state", {"id": A})
    current = state.get("current_time", 0)
    t.check(
        "8b: current_time near seek target (±1500ms)",
        abs(current - 5000) < 1500,
    )
    stop_all()

    # ── Test 9: Natural end → Stop ────────────────────────────
    print("\n═══ Test 9: Natural end → Stop ═══")
    call("cue.execute", {"id": B, "action": "Start"})
    wait_state(B, "Running", timeout=5)
    # Seek near end of 8s tone
    call("cue.seek", {"id": B, "position": 7500})
    t.check(
        "9: Cue stops naturally at end",
        wait_state(B, "Stop", timeout=5),
    )
    stop_all()

    # ── Test 10: Stop then restart ────────────────────────────
    print("\n═══ Test 10: Stop then restart ═══")
    call("cue.execute", {"id": C, "action": "Start"})
    wait_state(C, "Running", timeout=5)
    call("cue.execute", {"id": C, "action": "Stop"})
    t.check(
        "10a: Stopped cleanly",
        wait_state(C, "Stop", timeout=5),
    )
    time.sleep(0.3)
    call("cue.execute", {"id": C, "action": "Start"})
    t.check(
        "10b: Restart reaches Running again",
        wait_state(C, "Running", timeout=5),
    )
    stop_all()


if __name__ == "__main__":
    run_suite("Media Playback Lifecycle", run_tests)
