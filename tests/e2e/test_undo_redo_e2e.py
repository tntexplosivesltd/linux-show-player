#!/usr/bin/env python3
"""E2E tests for undo/redo stack integrity.

Verifies that undo/redo correctly reverses and re-applies cue additions,
moves, property changes, grouping, and ungrouping operations, and that
commands.is_saved() and commands.clear() behave correctly.

Run:
    poetry run python tests/e2e/test_undo_redo_e2e.py

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
    clear_cues,
    cue_prop,
    run_suite,
    setup_with_tones,
    stop_all,
)

SAVE_PATH = "/tmp/lisp_undo_redo_e2e_test.lsp"


# ── Poll helpers ───────────────────────────────────────────────

def _wait_for_count(expected, timeout=10.0):
    """Poll cue.count until expected count arrives or timeout."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        count = call("cue.count")["count"]
        if count == expected:
            return count
        time.sleep(0.3)
    return call("cue.count")["count"]


def _sorted_cues():
    """Return all cues sorted by index."""
    return sorted(call("cue.list"), key=lambda c: c["index"])


# ── Tests ──────────────────────────────────────────────────────

def test_1_add_undo_redo(t):
    """Add cue, undo → count=0, redo → count=1 with same ID."""
    print("\n=== Test 1: Add / undo / redo ===")

    clear_cues()
    t.check("1 precond: empty session",
            call("cue.count")["count"] == 0)

    result = call("cue.add", {
        "type": "StopAll",
        "properties": {"name": "Undo Target"},
    })
    added_id = result["id"]
    time.sleep(0.3)
    t.check("1: Cue added", call("cue.count")["count"] == 1)

    call("commands.undo")
    time.sleep(0.3)
    t.check("1: Undo removes cue", _wait_for_count(0) == 0)

    call("commands.redo")
    time.sleep(0.3)
    count_after = _wait_for_count(1)
    t.check("1: Redo restores cue", count_after == 1)

    cues = call("cue.list")
    t.check("1: Same ID after redo",
            len(cues) == 1 and cues[0]["id"] == added_id)


def test_2_move_undo(t):
    """Move cue from index 3 to index 0; undo restores original order."""
    print("\n=== Test 2: Move / undo ===")

    setup_with_tones()
    cues_before = _sorted_cues()
    original_order = [c["id"] for c in cues_before]
    t.check("2 precond: 4 cues loaded", len(original_order) == 4)

    # Move last cue (index 3) to front (index 0)
    call("layout.move_cue", {"from_index": 3, "to_index": 0})
    time.sleep(0.3)

    cues_after_move = _sorted_cues()
    moved_order = [c["id"] for c in cues_after_move]
    # The cue that was last should now be first
    t.check("2: Cue moved to front",
            moved_order[0] == original_order[3])

    call("commands.undo")
    time.sleep(0.3)

    cues_after_undo = _sorted_cues()
    restored_order = [c["id"] for c in cues_after_undo]
    t.check("2: Undo restores original order",
            restored_order == original_order)


def test_3_set_property_undo_redo(t):
    """Set property, undo → original value, redo → updated value."""
    print("\n=== Test 3: Property update / undo / redo ===")

    ids = setup_with_tones()
    cue_id = ids["tone_A"]

    original_name = cue_prop(cue_id, "name")

    call("cue.set_property", {
        "id": cue_id, "property": "name", "value": "Renamed Cue",
    })
    time.sleep(0.2)
    t.check("3: Property updated",
            cue_prop(cue_id, "name") == "Renamed Cue")

    call("commands.undo")
    time.sleep(0.2)
    t.check("3: Undo restores original name",
            cue_prop(cue_id, "name") == original_name)

    call("commands.redo")
    time.sleep(0.2)
    t.check("3: Redo applies updated name",
            cue_prop(cue_id, "name") == "Renamed Cue")


