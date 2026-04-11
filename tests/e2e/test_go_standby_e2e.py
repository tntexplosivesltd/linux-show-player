#!/usr/bin/env python3
"""E2E tests for GO button and standby progression.

Starts LiSP automatically, runs all GO/standby tests, then shuts down.

Run:
    poetry run python tests/e2e/test_go_standby_e2e.py

Options:
    --no-launch    Don't start/stop LiSP (attach to existing)
    --host HOST    Harness host (default: 127.0.0.1)
    --port PORT    Harness port (default: 8070)
"""

import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from tests.e2e.helpers import (
    run_suite, call, cue_state, cue_prop, wait_state,
    stop_all, setup_with_tones, clear_cues,
)


# ── Helpers ───────────────────────────────────────────────────


def standby_index():
    """Return current standby index, or -1 when list is empty."""
    result = call("layout.standby")
    if result is None:
        return -1
    return result["standby_index"]


def sorted_cues():
    """Return all cues sorted by index."""
    return sorted(call("cue.list"), key=lambda c: c["index"])


# ── Tests ─────────────────────────────────────────────────────


def test_1_go_starts_cue_and_advances(t, ids):
    """GO starts the standby cue and standby advances to the next."""
    print("\n=== Test 1: GO starts standby cue, standby advances ===")
    stop_all()
    A = ids["tone_A"]

    # Standby should start at index 0
    call("layout.set_standby_index", {"index": 0})
    initial_idx = standby_index()

    call("layout.go")
    time.sleep(0.4)

    t.check("1: tone_A started", cue_state(A) == "Running")
    t.check("1: standby advanced past A",
            standby_index() > initial_idx)

    stop_all()


def test_2_go_on_group_child_does_nothing(t, ids):
    """GO on a group child at standby does nothing."""
    print("\n=== Test 2: GO on group child does nothing ===")
    stop_all()

    A, B = ids["tone_A"], ids["tone_B"]

    # Group A and B
    call("layout.context_action", {
        "action": "Group selected",
        "cue_ids": [A, B],
    })
    time.sleep(0.4)

    cues = sorted_cues()
    group_id = cues[0]["id"]
    # index 1 is A (first child)
    child_idx = cues[1]["index"]

    call("layout.set_standby_index", {"index": child_idx})
    call("layout.go")
    time.sleep(0.3)

    t.check("2: Child not started by GO", cue_state(A) == "Stop")
    t.check("2: Standby unchanged at child",
            standby_index() == child_idx)

    stop_all()
    # Clean up: ungroup
    call("layout.context_action", {
        "action": "Ungroup", "cue_ids": [group_id],
    })
    time.sleep(0.3)


def test_3_standby_skips_grouped_children(t, ids):
    """After GO fires the group cue, standby skips its children."""
    print("\n=== Test 3: Standby skips grouped children ===")
    stop_all()

    A, B, C = ids["tone_A"], ids["tone_B"], ids["tone_C"]

    # Group A and B; C remains standalone
    call("layout.context_action", {
        "action": "Group selected",
        "cue_ids": [A, B],
    })
    time.sleep(0.4)

    cues = sorted_cues()
    group_id = cues[0]["id"]
    # Layout order: group(0), A(1), B(2), C(3), D(4)
    c_index = next(c["index"] for c in cues if c["id"] == C)

    # Set standby to the group itself
    call("layout.set_standby_index", {"index": 0})
    call("layout.go")
    time.sleep(0.4)

    # With auto_continue=True (default), standby should skip A and B
    # and land on C (first non-child cue after the group)
    t.check("3: Standby skipped children, landed on C",
            standby_index() == c_index)

    stop_all()
    call("layout.context_action", {
        "action": "Ungroup", "cue_ids": [group_id],
    })
    time.sleep(0.3)


def test_4_trigger_after_end_chains(t, ids):
    """next_action=TriggerAfterEnd fires next non-child cue on end."""
    print("\n=== Test 4: TriggerAfterEnd chains to next cue ===")
    stop_all()

    cues = sorted_cues()
    A_id = cues[0]["id"]
    B_id = cues[1]["id"]

    call("cue.set_property", {
        "id": A_id, "property": "next_action",
        "value": "TriggerAfterEnd",
    })

    call("cue.execute", {"id": A_id, "action": "Start"})
    time.sleep(0.3)
    # Seek near end to avoid waiting 8 s
    call("cue.seek", {"id": A_id, "position": 7500})

    # B should start after A ends
    started = wait_state(B_id, "Running", timeout=3.0)
    t.check("4: B started via TriggerAfterEnd", started)

    stop_all()
    # Reset next_action
    call("cue.set_property", {
        "id": A_id, "property": "next_action",
        "value": "DoNothing",
    })


def test_5_select_after_end_moves_standby_only(t, ids):
    """next_action=SelectAfterEnd moves standby, does not execute."""
    print("\n=== Test 5: SelectAfterEnd moves standby only ===")
    stop_all()

    cues = sorted_cues()
    A_id = cues[0]["id"]
    B_id = cues[1]["id"]
    b_index = cues[1]["index"]

    call("cue.set_property", {
        "id": A_id, "property": "next_action",
        "value": "SelectAfterEnd",
    })

    # Point standby away from B so we can detect it moving
    call("layout.set_standby_index", {"index": 0})

    call("cue.execute", {"id": A_id, "action": "Start"})
    time.sleep(0.3)
    call("cue.seek", {"id": A_id, "position": 7500})

    # Wait for A to stop
    wait_state(A_id, "Stop", timeout=3.0)
    time.sleep(0.3)

    t.check("5: B not started", cue_state(B_id) == "Stop")
    t.check("5: Standby moved to B", standby_index() == b_index)

    stop_all()
    call("cue.set_property", {
        "id": A_id, "property": "next_action",
        "value": "DoNothing",
    })


