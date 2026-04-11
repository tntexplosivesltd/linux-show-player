#!/usr/bin/env python3
"""E2E tests for IndexActionCue.

Verifies relative and absolute index targeting, correct behaviour
after layout moves, graceful handling of out-of-range indices, and
save/load property fidelity.

Run:
    poetry run python tests/e2e/test_index_action_cue_e2e.py

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

SAVE_PATH = "/tmp/lisp_index_action_cue_e2e.lsp"


def _sorted_cues():
    """Return all cues sorted by layout index."""
    return sorted(call("cue.list"), key=lambda c: c["index"])


def _add_index_action(name, target_index, relative, action=1):
    """Add an IndexActionCue and return its id."""
    result = call("cue.add", {
        "type": "IndexActionCue",
        "properties": {
            "name": name,
            "target_index": target_index,
            "relative": relative,
            "action": action,
        },
    })
    time.sleep(0.3)
    # cue.add returns the new cue dict; id is inside it
    if isinstance(result, dict) and "id" in result:
        return result["id"]
    # Fall back: scan cue list for the name
    cues = call("cue.list")
    match = next((c for c in cues if c["name"] == name), None)
    assert match is not None, f"Could not find added cue: {name}"
    return match["id"]


def _wait_for_count(expected, timeout=10.0):
    """Poll cue.list until expected count arrives or timeout."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        cues = call("cue.list")
        if len(cues) == expected:
            return cues
        time.sleep(0.4)
    return call("cue.list")


# ── Tests ──────────────────────────────────────────────────────


def test_1_relative_targets_next_cue(t):
    """relative=True, target_index=1 — starts the next cue in layout."""
    print("\n=== Test 1: relative=True targets next cue ===")
    stop_all()

    ids = setup_with_tones()
    # Layout is now: [tone_A(0), tone_B(1), tone_C(2), tone_D(3)]

    # Add IndexActionCue at the end: relative offset +1 from its own
    # position will target tone_A (index 0 -> target index 1 = cue at 1
    # when placed at index 4 -> cue at index 5, but with relative=True
    # and target_index=1 it targets self.index + 1).
    # Instead place it before tone_B to target tone_B cleanly.
    # Strategy: insert it at position 0 first via add then move.
    iac_id = _add_index_action(
        "IAC rel+1", target_index=1, relative=True, action=1,
    )

    # Move the IAC to index 0 so that self.index=0 + target_index=1
    # points at index 1 (tone_A after any reorder, but tone_A is now
    # at index 1 since IAC took index 0 when added to the end and we
    # moved it). Let's move IAC to index 0.
    cues = _sorted_cues()
    iac_layout_index = next(
        c["index"] for c in cues if c["id"] == iac_id
    )
    call("layout.move_cue", {
        "from_index": iac_layout_index,
        "to_index": 0,
    })
    time.sleep(0.3)

    # After move: IAC at index 0, tone_A at 1, tone_B at 2, …
    # target = 0 + 1 = 1 → tone_A
    tone_a_id = ids["tone_A"]

    call("cue.execute", {"id": iac_id, "action": "Start"})
    time.sleep(0.5)

    t.check(
        "1: tone_A started by relative IAC",
        cue_state(tone_a_id) == "Running",
    )

    stop_all()


def test_2_absolute_targets_first_cue(t):
    """relative=False, target_index=0 — always targets the first cue."""
    print("\n=== Test 2: relative=False, target_index=0 ===")
    stop_all()

    ids = setup_with_tones()
    # Add an absolute IAC: always targets index 0.
    iac_id = _add_index_action(
        "IAC abs 0", target_index=0, relative=False, action=1,
    )
    # IAC is appended at index 4; tone_A is at index 0.
    tone_a_id = ids["tone_A"]

    call("cue.execute", {"id": iac_id, "action": "Start"})
    time.sleep(0.5)

    t.check(
        "2: tone_A (index 0) started by absolute IAC",
        cue_state(tone_a_id) == "Running",
    )

    stop_all()

    # Move tone_B to index 0 to verify absolute still targets index 0,
    # which is now tone_B.
    cues = _sorted_cues()
    tone_b_layout = next(
        c["index"] for c in cues if c["id"] == ids["tone_B"]
    )
    call("layout.move_cue", {
        "from_index": tone_b_layout,
        "to_index": 0,
    })
    time.sleep(0.3)

    call("cue.execute", {"id": iac_id, "action": "Start"})
    time.sleep(0.5)

    t.check(
        "2: After move, absolute IAC still targets index 0 (tone_B)",
        cue_state(ids["tone_B"]) == "Running",
    )

    stop_all()