def test_4_group_undo_redo(t):
    """Group 3 cues, undo → ungrouped, redo → regrouped same ID."""
    print("\n=== Test 4: Group / undo / redo ===")

    ids = setup_with_tones()
    A, B, C = ids["tone_A"], ids["tone_B"], ids["tone_C"]

    call("layout.context_action", {
        "action": "Group selected",
        "cue_ids": [A, B, C],
    })
    time.sleep(0.3)

    count_after_group = _wait_for_count(5)
    t.check("4: GroupCue created (5 total)", count_after_group == 5)

    cues_sorted = _sorted_cues()
    group = next(
        (c for c in cues_sorted if c["_type_"] == "GroupCue"),
        None,
    )
    t.check("4: GroupCue present", group is not None)
    if group is None:
        return
    group_id = group["id"]

    t.check("4: Children have group_id",
            all(cue_prop(x, "group_id") == group_id
                for x in [A, B, C]))

    # Undo grouping
    call("commands.undo")
    time.sleep(0.3)
    count_after_undo = _wait_for_count(4)
    t.check("4: Undo removes group (4 total)", count_after_undo == 4)
    t.check("4: Children ungrouped after undo",
            cue_prop(A, "group_id") == "")

    # Redo grouping
    call("commands.redo")
    time.sleep(0.3)
    count_after_redo = _wait_for_count(5)
    t.check("4: Redo restores group (5 total)", count_after_redo == 5)
    t.check("4: Same group ID after redo",
            cue_prop(A, "group_id") == group_id)


def test_5_ungroup_undo_redo(t):
    """Ungroup → undo → group restored; redo → ungrouped again."""
    print("\n=== Test 5: Ungroup / undo / redo ===")

    ids = setup_with_tones()
    A, B, C = ids["tone_A"], ids["tone_B"], ids["tone_C"]

    # Create a group first
    call("layout.context_action", {
        "action": "Group selected",
        "cue_ids": [A, B, C],
    })
    time.sleep(0.3)
    _wait_for_count(5)

    cues_sorted = _sorted_cues()
    group = next(
        (c for c in cues_sorted if c["_type_"] == "GroupCue"),
        None,
    )
    t.check("5 precond: Group created", group is not None)
    if group is None:
        return
    group_id = group["id"]

    # Ungroup
    call("layout.context_action", {
        "action": "Ungroup",
        "cue_ids": [group_id],
    })
    time.sleep(0.3)
    count_after_ungroup = _wait_for_count(4)
    t.check("5: Ungroup removes GroupCue (4 total)",
            count_after_ungroup == 4)
    t.check("5: A ungrouped", cue_prop(A, "group_id") == "")

    # Undo ungroup → group should be restored
    call("commands.undo")
    time.sleep(0.3)
    count_after_undo = _wait_for_count(5)
    t.check("5: Undo restores group (5 total)", count_after_undo == 5)
    t.check("5: A re-grouped after undo",
            cue_prop(A, "group_id") == group_id)

    # Redo ungroup → ungrouped again
    call("commands.redo")
    time.sleep(0.3)
    count_after_redo = _wait_for_count(4)
    t.check("5: Redo ungroups again (4 total)", count_after_redo == 4)
    t.check("5: A ungrouped after redo",
            cue_prop(A, "group_id") == "")


