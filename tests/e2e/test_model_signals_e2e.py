#!/usr/bin/env python3
"""E2E tests for CueModel signal fidelity.

Verifies that cue_model.item_added, cue_model.item_removed, and
cue_model.model_reset fire correctly and carry the right payloads,
and that per-cue 'started' signals still work after a session reload.

Run:
    poetry run python tests/e2e/test_model_signals_e2e.py

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
    AUDIO_DIR,
)

SAVE_PATH = "/tmp/lisp_model_signals_e2e_test.lsp"


# ── Helpers ────────────────────────────────────────────────────

def _wait_for_cue_count(expected, timeout=10.0):
    """Poll cue.list until count matches or timeout."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        cues = call("cue.list")
        if len(cues) == expected:
            return cues
        time.sleep(0.3)
    return call("cue.list")


# ── Tests ──────────────────────────────────────────────────────

def test_1_item_added_fires_on_cue_add(t):
    """cue.add → cue_model.item_added fires with the correct cue ID."""
    print("\n=== Test 1: item_added fires on cue.add ===")

    clear_cues()

    # Subscribe before triggering the event
    sub = call("signals.subscribe", {"signal": "cue_model.item_added"})
    sub_id = sub["subscription_id"]

    try:
        result = call("cue.add", {
            "type": "StopAll",
            "properties": {"name": "Signal Test Cue"},
        })
        added_id = result["id"]

        # wait_for blocks until the signal arrives or raises RuntimeError
        resp = call("signals.wait_for", {
            "subscription_id": sub_id,
            "timeout": 5.0,
        })
        event = resp.get("event") if resp else None

        t.check("1: item_added event received", event is not None)
        if event is None:
            return

        args = event.get("args", [])
        t.check("1: event has args", len(args) > 0)
        if not args:
            return

        cue_dict = args[0]
        t.check(
            "1: event carries correct cue ID",
            isinstance(cue_dict, dict)
            and cue_dict.get("id") == added_id,
        )
    finally:
        call("signals.unsubscribe", {"subscription_id": sub_id})


def test_2_item_removed_fires_on_cue_remove(t):
    """cue.remove → cue_model.item_removed fires with the correct cue ID."""
    print("\n=== Test 2: item_removed fires on cue.remove ===")

    clear_cues()

    # Add a cue to remove
    result = call("cue.add", {
        "type": "StopAll",
        "properties": {"name": "To Remove"},
    })
    target_id = result["id"]
    time.sleep(0.3)

    sub = call("signals.subscribe", {"signal": "cue_model.item_removed"})
    sub_id = sub["subscription_id"]

    try:
        call("cue.remove", {"id": target_id})

        resp = call("signals.wait_for", {
            "subscription_id": sub_id,
            "timeout": 5.0,
        })
        event = resp.get("event") if resp else None

        t.check("2: item_removed event received", event is not None)
        if event is None:
            return

        args = event.get("args", [])
        t.check("2: event has args", len(args) > 0)
        if not args:
            return

        cue_dict = args[0]
        t.check(
            "2: event carries correct cue ID",
            isinstance(cue_dict, dict)
            and cue_dict.get("id") == target_id,
        )
    finally:
        call("signals.unsubscribe", {"subscription_id": sub_id})


def test_3_bulk_add_emits_four_item_added(t):
    """Bulk add of 4 files → 4 item_added events arrive."""
    print("\n=== Test 3: bulk add emits 4 item_added events ===")

    clear_cues()

    sub = call("signals.subscribe", {"signal": "cue_model.item_added"})
    sub_id = sub["subscription_id"]

    try:
        call("cue.add_from_uri", {"files": [
            os.path.join(AUDIO_DIR, "tone_A.wav"),
            os.path.join(AUDIO_DIR, "tone_B.wav"),
            os.path.join(AUDIO_DIR, "tone_C.wav"),
            os.path.join(AUDIO_DIR, "tone_D.wav"),
        ]})

        # Wait for all 4 cues to appear in the model
        _wait_for_cue_count(4, timeout=10.0)

        # Poll without blocking — all events should be buffered by now
        result = call("signals.poll", {"subscription_id": sub_id})
        events = result.get("events", [])

        t.check(
            "3: 4 item_added events received",
            len(events) == 4,
        )
        # All events should carry a cue ID
        ids_in_events = [
            e["args"][0]["id"]
            for e in events
            if e.get("args") and isinstance(e["args"][0], dict)
        ]
        t.check(
            "3: all events carry a cue ID",
            len(ids_in_events) == 4,
        )
        t.check(
            "3: all event cue IDs are unique",
            len(set(ids_in_events)) == 4,
        )
    finally:
        call("signals.unsubscribe", {"subscription_id": sub_id})


