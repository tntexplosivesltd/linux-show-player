#!/usr/bin/env python3
"""E2E tests for CommandCue.

Tests shell command execution: success, failure with error
propagation, failure suppressed by no_error, and stop mid-run.

Run:
    poetry run python tests/e2e/test_command_cue_e2e.py

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
    clear_cues,
)


# ── Tests ─────────────────────────────────────────────────────


def test_1_successful_command(t):
    """echo hello runs to completion: Running → Stop (success)."""
    print("\n=== Test 1: Successful command (echo hello) → Stop ===")
    clear_cues()

    result = call("cue.add", {
        "type": "CommandCue",
        "properties": {
            "name": "Echo Hello",
            "command": "echo hello",
            "no_output": True,
            "no_error": False,
        },
    })
    cue_id = result["id"]
    time.sleep(0.2)

    call("cue.execute", {"id": cue_id, "action": "Start"})

    # Command completes quickly; wait for Stop state
    reached_stop = wait_state(cue_id, "Stop", timeout=5.0)
    t.check("1: cue reaches Stop after echo hello", reached_stop)
    t.check("1: state is Stop (not Error)",
            cue_state(cue_id) == "Stop")


def test_2_failing_command_no_error_false(t):
    """false exits non-zero with no_error=False → state=Error."""
    print("\n=== Test 2: Failing command with no_error=False → Error ===")
    clear_cues()

    result = call("cue.add", {
        "type": "CommandCue",
        "properties": {
            "name": "False No Error False",
            "command": "false",
            "no_output": True,
            "no_error": False,
        },
    })
    cue_id = result["id"]
    time.sleep(0.2)

    call("cue.execute", {"id": cue_id, "action": "Start"})

    # false exits immediately with code 1; wait for Error state
    reached_error = wait_state(cue_id, "Error", timeout=5.0)
    t.check("2: cue reaches Error after false", reached_error)
    t.check("2: state is Error (not Stop)",
            cue_state(cue_id) == "Error")


def test_3_failing_command_no_error_true(t):
    """false with no_error=True suppresses error → state=Stop."""
    print("\n=== Test 3: Failing command with no_error=True → Stop ===")
    clear_cues()

    result = call("cue.add", {
        "type": "CommandCue",
        "properties": {
            "name": "False No Error True",
            "command": "false",
            "no_output": True,
            "no_error": True,
        },
    })
    cue_id = result["id"]
    time.sleep(0.2)

    call("cue.execute", {"id": cue_id, "action": "Start"})

    # false exits immediately; no_error=True → Stop, not Error
    reached_stop = wait_state(cue_id, "Stop", timeout=5.0)
    t.check("3: cue reaches Stop after false (no_error=True)",
            reached_stop)
    t.check("3: state is Stop (not Error)",
            cue_state(cue_id) == "Stop")


def test_4_stop_mid_execution(t):
    """sleep 30 is stopped mid-run → cue terminates cleanly."""
    print("\n=== Test 4: Stop mid-execution (sleep 30) → Stop ===")
    clear_cues()

    result = call("cue.add", {
        "type": "CommandCue",
        "properties": {
            "name": "Long Sleep",
            "command": "sleep 30",
            "no_output": True,
            "no_error": True,
        },
    })
    cue_id = result["id"]
    time.sleep(0.2)

    call("cue.execute", {"id": cue_id, "action": "Start"})

    # Give the subprocess a moment to actually start
    time.sleep(0.5)
    t.check("4: cue is Running before stop",
            cue_state(cue_id) == "Running")

    # Stop the cue mid-run
    call("cue.execute", {"id": cue_id, "action": "Stop"})

    # Cue should terminate promptly after stop
    reached_stop = wait_state(cue_id, "Stop", timeout=5.0)
    t.check("4: cue reaches Stop after mid-run stop", reached_stop)
    t.check("4: state is Stop (not Error)",
            cue_state(cue_id) == "Stop")


# ── Entry point ───────────────────────────────────────────────


def run_tests(t):
    test_1_successful_command(t)
    test_2_failing_command_no_error_false(t)
    test_3_failing_command_no_error_true(t)
    test_4_stop_mid_execution(t)


if __name__ == "__main__":
    run_suite("CommandCue", run_tests)