def test_6_is_saved_transitions(t):
    """commands.is_saved() tracks mutations and save correctly."""
    print("\n=== Test 6: is_saved transitions ===")

    ids = setup_with_tones()
    cue_id = ids["tone_A"]

    # Save to establish a clean baseline
    call("session.save", {"path": SAVE_PATH})
    t.check("6: is_saved True after save",
            call("commands.is_saved")["is_saved"] is True)

    # Add a cue — stack is now dirty
    call("cue.add", {
        "type": "StopAll",
        "properties": {"name": "Dirty Cue"},
    })
    time.sleep(0.2)
    t.check("6: is_saved False after cue.add",
            call("commands.is_saved")["is_saved"] is False)

    # Save again — should be clean
    call("session.save", {"path": SAVE_PATH})
    t.check("6: is_saved True after second save",
            call("commands.is_saved")["is_saved"] is True)

    # Move a cue — dirty again
    call("layout.move_cue", {"from_index": 0, "to_index": 1})
    time.sleep(0.2)
    t.check("6: is_saved False after move",
            call("commands.is_saved")["is_saved"] is False)

    # Save again — clean
    call("session.save", {"path": SAVE_PATH})
    t.check("6: is_saved True after move+save",
            call("commands.is_saved")["is_saved"] is True)

    # Set property — dirty again
    call("cue.set_property", {
        "id": cue_id, "property": "name", "value": "Dirty Name",
    })
    time.sleep(0.2)
    t.check("6: is_saved False after set_property",
            call("commands.is_saved")["is_saved"] is False)


def test_7_clear_then_undo_is_noop(t):
    """commands.clear() then undo — count unchanged (no-op)."""
    print("\n=== Test 7: commands.clear then undo is no-op ===")

    clear_cues()

    # Add two cues so there is something to undo
    call("cue.add", {
        "type": "StopAll",
        "properties": {"name": "Cue Alpha"},
    })
    call("cue.add", {
        "type": "StopAll",
        "properties": {"name": "Cue Beta"},
    })
    time.sleep(0.3)
    t.check("7 precond: 2 cues present",
            _wait_for_count(2) == 2)

    # Clear the undo stack
    call("commands.clear")
    time.sleep(0.2)

    # Attempt undo — should be a no-op
    try:
        call("commands.undo")
    except Exception:
        pass  # Some implementations may error on empty stack
    time.sleep(0.3)

    count_after = call("cue.count")["count"]
    t.check("7: Undo after clear leaves cues intact",
            count_after == 2)


def test_8_undo_after_load_is_noop(t):
    """Undo immediately after session.load — count stays same."""
    print("\n=== Test 8: Undo after session.load is no-op ===")

    setup_with_tones()
    call("session.save", {"path": SAVE_PATH})

    # Load the saved session
    call("session.load", {"path": SAVE_PATH})

    # Wait for the load to settle
    count_after_load = _wait_for_count(4)
    t.check("8 precond: 4 cues after load", count_after_load == 4)

    # Attempt undo — should be a no-op (load clears the stack)
    try:
        call("commands.undo")
    except Exception:
        pass  # Empty stack may error; that is acceptable
    time.sleep(0.3)

    count_after_undo = call("cue.count")["count"]
    t.check("8: Count unchanged after undo post-load",
            count_after_undo == 4)


# ── Suite entry point ──────────────────────────────────────────

def run_tests(t):
    try:
        test_1_add_undo_redo(t)
    except Exception as e:
        t.check(f"Test 1 error: {e}", False)

    try:
        test_2_move_undo(t)
    except Exception as e:
        t.check(f"Test 2 error: {e}", False)

    try:
        test_3_set_property_undo_redo(t)
    except Exception as e:
        t.check(f"Test 3 error: {e}", False)

    try:
        test_4_group_undo_redo(t)
    except Exception as e:
        t.check(f"Test 4 error: {e}", False)

    try:
        test_5_ungroup_undo_redo(t)
    except Exception as e:
        t.check(f"Test 5 error: {e}", False)

    try:
        test_6_is_saved_transitions(t)
    except Exception as e:
        t.check(f"Test 6 error: {e}", False)

    try:
        test_7_clear_then_undo_is_noop(t)
    except Exception as e:
        t.check(f"Test 7 error: {e}", False)

    try:
        test_8_undo_after_load_is_noop(t)
    except Exception as e:
        t.check(f"Test 8 error: {e}", False)

    stop_all()


if __name__ == "__main__":
    run_suite("Undo/Redo Stack", run_tests)