def test_4_session_load_fires_model_reset_then_item_added(t):
    """session.load → model_reset fires, then item_added per restored cue."""
    print("\n=== Test 4: session.load fires model_reset + item_added ===")

    # Set up 4 cues and save
    setup_with_tones()
    call("session.save", {"path": SAVE_PATH})

    sub_reset = call("signals.subscribe", {
        "signal": "cue_model.model_reset",
    })
    sub_added = call("signals.subscribe", {
        "signal": "cue_model.item_added",
    })

    try:
        call("session.load", {"path": SAVE_PATH})

        # Wait for model_reset first
        resp_reset = call("signals.wait_for", {
            "subscription_id": sub_reset["subscription_id"],
            "timeout": 10.0,
        })
        reset_event = resp_reset.get("event") if resp_reset else None
        t.check("4: model_reset fired on load", reset_event is not None)

        # Wait for all 4 cues to be restored
        _wait_for_cue_count(4, timeout=10.0)

        # Poll item_added — should have 4 events
        result = call("signals.poll", {
            "subscription_id": sub_added["subscription_id"],
        })
        added_events = result.get("events", [])

        t.check(
            "4: 4 item_added events after reload",
            len(added_events) == 4,
        )
    finally:
        call("signals.unsubscribe", {
            "subscription_id": sub_reset["subscription_id"],
        })
        call("signals.unsubscribe", {
            "subscription_id": sub_added["subscription_id"],
        })


def test_5_started_signal_works_after_reload(t):
    """After reload, starting a cue emits the 'started' per-cue signal."""
    print("\n=== Test 5: per-cue started signal works after reload ===")

    # Ensure saved session exists from test 4; re-save to be safe
    setup_with_tones()
    call("session.save", {"path": SAVE_PATH})

    # Reload the session
    call("session.load", {"path": SAVE_PATH})
    cues = _wait_for_cue_count(4, timeout=10.0)
    t.check("5 precond: 4 cues after reload", len(cues) == 4)
    if len(cues) != 4:
        return

    # Pick the first cue (sorted by index)
    cues_sorted = sorted(cues, key=lambda c: c["index"])
    cue_id = cues_sorted[0]["id"]

    # Subscribe to the per-cue 'started' signal
    sub = call("signals.subscribe", {
        "signal": "cue.started",
        "cue_id": cue_id,
    })
    sub_id = sub["subscription_id"]

    try:
        call("cue.execute", {"id": cue_id, "action": "Start"})

        resp = call("signals.wait_for", {
            "subscription_id": sub_id,
            "timeout": 5.0,
        })
        event = resp.get("event") if resp else None

        t.check(
            "5: started signal fires after reload",
            event is not None,
        )
        if event is None:
            return

        # The signal path should reference the cue
        signal_path = event.get("signal", "")
        t.check(
            "5: signal path contains cue_id",
            cue_id in signal_path,
        )

        t.check(
            "5: cue is Running after start",
            wait_state(cue_id, "Running", timeout=5),
        )
    finally:
        call("signals.unsubscribe", {"subscription_id": sub_id})
        stop_all()


# ── Suite entry point ──────────────────────────────────────────

def run_tests(t):
    try:
        test_1_item_added_fires_on_cue_add(t)
    except Exception as e:
        t.check(f"Test 1 error: {e}", False)

    try:
        test_2_item_removed_fires_on_cue_remove(t)
    except Exception as e:
        t.check(f"Test 2 error: {e}", False)

    try:
        test_3_bulk_add_emits_four_item_added(t)
    except Exception as e:
        t.check(f"Test 3 error: {e}", False)

    try:
        test_4_session_load_fires_model_reset_then_item_added(t)
    except Exception as e:
        t.check(f"Test 4 error: {e}", False)

    try:
        test_5_started_signal_works_after_reload(t)
    except Exception as e:
        t.check(f"Test 5 error: {e}", False)

    stop_all()


if __name__ == "__main__":
    run_suite("Model Signals", run_tests)
