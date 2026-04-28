#!/usr/bin/env python3
"""E2E tests for cart-layout click → inspector wiring.

Regression coverage for the bug where switching to the inspector
left cart users with no way to edit cues — plain click runs the
cue (cart's defining behaviour), Ctrl+click toggles into the
multi-selection, and Shift+click should make this cue the sole
selection so the inspector binds to it.

Run:
    poetry run python tests/e2e/test_cart_inspector_e2e.py
"""

import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from tests.e2e.helpers import (  # noqa: E402
    call,
    run_suite,
    setup_with_tones,
    stop_all,
    wait_state,
)


def _settle_selection():
    # Cart layout coalesces selectedChanged emissions on a 0-tick
    # timer; give that one event-loop spin to flush.
    time.sleep(0.1)


def test_1_plain_click_executes_no_selection(t, ids):
    """Plain click runs the cue and leaves selection untouched."""
    print("\n=== Test 1: plain click executes ===")

    A = ids["tone_A"]

    # Start from a clean slate.
    call("cart.click_cue", {"cue_id": A, "modifier": "none"})
    t.check("1a: cue starts on plain click", wait_state(A, "Running"))

    selected = call("layout.selected_cues") or []
    selected_ids = [c.get("id") for c in selected]
    t.check(
        "1b: plain click did not add cue to selection",
        A not in selected_ids,
    )

    state = call("inspector.state")
    t.check(
        "1c: inspector remains empty after plain click",
        state["cue_ids"] == [],
    )

    call("cue.execute", {"id": A, "action": "Stop"})
    wait_state(A, "Stop")


def test_2_shift_click_exclusive_selects_and_binds(t, ids):
    """Shift+click selects only that cue and the inspector binds."""
    print("\n=== Test 2: shift+click drives inspector ===")

    A = ids["tone_A"]
    B = ids["tone_B"]

    call("cart.click_cue", {"cue_id": A, "modifier": "shift"})
    _settle_selection()

    state = call("inspector.state")
    t.check(
        "2a: inspector binds to A only",
        state["cue_ids"] == [A],
    )
    t.check(
        "2b: A is the sole selection",
        sorted([c.get("id") for c in (call("layout.selected_cues") or [])])
        == [A],
    )

    # Switching the exclusive selection drops the previous binding.
    call("cart.click_cue", {"cue_id": B, "modifier": "shift"})
    _settle_selection()

    state = call("inspector.state")
    t.check(
        "2c: inspector follows the new exclusive selection",
        state["cue_ids"] == [B],
    )
    t.check(
        "2d: previous exclusive selection cleared",
        sorted([c.get("id") for c in (call("layout.selected_cues") or [])])
        == [B],
    )

    # Shift+click never starts the cue.
    t.check(
        "2e: shift+click did not start the cue",
        call("cue.state", {"id": B})["state_name"] != "Running",
    )


def test_3_ctrl_click_still_additive(t, ids):
    """Ctrl+click keeps its multi-select toggle behaviour."""
    print("\n=== Test 3: ctrl+click still additive ===")

    A = ids["tone_A"]
    B = ids["tone_B"]
    C = ids["tone_C"]

    # Reset selection by binding the inspector to nothing via an
    # exclusive shift+click somewhere, then ctrl-toggling it off.
    call("cart.click_cue", {"cue_id": A, "modifier": "shift"})
    _settle_selection()
    call("cart.click_cue", {"cue_id": A, "modifier": "ctrl"})
    _settle_selection()

    call("cart.click_cue", {"cue_id": A, "modifier": "ctrl"})
    call("cart.click_cue", {"cue_id": B, "modifier": "ctrl"})
    _settle_selection()

    selected = sorted(
        c.get("id") for c in (call("layout.selected_cues") or [])
    )
    t.check(
        "3a: ctrl+click adds to multi-selection",
        selected == sorted([A, B]),
    )

    state = call("inspector.state")
    t.check(
        "3b: inspector reflects multi-selection",
        sorted(state["cue_ids"]) == sorted([A, B]),
    )

    # Shift on top of a multi-selection collapses to the chosen cue.
    call("cart.click_cue", {"cue_id": C, "modifier": "shift"})
    _settle_selection()

    state = call("inspector.state")
    t.check(
        "3c: shift+click collapses multi-selection to chosen cue",
        state["cue_ids"] == [C],
    )


