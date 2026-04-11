#!/usr/bin/env python3
"""E2E tests for global controls (StopAll/PauseAll/ResumeAll/InterruptAll).

Covers layout-level broadcast operations and the StopAll cue type.

Run:
    poetry run python tests/e2e/test_global_controls_e2e.py

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
    clear_cues,
)


# ── Helpers ────────────────────────────────────────────────────


def _start_all_tones(ids):
    """Start all four tone cues and wait until each is Running."""
    for cid in ids.values():
        call("cue.execute", {"id": cid, "action": "Start"})
    for cid in ids.values():
        wait_state(cid, "Running", timeout=5)


def _all_in_state(ids, target):
    """Return True if every cue id is in the given state."""
    return all(cue_state(cid) == target for cid in ids.values())


# ── Tests ──────────────────────────────────────────────────────


def test_1_stop_all_stops_running(t):
    """layout.stop_all → all running cues reach Stop."""
    print("\n=== Test 1: stop_all stops all running cues ===")
    stop_all()

    ids = setup_with_tones()
    _start_all_tones(ids)

    t.check(
        "1 precond: all tones Running",
        _all_in_state(ids, "Running"),
    )

    call("layout.stop_all")

    reached = all(
        wait_state(cid, "Stop", timeout=5) for cid in ids.values()
    )
    t.check("1: all cues reach Stop after stop_all", reached)


def test_2_pause_all(t):
    """layout.pause_all → all running cues reach Pause."""
    print("\n=== Test 2: pause_all pauses all running cues ===")
    stop_all()

    ids = setup_with_tones()
    _start_all_tones(ids)

    t.check(
        "2 precond: all tones Running",
        _all_in_state(ids, "Running"),
    )

    call("layout.pause_all")

    reached = all(
        wait_state(cid, "Pause", timeout=5) for cid in ids.values()
    )
    t.check("2: all cues reach Pause after pause_all", reached)

    stop_all()


def test_3_resume_all(t):
    """layout.resume_all after pause_all → all cues return to Running."""
    print("\n=== Test 3: resume_all after pause_all ===")
    stop_all()

    ids = setup_with_tones()
    _start_all_tones(ids)

    call("layout.pause_all")
    paused = all(
        wait_state(cid, "Pause", timeout=5) for cid in ids.values()
    )
    t.check("3 precond: all tones Paused", paused)

    call("layout.resume_all")

    reached = all(
        wait_state(cid, "Running", timeout=5) for cid in ids.values()
    )
    t.check("3: all cues return to Running after resume_all", reached)

    stop_all()


def test_4_interrupt_all(t):
    """layout.interrupt_all → all running cues reach Stop immediately."""
    print("\n=== Test 4: interrupt_all stops all cues immediately ===")
    stop_all()

    ids = setup_with_tones()
    _start_all_tones(ids)

    t.check(
        "4 precond: all tones Running",
        _all_in_state(ids, "Running"),
    )

    call("layout.interrupt_all")

    # interrupt_all is immediate — use a tight timeout
    reached = all(
        wait_state(cid, "Stop", timeout=5) for cid in ids.values()
    )
    t.check("4: all cues reach Stop after interrupt_all", reached)


def test_5_stop_all_cue_type(t):
    """StopAll cue with default action (Stop) stops all running cues."""
    print("\n=== Test 5: StopAll cue type stops all cues ===")
    stop_all()

    ids = setup_with_tones()
    _start_all_tones(ids)

    t.check(
        "5 precond: all tones Running",
        _all_in_state(ids, "Running"),
    )

    # Add a StopAll cue — default action is Stop
    result = call("cue.add", {
        "type": "StopAll",
        "properties": {"name": "StopAll Cue"},
    })
    sa_id = result["id"]
    time.sleep(0.3)

    call("cue.execute", {"id": sa_id, "action": "Start"})

    reached = all(
        wait_state(cid, "Stop", timeout=5) for cid in ids.values()
    )
    t.check("5: StopAll cue stops all running tones", reached)

    stop_all()


def test_6_stop_all_during_prewait(t):
    """stop_all fires while a cue is in PreWait — cue stops before content."""
    print("\n=== Test 6: stop_all interrupts cue in PreWait ===")
    stop_all()

    ids = setup_with_tones()
    A = ids["tone_A"]

    # Give tone_A a long pre_wait so it stays in PreWait long enough
    # for us to fire stop_all while it is waiting.
    call("cue.set_property", {
        "id": A, "property": "pre_wait", "value": 10.0,
    })

    call("cue.execute", {"id": A, "action": "Start"})

    # Poll briefly for PreWait state
    deadline = time.time() + 5
    in_prewait = False
    while time.time() < deadline:
        state = cue_state(A)
        if "PreWait" in state:
            in_prewait = True
            break
        time.sleep(0.1)

    t.check("6 precond: cue entered PreWait", in_prewait)

    call("layout.stop_all")

    reached_stop = wait_state(A, "Stop", timeout=5)
    t.check("6: cue stops from PreWait on stop_all", reached_stop)

    # Restore pre_wait to 0 for subsequent tests
    call("cue.set_property", {
        "id": A, "property": "pre_wait", "value": 0.0,
    })


def test_7_global_controls_empty_model(t):
    """Global controls on empty model / all-stopped model do not crash."""
    print("\n=== Test 7: global controls on empty/stopped model ===")

    clear_cues()

    # All four controls must succeed without raising
    try:
        call("layout.stop_all")
        call("layout.pause_all")
        call("layout.resume_all")
        call("layout.interrupt_all")
        t.check("7a: global controls on empty model do not crash", True)
    except Exception as exc:
        t.check(
            f"7a: global controls on empty model do not crash ({exc})",
            False,
        )

    # With cues in stopped state
    ids = setup_with_tones()
    # All tones are Stop at this point

    try:
        call("layout.stop_all")
        call("layout.pause_all")
        call("layout.resume_all")
        call("layout.interrupt_all")
        t.check(
            "7b: global controls on all-stopped model do not crash",
            True,
        )
    except Exception as exc:
        t.check(
            f"7b: global controls on all-stopped model do not crash ({exc})",
            False,
        )

    # Cues should still be Stop after the above calls
    all_stopped = _all_in_state(ids, "Stop")
    t.check("7c: cues remain Stop after controls on stopped model", all_stopped)


# ── Suite entry point ──────────────────────────────────────────


def run_tests(t):
    try:
        test_1_stop_all_stops_running(t)
    except Exception as exc:
        t.check(f"Test 1 error: {exc}", False)

    try:
        test_2_pause_all(t)
    except Exception as exc:
        t.check(f"Test 2 error: {exc}", False)

    try:
        test_3_resume_all(t)
    except Exception as exc:
        t.check(f"Test 3 error: {exc}", False)

    try:
        test_4_interrupt_all(t)
    except Exception as exc:
        t.check(f"Test 4 error: {exc}", False)

    try:
        test_5_stop_all_cue_type(t)
    except Exception as exc:
        t.check(f"Test 5 error: {exc}", False)

    try:
        test_6_stop_all_during_prewait(t)
    except Exception as exc:
        t.check(f"Test 6 error: {exc}", False)

    try:
        test_7_global_controls_empty_model(t)
    except Exception as exc:
        t.check(f"Test 7 error: {exc}", False)

    stop_all()


if __name__ == "__main__":
    run_suite("Global Controls", run_tests)
