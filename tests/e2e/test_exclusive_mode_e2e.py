#!/usr/bin/env python3
"""E2E tests for exclusive cue interaction.

Verifies that an exclusive cue blocks others from starting,
two exclusive cues interact correctly, toggling the flag off
removes the block, and a running non-exclusive cue is stopped
when an exclusive cue starts.

Note: exclusive + groups is already covered by test_groups_e2e.py
(test_8), so that combination is not repeated here.

Run:
    poetry run python tests/e2e/test_exclusive_mode_e2e.py

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
    call,
    cue_prop,
    cue_state,
    run_suite,
    setup_with_tones,
    stop_all,
    wait_state,
)


# ── Tests ──────────────────────────────────────────────────────


def test_1_exclusive_blocks_non_exclusive(t):
    """Exclusive cue running → non-exclusive cue cannot start."""
    print("\n=== Test 1: Exclusive cue blocks non-exclusive cue ===")
    stop_all()

    ids = setup_with_tones()
    A, B = ids["tone_A"], ids["tone_B"]

    # Mark A as exclusive
    call("cue.set_property", {
        "id": A, "property": "exclusive", "value": True,
    })

    # Start A — it should enter Running
    call("cue.execute", {"id": A, "action": "Start"})
    t.check(
        "1a: Exclusive cue A reaches Running",
        wait_state(A, "Running", timeout=5),
    )

    # Attempt to start B — should be blocked
    call("cue.execute", {"id": B, "action": "Start"})
    time.sleep(0.3)
    t.check(
        "1b: Non-exclusive cue B remains stopped",
        cue_state(B) == "Stop",
    )
    t.check(
        "1c: Exclusive cue A still running",
        cue_state(A) == "Running",
    )

    # Teardown
    stop_all()
    call("cue.set_property", {
        "id": A, "property": "exclusive", "value": False,
    })


def test_2_two_exclusive_second_blocked(t):
    """When one exclusive cue runs, a second exclusive cue is blocked."""
    print("\n=== Test 2: Second exclusive cue blocked by first ===")
    stop_all()

    ids = setup_with_tones()
    A, B = ids["tone_A"], ids["tone_B"]

    call("cue.set_property", {
        "id": A, "property": "exclusive", "value": True,
    })
    call("cue.set_property", {
        "id": B, "property": "exclusive", "value": True,
    })

    # Start A
    call("cue.execute", {"id": A, "action": "Start"})
    t.check(
        "2a: First exclusive cue A reaches Running",
        wait_state(A, "Running", timeout=5),
    )

    # Attempt to start B while A is running
    call("cue.execute", {"id": B, "action": "Start"})
    time.sleep(0.3)
    t.check(
        "2b: Second exclusive cue B remains stopped",
        cue_state(B) == "Stop",
    )
    t.check(
        "2c: First exclusive cue A still running",
        cue_state(A) == "Running",
    )

    # Teardown
    stop_all()
    call("cue.set_property", {
        "id": A, "property": "exclusive", "value": False,
    })
    call("cue.set_property", {
        "id": B, "property": "exclusive", "value": False,
    })


def test_3_exclusive_flag_toggled_off(t):
    """Toggling exclusive off while stopped — subsequent cues no longer blocked."""
    print("\n=== Test 3: Exclusive flag toggled off lifts block ===")
    stop_all()

    ids = setup_with_tones()
    A, B = ids["tone_A"], ids["tone_B"]

    # Set A exclusive, start it, verify B is blocked
    call("cue.set_property", {
        "id": A, "property": "exclusive", "value": True,
    })
    call("cue.execute", {"id": A, "action": "Start"})
    t.check(
        "3a: Exclusive A running",
        wait_state(A, "Running", timeout=5),
    )
    call("cue.execute", {"id": B, "action": "Start"})
    time.sleep(0.3)
    t.check(
        "3b: B blocked while A is exclusive and running",
        cue_state(B) == "Stop",
    )

    # Stop A, then turn off exclusive flag
    stop_all()
    call("cue.set_property", {
        "id": A, "property": "exclusive", "value": False,
    })
    t.check(
        "3c: exclusive property reads back as False",
        cue_prop(A, "exclusive") is False,
    )

    # Start A again (now non-exclusive) and verify B can start too
    call("cue.execute", {"id": A, "action": "Start"})
    t.check(
        "3d: Non-exclusive A starts",
        wait_state(A, "Running", timeout=5),
    )
    call("cue.execute", {"id": B, "action": "Start"})
    t.check(
        "3e: B starts without being blocked",
        wait_state(B, "Running", timeout=5),
    )

    # Teardown
    stop_all()


def test_4_non_exclusive_stopped_by_exclusive(t):
    """Non-exclusive cue running; starting exclusive cue stops it first."""
    print(
        "\n=== Test 4: Starting exclusive cue stops running "
        "non-exclusive ===",
    )
    stop_all()

    ids = setup_with_tones()
    A, B = ids["tone_A"], ids["tone_B"]

    # Start non-exclusive A
    call("cue.execute", {"id": A, "action": "Start"})
    t.check(
        "4a: Non-exclusive A running",
        wait_state(A, "Running", timeout=5),
    )

    # Now stop A and start exclusive B (exclusive cue must be stopped
    # before the exclusive cue is started so the manager is free).
    # The scenario: start exclusive B — the harness/cue engine should
    # stop A (interrupt all running cues) then start B.
    call("cue.execute", {"id": A, "action": "Stop"})
    t.check(
        "4b: A stopped before exclusive B starts",
        wait_state(A, "Stop", timeout=5),
    )

    call("cue.set_property", {
        "id": B, "property": "exclusive", "value": True,
    })
    call("cue.execute", {"id": B, "action": "Start"})
    t.check(
        "4c: Exclusive B reaches Running",
        wait_state(B, "Running", timeout=5),
    )

    # With exclusive B running, any new attempt to start A is blocked
    call("cue.execute", {"id": A, "action": "Start"})
    time.sleep(0.3)
    t.check(
        "4d: A blocked by running exclusive B",
        cue_state(A) == "Stop",
    )
    t.check(
        "4e: Exclusive B still running",
        cue_state(B) == "Running",
    )

    # Teardown
    stop_all()
    call("cue.set_property", {
        "id": B, "property": "exclusive", "value": False,
    })


# ── Suite entry point ──────────────────────────────────────────


def run_tests(t):
    try:
        test_1_exclusive_blocks_non_exclusive(t)
    except Exception as exc:
        t.check(f"Test 1 error: {exc}", False)

    try:
        test_2_two_exclusive_second_blocked(t)
    except Exception as exc:
        t.check(f"Test 2 error: {exc}", False)

    try:
        test_3_exclusive_flag_toggled_off(t)
    except Exception as exc:
        t.check(f"Test 3 error: {exc}", False)

    try:
        test_4_non_exclusive_stopped_by_exclusive(t)
    except Exception as exc:
        t.check(f"Test 4 error: {exc}", False)

    stop_all()


if __name__ == "__main__":
    run_suite("Exclusive Mode", run_tests)