def test_6_trigger_after_wait_delays_then_fires(t, ids):
    """next_action=TriggerAfterWait with post_wait delays then fires."""
    print("\n=== Test 6: TriggerAfterWait delays then fires ===")
    stop_all()

    cues = sorted_cues()
    A_id = cues[0]["id"]
    B_id = cues[1]["id"]

    call("cue.set_property", {
        "id": A_id, "property": "next_action",
        "value": "TriggerAfterWait",
    })
    call("cue.set_property", {
        "id": A_id, "property": "post_wait",
        "value": 1.5,
    })

    call("cue.execute", {"id": A_id, "action": "Start"})
    time.sleep(0.3)
    # Seek A near the end so the post-wait fires quickly
    call("cue.seek", {"id": A_id, "position": 7500})

    # Wait for A to finish (post-wait fires after A ends)
    wait_state(A_id, "Stop", timeout=3.0)

    # B should NOT be running immediately after A stops
    # (post_wait is 1.5 s)
    time.sleep(0.3)
    t.check("6: B not yet started (in post-wait)",
            cue_state(B_id) == "Stop")

    # After 1.5 s post-wait completes, B should start
    started = wait_state(B_id, "Running", timeout=3.0)
    t.check("6: B started after post-wait", started)

    stop_all()
    call("cue.set_property", {
        "id": A_id, "property": "next_action",
        "value": "DoNothing",
    })
    call("cue.set_property", {
        "id": A_id, "property": "post_wait",
        "value": 0,
    })


def test_7_do_nothing_after_end(t, ids):
    """next_action=DoNothing — nothing happens after cue ends."""
    print("\n=== Test 7: DoNothing after cue ends ===")
    stop_all()

    cues = sorted_cues()
    A_id = cues[0]["id"]
    B_id = cues[1]["id"]

    # Confirm DoNothing is set (default)
    call("cue.set_property", {
        "id": A_id, "property": "next_action",
        "value": "DoNothing",
    })

    call("cue.execute", {"id": A_id, "action": "Start"})
    time.sleep(0.3)
    call("cue.seek", {"id": A_id, "position": 7500})

    wait_state(A_id, "Stop", timeout=3.0)
    time.sleep(0.5)

    t.check("7: B not started", cue_state(B_id) == "Stop")


def test_8_go_on_empty_list_does_nothing(t):
    """GO on an empty list does nothing (no crash)."""
    print("\n=== Test 8: GO on empty list does nothing ===")
    clear_cues()
    time.sleep(0.3)

    # Should return None for standby
    t.check("8: Standby is -1 on empty list",
            standby_index() == -1)

    # Should not raise
    try:
        call("layout.go")
        time.sleep(0.2)
        t.check("8: GO on empty list does not crash", True)
    except Exception:
        t.check("8: GO on empty list does not crash", False)


def test_9_auto_continue_false(t, ids):
    """auto_continue=False — GO fires cue but standby does NOT advance."""
    print("\n=== Test 9: auto_continue=False standby stays put ===")
    stop_all()

    A = ids["tone_A"]

    call("layout.set_standby_index", {"index": 0})
    # Disable auto_continue via layout.go advance=0
    call("layout.go", {"advance": 0})
    time.sleep(0.4)

    t.check("9: tone_A started", cue_state(A) == "Running")
    t.check("9: Standby did not advance",
            standby_index() == 0)

    stop_all()


def test_10_standby_at_last_cue(t, ids):
    """Standby at last cue + GO — standby stays at last cue."""
    print("\n=== Test 10: Standby at last cue stays put ===")
    stop_all()

    cues = sorted_cues()
    last = cues[-1]
    last_idx = last["index"]
    last_id = last["id"]

    call("layout.set_standby_index", {"index": last_idx})
    t.check("10: Standby set to last cue",
            standby_index() == last_idx)

    call("layout.go")
    time.sleep(0.4)

    t.check("10: Last cue started", cue_state(last_id) == "Running")
    t.check("10: Standby stays at last cue",
            standby_index() == last_idx)

    stop_all()


# ── Entry point ───────────────────────────────────────────────


def run_tests(t):
    print("\nSetting up test cues...")
    ids = setup_with_tones()

    # Tests 1-7 and 9-10 need cues; test 8 clears them
    test_1_go_starts_cue_and_advances(t, ids)
    test_2_go_on_group_child_does_nothing(t, ids)
    test_3_standby_skips_grouped_children(t, ids)
    test_4_trigger_after_end_chains(t, ids)
    test_5_select_after_end_moves_standby_only(t, ids)
    test_6_trigger_after_wait_delays_then_fires(t, ids)
    test_7_do_nothing_after_end(t, ids)
    test_8_go_on_empty_list_does_nothing(t)

    # Re-create cues for tests 9 and 10
    print("\nRe-setting up test cues for tests 9-10...")
    ids = setup_with_tones()
    test_9_auto_continue_false(t, ids)
    test_10_standby_at_last_cue(t, ids)


if __name__ == "__main__":
    run_suite("GO Button and Standby", run_tests)
