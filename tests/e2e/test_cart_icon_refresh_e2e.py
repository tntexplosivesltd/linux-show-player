#!/usr/bin/env python3
"""E2E regression for live cart-cell icon refresh.

Cart cells used to ignore `cue.icon` property changes — the cell
stayed frozen on its launch-time icon until the session reloaded.
This suite drives icon changes through `cue.set_property` (which
emits the same `property_changed` signal that `UpdateCueCommand`
fires from the inspector and undo/redo) and asserts the rendered
QClickLabel icon updates without a session reload.

What this suite does NOT cover:

* The inspector's icon-picker modal (`IconSelectorDialog` opened
  by `cueIconButton`). The harness's `inspector.set_field` only
  drives line edits, spin boxes, sliders, checkable buttons, and
  combo boxes; the icon picker is a non-checkable button that
  opens a modal dialog. Verify that flow manually — open the
  inspector, click the icon button, choose a different icon, and
  confirm the cell updates without reload.
* Theme-switch invalidation (`IconTheme.set_theme_name(...)`) is
  also a manual path; switching themes mid-session must keep cart
  cells in sync.

Run:
    poetry run python tests/e2e/test_cart_icon_refresh_e2e.py
"""

import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from tests.e2e.helpers import (  # noqa: E402
    call,
    cue_prop,
    cue_signal,
    run_suite,
    setup_with_tones,
    stop_all,
    wait_for_signal,
)


def _icon_state(cue_id):
    return call("cart.cell_icon_state", {"cue_id": cue_id})


def _wait_icon_match(cue_id, *, timeout=2.0, poll=0.02):
    """Poll until the cart cell's rendered icon matches its cue.icon.

    Replaces a fragile sleep after `wait_for_signal`: the icon
    refresh runs on a `Connection.QtQueued` slot, which is posted
    AFTER `property_changed` returns to the test, so signal-wait
    alone doesn't guarantee the cell has been redrawn yet. Polling
    on the harness reader is both deterministic and quick — it
    settles within a single event-loop tick on healthy runs.
    """
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        last = _icon_state(cue_id)
        if last["matches"]:
            return last
        time.sleep(poll)
    return last


def _set_icon_and_wait(cue_id, value):
    """Drive cue.icon via property_changed and poll for cell refresh.

    Going through `cue.set_property` mirrors the path the inspector
    takes (UpdateCueCommand → property_changed).
    """
    with cue_signal(cue_id, "property_changed") as sub:
        call("cue.set_property", {
            "id": cue_id,
            "property": "icon",
            "value": value,
        })
        wait_for_signal(sub, timeout=2.0)
    _wait_icon_match(cue_id)


def test_1_initial_state_matches(t, ids):
    """The freshly-bound cart cell shows the right icon to begin with."""
    print("\n=== Test 1: initial state ===")

    A = ids["tone_A"]
    state = _icon_state(A)

    t.check(
        "1a: cell renders an icon at all",
        state["current_id"] is not None,
    )
    t.check(
        "1b: cell icon matches the cached icon for cue.icon",
        state["matches"] is True,
    )
    t.check(
        "1c: harness reports the cue's current icon name",
        state["icon_property"] == cue_prop(A, "icon"),
    )


def test_2_icon_change_refreshes_cell(t, ids):
    """Changing cue.icon updates the cell without a session reload."""
    print("\n=== Test 2: icon change refreshes cell ===")

    A = ids["tone_A"]
    B = ids["tone_B"]

    before = _icon_state(A)
    original_icon_name = before["icon_property"]
    sibling_before = _icon_state(B)

    # Pick a deliberately different icon. The action-cue palette
    # ships with `prompt`, `stop` etc. as -cart variants; pick one
    # that is guaranteed not to match the audio default.
    new_icon = (
        "prompt" if original_icon_name != "prompt" else "stop"
    )

    _set_icon_and_wait(A, new_icon)

    after = _icon_state(A)
    sibling_after = _icon_state(B)

    t.check(
        "2a: cue.icon property persisted",
        after["icon_property"] == new_icon,
    )
    t.check(
        "2b: cell icon identity changed after the property change",
        after["current_id"] != before["current_id"],
    )
    t.check(
        "2c: cell now matches the new cached icon",
        after["matches"] is True,
    )
    t.check(
        "2d: expected_id tracks the new icon, not the old one",
        after["expected_id"] != before["expected_id"],
    )
    # Multi-cue isolation: a single-cue icon change must not
    # disturb sibling cells.
    t.check(
        "2e: sibling cell's icon identity unchanged",
        sibling_after["current_id"] == sibling_before["current_id"],
    )
    t.check(
        "2f: sibling cell's icon property unchanged",
        sibling_after["icon_property"]
        == sibling_before["icon_property"],
    )


def test_3_undo_redo_round_trips_the_icon(t, ids):
    """Undo restores the previous icon; redo reapplies the new one."""
    print("\n=== Test 3: undo/redo round-trip ===")

    A = ids["tone_A"]

    # Re-anchor on a known starting icon AND clear the undo stack
    # so the next undo unambiguously reverts the change inside this
    # test. Without `commands.clear`, the undo would pop whatever
    # the previous test queued, making this assertion order-coupled.
    _set_icon_and_wait(A, "speaker")
    call("commands.clear")
    baseline = _icon_state(A)

    _set_icon_and_wait(A, "prompt")
    after_change = _icon_state(A)
    t.check(
        "3a: cell tracked the change",
        after_change["matches"] is True
        and after_change["current_id"] != baseline["current_id"],
    )

    with cue_signal(A, "property_changed") as sub:
        call("commands.undo")
        wait_for_signal(sub, timeout=2.0)
    _wait_icon_match(A)

    after_undo = _icon_state(A)
    t.check(
        "3b: undo restored the original icon name",
        after_undo["icon_property"] == "speaker",
    )
    t.check(
        "3c: cell icon matches the restored cached icon",
        after_undo["matches"] is True
        and after_undo["current_id"] == baseline["current_id"],
    )

    with cue_signal(A, "property_changed") as sub:
        call("commands.redo")
        wait_for_signal(sub, timeout=2.0)
    _wait_icon_match(A)

    after_redo = _icon_state(A)
    t.check(
        "3d: redo reapplied the new icon",
        after_redo["icon_property"] == "prompt"
        and after_redo["current_id"] == after_change["current_id"]
        and after_redo["matches"] is True,
    )


def run_tests(t):
    print("\nSetting up test cues...")
    ids = setup_with_tones()

    try:
        test_1_initial_state_matches(t, ids)
    except Exception as e:
        t.check(f"Test 1 error: {e}", False)

    try:
        test_2_icon_change_refreshes_cell(t, ids)
    except Exception as e:
        t.check(f"Test 2 error: {e}", False)

    try:
        test_3_undo_redo_round_trips_the_icon(t, ids)
    except Exception as e:
        t.check(f"Test 3 error: {e}", False)

    stop_all()


if __name__ == "__main__":
    run_suite(
        "Cart Cell Icon Refresh",
        run_tests,
        layout="CartLayout",
    )
