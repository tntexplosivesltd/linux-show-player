#!/usr/bin/env python3
"""E2E tests for pre/post-wait with next_action chaining.

Tests pre-wait state transitions, stop/pause during pre-wait,
post-wait with TriggerAfterWait/TriggerAfterEnd, SelectAfterEnd
standby advancement, 3-cue sequential chain, and last-cue no-crash.

Run:
    poetry run python tests/e2e/test_wait_chaining_e2e.py

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
    cue_prop,
    wait_state,
    stop_all,
    setup_with_tones,
    clear_cues,
)


# ── Helpers ───────────────────────────────────────────────────


def sorted_cues():
    """Return all cues sorted by index."""
    return sorted(call("cue.list"), key=lambda c: c["index"])


def standby_index():
    """Return current standby index, or -1 when list is empty."""
    result = call("layout.standby")
    if result is None:
        return -1
    return result["standby_index"]


def reset_cue_waits(cue_id):
    """Reset pre_wait, post_wait, and next_action to defaults."""
    call("cue.set_property",
         {"id": cue_id, "property": "pre_wait", "value": 0})
    call("cue.set_property",
         {"id": cue_id, "property": "post_wait", "value": 0})
    call("cue.set_property",
         {"id": cue_id, "property": "next_action", "value": "DoNothing"})


# ── Tests ─────────────────────────────────────────────────────


def test_1_pre_wait_holds_then_runs(t, ids):
    """pre_wait=1.5s: state=PreWait for ~1.5s, then transitions to Running."""
    print("\n=== Test 1: pre_wait holds in PreWait then transitions to Running ===")
    stop_all()

    A = ids["tone_A"]
    call("cue.set_property",
         {"id": A, "property": "pre_wait", "value": 1.5})

    call("cue.execute", {"id": A, "action": "Start"})
    # Immediately after start, should be in PreWait
    time.sleep(0.1)
    t.check("1a: state is PreWait immediately after start",
            cue_state(A) == "PreWait")

    # After pre-wait elapses, should transition to Running
    t.check("1b: state becomes Running after pre_wait",
            wait_state(A, "Running", timeout=4.0))

    stop_all()
    reset_cue_waits(A)


def test_2_stop_during_pre_wait(t, ids):
    """Stop during pre_wait returns to Stop immediately."""
    print("\n=== Test 2: Stop during pre_wait → Stop immediately ===")
    stop_all()

    A = ids["tone_A"]
    call("cue.set_property",
         {"id": A, "property": "pre_wait", "value": 1.5})

    call("cue.execute", {"id": A, "action": "Start"})
    time.sleep(0.1)
    t.check("2a: in PreWait before stop",
            cue_state(A) == "PreWait")

    call("cue.execute", {"id": A, "action": "Stop"})
    t.check("2b: state returns to Stop immediately",
            wait_state(A, "Stop", timeout=2.0))

    # Confirm it does NOT proceed to Running
    time.sleep(0.3)
    t.check("2c: still Stop (pre_wait did not resume)",
            cue_state(A) == "Stop")

    stop_all()
    reset_cue_waits(A)


def test_3_pause_resume_during_pre_wait(t, ids):
    """Pause during pre_wait → PreWait_Pause; resume continues wait."""
    print("\n=== Test 3: Pause/resume during pre_wait ===")
    stop_all()

    A = ids["tone_A"]
    call("cue.set_property",
         {"id": A, "property": "pre_wait", "value": 3.0})

    call("cue.execute", {"id": A, "action": "Start"})
    time.sleep(0.2)
    t.check("3a: in PreWait before pause",
            cue_state(A) == "PreWait")

    call("cue.execute", {"id": A, "action": "Pause"})
    time.sleep(0.1)
    t.check("3b: state is PreWait_Pause after pause",
            cue_state(A) == "PreWait_Pause")

    # Confirm it does not auto-advance while paused
    time.sleep(0.5)
    t.check("3c: still PreWait_Pause (not Running)",
            cue_state(A) == "PreWait_Pause")

    call("cue.execute", {"id": A, "action": "Resume"})
    t.check("3d: state becomes Running after resume",
            wait_state(A, "Running", timeout=5.0))

    stop_all()
    reset_cue_waits(A)


def test_4_post_wait_trigger_after_wait(t, ids):
    """post_wait=1.5s + TriggerAfterWait: next cue starts after wait elapses."""
    print("\n=== Test 4: post_wait + TriggerAfterWait fires next cue ===")
    stop_all()

    cues = sorted_cues()
    A_id = cues[0]["id"]
    B_id = cues[1]["id"]

    call("cue.set_property",
         {"id": A_id, "property": "next_action", "value": "TriggerAfterWait"})
    call("cue.set_property",
         {"id": A_id, "property": "post_wait", "value": 3.0})

    call("cue.execute", {"id": A_id, "action": "Start"})
    wait_state(A_id, "Running", timeout=3.0)
    # Seek near end so content ends quickly
    call("cue.seek", {"id": A_id, "position": 7500})

    # After content ends + post_wait elapses, B should start
    t.check("4: B started after post-wait elapses",
            wait_state(B_id, "Running", timeout=8.0))

    stop_all()
    reset_cue_waits(A_id)


def test_5_trigger_after_end(t, ids):
    """TriggerAfterEnd: next cue starts only after audio ends naturally."""
    print("\n=== Test 5: TriggerAfterEnd starts next cue after audio ends ===")
    stop_all()

    cues = sorted_cues()
    A_id = cues[0]["id"]
    B_id = cues[1]["id"]

    call("cue.set_property",
         {"id": A_id, "property": "next_action", "value": "TriggerAfterEnd"})

    call("cue.execute", {"id": A_id, "action": "Start"})
    wait_state(A_id, "Running", timeout=3.0)
    # Seek near end to trigger natural end quickly
    call("cue.seek", {"id": A_id, "position": 7500})

    # B should start after A ends naturally
    t.check("5: B started via TriggerAfterEnd",
            wait_state(B_id, "Running", timeout=3.0))

    stop_all()
    reset_cue_waits(A_id)


def test_6_select_after_end_standby_only(t, ids):
    """SelectAfterEnd: standby advances to next cue, nothing runs."""
    print("\n=== Test 6: SelectAfterEnd advances standby only ===")
    stop_all()

    cues = sorted_cues()
    A_id = cues[0]["id"]
    B_id = cues[1]["id"]
    b_index = cues[1]["index"]

    call("cue.set_property",
         {"id": A_id, "property": "next_action", "value": "SelectAfterEnd"})

    # Move standby away from B so we can detect it moving there
    call("layout.set_standby_index", {"index": 0})

    call("cue.execute", {"id": A_id, "action": "Start"})
    wait_state(A_id, "Running", timeout=3.0)
    call("cue.seek", {"id": A_id, "position": 7500})

    # Wait for A to stop
    wait_state(A_id, "Stop", timeout=3.0)
    time.sleep(0.3)

    t.check("6a: B not started (SelectAfterEnd only moves standby)",
            cue_state(B_id) == "Stop")
    t.check("6b: standby moved to B",
            standby_index() == b_index)

    stop_all()
    reset_cue_waits(A_id)


def test_7_chain_of_3_trigger_after_end(t, ids):
    """Chain of 3 cues with TriggerAfterEnd produces sequential playback."""
    print("\n=== Test 7: 3-cue TriggerAfterEnd chain plays sequentially ===")
    stop_all()

    cues = sorted_cues()
    A_id = cues[0]["id"]
    B_id = cues[1]["id"]
    C_id = cues[2]["id"]

    # Set TriggerAfterEnd on both A and B
    for cue_id in (A_id, B_id):
        call("cue.set_property",
             {"id": cue_id, "property": "next_action",
              "value": "TriggerAfterEnd"})

    # Start A and seek near end
    call("cue.execute", {"id": A_id, "action": "Start"})
    wait_state(A_id, "Running", timeout=3.0)
    call("cue.seek", {"id": A_id, "position": 7500})

    # A → B: B should start after A ends
    t.check("7a: B started after A ends (TriggerAfterEnd)",
            wait_state(B_id, "Running", timeout=3.0))

    # Seek B near end so C fires quickly
    call("cue.seek", {"id": B_id, "position": 7500})

    # B → C: C should start after B ends
    t.check("7b: C started after B ends (TriggerAfterEnd)",
            wait_state(C_id, "Running", timeout=3.0))

    stop_all()
    reset_cue_waits(A_id)
    reset_cue_waits(B_id)


def test_8_trigger_after_end_on_last_cue(t, ids):
    """TriggerAfterEnd on last cue in list — no crash, no chain."""
    print("\n=== Test 8: TriggerAfterEnd on last cue does not crash ===")
    stop_all()

    cues = sorted_cues()
    last = cues[-1]
    last_id = last["id"]

    call("cue.set_property",
         {"id": last_id, "property": "next_action",
          "value": "TriggerAfterEnd"})

    call("cue.execute", {"id": last_id, "action": "Start"})
    wait_state(last_id, "Running", timeout=3.0)
    # Seek near end to trigger natural end
    call("cue.seek", {"id": last_id, "position": 7500})

    # Last cue should stop cleanly
    t.check("8a: last cue stops cleanly at end",
            wait_state(last_id, "Stop", timeout=3.0))

    # Verify LiSP is still responsive (no crash)
    try:
        call("ping")
        t.check("8b: LiSP still responsive after last-cue chain", True)
    except Exception:
        t.check("8b: LiSP still responsive after last-cue chain", False)

    stop_all()
    reset_cue_waits(last_id)


# ── Entry point ───────────────────────────────────────────────


def run_tests(t):
    print("\nSetting up test cues...")
    ids = setup_with_tones()

    test_1_pre_wait_holds_then_runs(t, ids)
    test_2_stop_during_pre_wait(t, ids)
    test_3_pause_resume_during_pre_wait(t, ids)
    test_4_post_wait_trigger_after_wait(t, ids)
    test_5_trigger_after_end(t, ids)
    test_6_select_after_end_standby_only(t, ids)
    test_7_chain_of_3_trigger_after_end(t, ids)
    test_8_trigger_after_end_on_last_cue(t, ids)


if __name__ == "__main__":
    run_suite("Wait Chaining", run_tests)