def test_3_relative_tracks_after_move(t):
    """After moving the IAC, relative still targets the correct neighbour."""
    print("\n=== Test 3: relative tracks neighbour after move ===")
    stop_all()

    ids = setup_with_tones()
    # Place IAC between tone_B and tone_C:
    #   tone_A(0), tone_B(1), IAC(2), tone_C(3), tone_D(4)
    # relative=True, target_index=1 → targets index 3 (tone_C).
    iac_id = _add_index_action(
        "IAC rel move", target_index=1, relative=True, action=1,
    )

    # IAC was appended (index 4 or 5 after tones at 0-3).
    # Move it to index 2.
    cues = _sorted_cues()
    iac_layout_index = next(
        c["index"] for c in cues if c["id"] == iac_id
    )
    call("layout.move_cue", {
        "from_index": iac_layout_index,
        "to_index": 2,
    })
    time.sleep(0.3)

    # Layout: tone_A(0), tone_B(1), IAC(2), tone_C(3), tone_D(4)
    # relative: 2 + 1 = 3 → tone_C
    tone_c_id = ids["tone_C"]

    call("cue.execute", {"id": iac_id, "action": "Start"})
    time.sleep(0.5)

    t.check(
        "3: tone_C started (neighbour after move)",
        cue_state(tone_c_id) == "Running",
    )

    stop_all()

    # Now move IAC to index 1 → relative: 1 + 1 = 2 → tone_B is now at
    # index 2 (IAC moved away from 2, tone_B slides to 1 or 2 depending
    # on direction). Re-query the layout to find tone_B's current index.
    cues = _sorted_cues()
    iac_layout_index = next(
        c["index"] for c in cues if c["id"] == iac_id
    )
    call("layout.move_cue", {
        "from_index": iac_layout_index,
        "to_index": 1,
    })
    time.sleep(0.3)

    # Layout after move: tone_A(0), IAC(1), tone_B(2), tone_C(3), tone_D(4)
    # relative: 1 + 1 = 2 → tone_B
    tone_b_id = ids["tone_B"]

    call("cue.execute", {"id": iac_id, "action": "Start"})
    time.sleep(0.5)

    t.check(
        "3: tone_B started after second move",
        cue_state(tone_b_id) == "Running",
    )

    stop_all()


def test_4_out_of_range_no_crash(t):
    """Target index beyond list length does not crash LiSP."""
    print("\n=== Test 4: Out-of-range target index does not crash ===")
    stop_all()

    ids = setup_with_tones()
    # 4 tones at indices 0-3; target index 999 is well beyond the list.
    iac_id = _add_index_action(
        "IAC oob", target_index=999, relative=False, action=1,
    )

    try:
        call("cue.execute", {"id": iac_id, "action": "Start"})
        time.sleep(0.5)
        t.check("4: No crash on out-of-range index", True)
    except Exception as exc:
        t.check(f"4: No crash on out-of-range index (got {exc})", False)

    # Verify no tone was started unexpectedly.
    any_running = any(
        cue_state(cid) == "Running"
        for cid in ids.values()
    )
    t.check("4: No tone started by out-of-range IAC", not any_running)

    stop_all()


def test_5_save_load_preserves_properties(t):
    """Save/load preserves target_index and relative properties."""
    print("\n=== Test 5: Save/load preserves target_index and relative ===")
    stop_all()

    setup_with_tones()

    iac_id = _add_index_action(
        "IAC save test", target_index=3, relative=False, action=1,
    )

    # Verify properties before save
    t.check(
        "5 precond: target_index=3",
        cue_prop(iac_id, "target_index") == 3,
    )
    t.check(
        "5 precond: relative=False",
        cue_prop(iac_id, "relative") is False,
    )

    call("session.save", {"path": SAVE_PATH})
    call("session.load", {"path": SAVE_PATH})

    # 4 tones + 1 IAC = 5 cues
    _wait_for_count(5)
    cues = call("cue.list")
    reloaded = next(
        (c for c in cues if c["name"] == "IAC save test"),
        None,
    )

    t.check("5: IAC found after reload", reloaded is not None)
    if reloaded is None:
        return

    rid = reloaded["id"]
    t.check(
        "5: target_index preserved after reload",
        cue_prop(rid, "target_index") == 3,
    )
    t.check(
        "5: relative preserved after reload",
        cue_prop(rid, "relative") is False,
    )


# ── Suite entry point ──────────────────────────────────────────


def run_tests(t):
    try:
        test_1_relative_targets_next_cue(t)
    except Exception as exc:
        t.check(f"Test 1 error: {exc}", False)

    try:
        test_2_absolute_targets_first_cue(t)
    except Exception as exc:
        t.check(f"Test 2 error: {exc}", False)

    try:
        test_3_relative_tracks_after_move(t)
    except Exception as exc:
        t.check(f"Test 3 error: {exc}", False)

    try:
        test_4_out_of_range_no_crash(t)
    except Exception as exc:
        t.check(f"Test 4 error: {exc}", False)

    try:
        test_5_save_load_preserves_properties(t)
    except Exception as exc:
        t.check(f"Test 5 error: {exc}", False)

    stop_all()


if __name__ == "__main__":
    run_suite("IndexActionCue", run_tests)