def test_4_shift_click_rebuilds_tabs_across_cue_types(t, ids):
    """Shift+click between MediaCue and an action cue rebuilds tabs."""
    print("\n=== Test 4: cross-type tab rebuild ===")

    A = ids["tone_A"]

    # Add a non-MediaCue cell so the inspector has to swap tab rows
    # when the exclusive selection moves between types.
    stop_id = call("cue.add", {
        "type": "StopAll",
        "properties": {"name": "stop-all"},
    })["id"]
    time.sleep(0.2)

    call("cart.click_cue", {"cue_id": A, "modifier": "shift"})
    _settle_selection()

    state = call("inspector.state")
    t.check(
        "4a: MediaCue selection shows the Media Cue page",
        "Media Cue" in state["page_names"],
    )

    call("cart.click_cue", {"cue_id": stop_id, "modifier": "shift"})
    _settle_selection()

    state = call("inspector.state")
    t.check(
        "4b: inspector rebound to action cue",
        state["cue_ids"] == [stop_id],
    )
    t.check(
        "4c: Media Cue page is gone for action-cue selection",
        "Media Cue" not in state["page_names"],
    )
    t.check(
        "4d: General page is still present",
        "General" in state["page_names"],
    )

    # Swap back; the Media Cue tab must reappear.
    call("cart.click_cue", {"cue_id": A, "modifier": "shift"})
    _settle_selection()

    state = call("inspector.state")
    t.check(
        "4e: Media Cue page returns when binding back to MediaCue",
        "Media Cue" in state["page_names"],
    )

    call("cue.remove", {"id": stop_id})
    time.sleep(0.2)


def test_5_remove_clears_inspector(t, ids):
    """Removing a shift+click-selected cue empties the inspector."""
    print("\n=== Test 5: remove while bound ===")

    A = ids["tone_A"]

    call("cart.click_cue", {"cue_id": A, "modifier": "shift"})
    _settle_selection()

    state = call("inspector.state")
    t.check(
        "5a: precondition — A is the inspector binding",
        state["cue_ids"] == [A],
    )

    call("cue.remove", {"id": A})
    time.sleep(0.3)

    state = call("inspector.state")
    t.check(
        "5b: inspector empties when its sole cue is removed",
        state["cue_ids"] == [],
    )
    t.check(
        "5c: tab row is empty after removal",
        state["tab_count"] == 0,
    )

    selected = call("layout.selected_cues") or []
    t.check(
        "5d: layout selection no longer references the removed cue",
        A not in [c.get("id") for c in selected],
    )


def run_tests(t):
    print("\nSetting up test cues...")
    ids = setup_with_tones()

    try:
        test_1_plain_click_executes_no_selection(t, ids)
    except Exception as e:
        t.check(f"Test 1 error: {e}", False)

    try:
        test_2_shift_click_exclusive_selects_and_binds(t, ids)
    except Exception as e:
        t.check(f"Test 2 error: {e}", False)

    try:
        test_3_ctrl_click_still_additive(t, ids)
    except Exception as e:
        t.check(f"Test 3 error: {e}", False)

    try:
        test_4_shift_click_rebuilds_tabs_across_cue_types(t, ids)
    except Exception as e:
        t.check(f"Test 4 error: {e}", False)

    try:
        test_5_remove_clears_inspector(t, ids)
    except Exception as e:
        t.check(f"Test 5 error: {e}", False)

    stop_all()


if __name__ == "__main__":
    run_suite(
        "Cart Layout Inspector Wiring",
        run_tests,
        layout="CartLayout",
    )
