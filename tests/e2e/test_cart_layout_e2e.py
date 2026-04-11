#!/usr/bin/env python3
"""E2E tests for Cart Layout basics.

Verifies that cues can be added to a CartLayout session, triggered
individually by ID, and that a save/load round-trip preserves them.

Run:
    poetry run python tests/e2e/test_cart_layout_e2e.py

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
    wait_state,
    stop_all,
    setup_with_tones,
)

SAVE_PATH = "/tmp/lisp_cart_layout_e2e.lsp"


# ── Poll helpers ───────────────────────────────────────────────


def _wait_for_count(expected, timeout=10.0):
    """Poll cue.list until expected count arrives or timeout."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        cues = call("cue.list")
        if len(cues) == expected:
            return cues
        time.sleep(0.5)
    return call("cue.list")


# ── Tests ──────────────────────────────────────────────────────


def test_1_cues_present_in_cart(t, ids):
    """Cues added via setup_with_tones appear in cue.list."""
    print("\n=== Test 1: Cues present in cart ===")

    cues = call("cue.list")
    t.check("1: 4 cues in cart", len(cues) == 4)


def test_2_execute_cue_by_id(t, ids):
    """A cue can be started and stopped individually by ID."""
    print("\n=== Test 2: Execute cue by ID ===")

    A = ids["tone_A"]

    call("cue.execute", {"id": A, "action": "Start"})
    t.check("2a: A running", wait_state(A, "Running"))

    call("cue.execute", {"id": A, "action": "Stop"})
    t.check("2b: A stopped", wait_state(A, "Stop"))


def test_3_save_load_roundtrip(t):
    """Session save/load round-trip preserves all cues."""
    print("\n=== Test 3: Save/load round-trip ===")

    call("session.save", {"path": SAVE_PATH})
    time.sleep(0.3)
    call("session.load", {"path": SAVE_PATH})

    loaded_cues = _wait_for_count(4)
    t.check("3: 4 cues after reload", len(loaded_cues) == 4)


# ── Suite entry point ──────────────────────────────────────────


def run_tests(t):
    print("\nSetting up test cues...")
    ids = setup_with_tones()

    try:
        test_1_cues_present_in_cart(t, ids)
    except Exception as e:
        t.check(f"Test 1 error: {e}", False)

    try:
        test_2_execute_cue_by_id(t, ids)
    except Exception as e:
        t.check(f"Test 2 error: {e}", False)

    try:
        test_3_save_load_roundtrip(t)
    except Exception as e:
        t.check(f"Test 3 error: {e}", False)

    stop_all()


if __name__ == "__main__":
    run_suite("Cart Layout Basics", run_tests, layout="CartLayout")
