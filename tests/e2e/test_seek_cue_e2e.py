#!/usr/bin/env python3
"""E2E tests for SeekCue.

Verifies that SeekCue correctly seeks its target MediaCue to the
specified position, handles edge cases (seek to zero, seek beyond
duration), and that properties round-trip through session save/load.

Run:
    poetry run python tests/e2e/test_seek_cue_e2e.py

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
)

SAVE_PATH = "/tmp/lisp_seek_cue_e2e_test.lsp"


# ── Poll helpers ───────────────────────────────────────────────

def _wait_for_count(expected, timeout=10.0):
    """Poll cue.list until expected count arrives or timeout."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        cues = call("cue.list")
        if len(cues) == expected:
            return cues
        time.sleep(0.4)
    return call("cue.list")


def _current_time_ms(cue_id):
    """Return current_time in ms for cue_id (from cue.state)."""
    return call("cue.state", {"id": cue_id})["current_time"]


# ── Tests ──────────────────────────────────────────────────────

def test_1_seek_while_playing(t, ids):
    """Seek while target is playing → current_time near target."""
    print("\n=== Test 1: Seek while target is playing ===")
    stop_all()

    A = ids["tone_A"]
    seek_target_ms = 5000

    # Start the target cue and let it play for a short while
    call("cue.execute", {"id": A, "action": "Start"})
    t.check("1: tone_A started", wait_state(A, "Running", timeout=5))

    # Add a SeekCue targeting tone_A at 5000 ms
    result = call("cue.add", {
        "type": "SeekCue",
        "properties": {
            "name": "Seek A to 5s",
            "target_id": A,
            "time": seek_target_ms,
        },
    })
    seek_id = result["id"]
    time.sleep(0.3)

    # Execute the SeekCue
    call("cue.execute", {"id": seek_id, "action": "Start"})
    time.sleep(0.4)

    pos = _current_time_ms(A)
    t.check(
        "1: current_time near 5000 ms (within 1000 ms)",
        abs(pos - seek_target_ms) <= 1000,
    )

    stop_all()
    call("cue.remove", {"id": seek_id})
    time.sleep(0.2)


def test_2_seek_to_zero(t, ids):
    """Seek to 0 → target rewinds to start."""
    print("\n=== Test 2: Seek to 0 rewinds target ===")
    stop_all()

    A = ids["tone_A"]

    # Start and advance past the beginning
    call("cue.execute", {"id": A, "action": "Start"})
    t.check("2: tone_A started", wait_state(A, "Running", timeout=5))
    # Advance to a known non-zero position
    call("cue.seek", {"id": A, "position": 4000})
    time.sleep(0.3)

    # Confirm we are past zero before seeking back
    pos_before = _current_time_ms(A)
    t.check("2: tone_A position > 0 before seek", pos_before > 0)

    # Create and execute a SeekCue that seeks to 0
    result = call("cue.add", {
        "type": "SeekCue",
        "properties": {
            "name": "Seek A to 0",
            "target_id": A,
            "time": 0,
        },
    })
    seek_id = result["id"]
    time.sleep(0.2)

    call("cue.execute", {"id": seek_id, "action": "Start"})
    time.sleep(0.4)

    pos_after = _current_time_ms(A)
    t.check(
        "2: current_time near 0 after seek (within 500 ms)",
        pos_after <= 500,
    )

    stop_all()
    call("cue.remove", {"id": seek_id})
    time.sleep(0.2)


def test_3_seek_beyond_duration(t, ids):
    """Seek beyond duration → no crash, cue completes cleanly."""
    print("\n=== Test 3: Seek beyond duration does not crash ===")
    stop_all()

    A = ids["tone_A"]

    # Start tone_A (8 s duration)
    call("cue.execute", {"id": A, "action": "Start"})
    t.check("3: tone_A started", wait_state(A, "Running", timeout=5))

    # Create SeekCue with a time well beyond the 8000 ms duration
    result = call("cue.add", {
        "type": "SeekCue",
        "properties": {
            "name": "Seek A beyond end",
            "target_id": A,
            "time": 9_999_999,
        },
    })
    seek_id = result["id"]
    time.sleep(0.2)

    # Execute — should not raise
    crashed = False
    try:
        call("cue.execute", {"id": seek_id, "action": "Start"})
        time.sleep(0.5)
    except Exception:
        crashed = True

    t.check("3: No crash seeking beyond duration", not crashed)

    stop_all()
    call("cue.remove", {"id": seek_id})
    time.sleep(0.2)


def test_4_save_load_preserves_properties(t, ids):
    """Save/load round-trip preserves target_id and time."""
    print("\n=== Test 4: Save/load preserves SeekCue properties ===")
    stop_all()

    A = ids["tone_A"]
    seek_ms = 3750

    # Create a SeekCue with known target_id and time
    result = call("cue.add", {
        "type": "SeekCue",
        "properties": {
            "name": "Seek Roundtrip",
            "target_id": A,
            "time": seek_ms,
        },
    })
    seek_id = result["id"]
    time.sleep(0.3)

    # Confirm properties before save
    t.check(
        "4: target_id set before save",
        cue_prop(seek_id, "target_id") == A,
    )
    t.check(
        "4: time set before save",
        cue_prop(seek_id, "time") == seek_ms,
    )

    # Save and reload the session (5 cues: 4 tones + 1 SeekCue)
    call("session.save", {"path": SAVE_PATH})
    call("session.load", {"path": SAVE_PATH})

    cues = _wait_for_count(5)
    t.check("4: 5 cues after reload", len(cues) == 5)

    reloaded = next(
        (c for c in cues if c["name"] == "Seek Roundtrip"),
        None,
    )
    t.check("4: SeekCue found after reload", reloaded is not None)
    if reloaded is None:
        return

    rid = reloaded["id"]
    t.check(
        "4: target_id preserved after reload",
        cue_prop(rid, "target_id") == A,
    )
    t.check(
        "4: time preserved after reload",
        cue_prop(rid, "time") == seek_ms,
    )


# ── Suite entry point ──────────────────────────────────────────

def run_tests(t):
    print("\nSetting up test cues...")
    ids = setup_with_tones()

    try:
        test_1_seek_while_playing(t, ids)
    except Exception as e:
        t.check(f"Test 1 error: {e}", False)

    try:
        test_2_seek_to_zero(t, ids)
    except Exception as e:
        t.check(f"Test 2 error: {e}", False)

    try:
        test_3_seek_beyond_duration(t, ids)
    except Exception as e:
        t.check(f"Test 3 error: {e}", False)

    try:
        test_4_save_load_preserves_properties(t, ids)
    except Exception as e:
        t.check(f"Test 4 error: {e}", False)

    stop_all()


if __name__ == "__main__":
    run_suite("SeekCue", run_tests)
