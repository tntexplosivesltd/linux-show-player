#!/usr/bin/env python3
"""E2E tests for VolumeControl cue.

Tests instant volume jump, fade-up while target is playing,
mid-fade interrupt, and save/load property round-trip.

Run:
    poetry run python tests/e2e/test_volume_control_e2e.py

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

SAVE_PATH = "/tmp/lisp_volume_control_e2e_test.lsp"


def _wait_for_vc(timeout=5.0):
    """Poll cue.list until a VolumeControl cue appears; return it or None."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        cues = call("cue.list")
        vc = next(
            (c for c in cues if c["_type_"] == "VolumeControl"),
            None,
        )
        if vc is not None:
            return vc
        time.sleep(0.2)
    return None


# ── Tests ──────────────────────────────────────────────────────


def test_1_instant_jump(t, ids):
    """duration=0: VolumeControl executes and ends immediately (→ Stop)."""
    print("\n=== Test 1: Instant volume jump (duration=0) ===")
    stop_all()

    A = ids["tone_A"]

    # Start the target cue so VolumeControl has a running media element
    call("cue.execute", {"id": A, "action": "Start"})
    t.check("1 precond: tone_A running", wait_state(A, "Running", timeout=5))

    vc_result = call("cue.add", {
        "type": "VolumeControl",
        "properties": {
            "name": "VC Instant",
            "target_id": A,
            "volume": 0.5,
            "duration": 0,
            "fade_type": "Linear",
        },
    })
    vc_id = vc_result["id"]
    time.sleep(0.3)

    call("cue.execute", {"id": vc_id, "action": "Start"})

    # With duration=0 the cue does a direct set and never enters Running;
    # it should reach Stop very quickly.
    reached_stop = wait_state(vc_id, "Stop", timeout=3)
    t.check("1: VolumeControl reaches Stop immediately", reached_stop)

    stop_all()


def test_2_fade_up_while_playing(t, ids):
    """duration>0: VolumeControl enters Running, then ends after duration."""
    print("\n=== Test 2: Fade-up while target is playing ===")
    stop_all()

    A = ids["tone_A"]

    # Start target with low volume so a fade-up is triggered
    call("cue.execute", {"id": A, "action": "Start"})
    t.check("2 precond: tone_A running", wait_state(A, "Running", timeout=5))

    # Set live_volume to 0 so the fade-up condition is met
    call("cue.set_property", {"id": A, "property": "volume", "value": 0.0})
    time.sleep(0.2)

    vc_result = call("cue.add", {
        "type": "VolumeControl",
        "properties": {
            "name": "VC Fade Up",
            "target_id": A,
            "volume": 0.8,
            "duration": 2000,
            "fade_type": "Linear",
        },
    })
    vc_id = vc_result["id"]
    time.sleep(0.3)

    call("cue.execute", {"id": vc_id, "action": "Start"})

    # Should enter Running while fading
    entered_running = wait_state(vc_id, "Running", timeout=3)
    t.check("2: VolumeControl enters Running during fade", entered_running)

    # After 2 s fade + margin, should complete and reach Stop
    reached_stop = wait_state(vc_id, "Stop", timeout=6)
    t.check("2: VolumeControl reaches Stop after fade completes", reached_stop)

    stop_all()


def test_3_interrupt_mid_fade(t, ids):
    """Interrupt mid-fade: VolumeControl stops and reaches Stop."""
    print("\n=== Test 3: Interrupt mid-fade ===")
    stop_all()

    A = ids["tone_A"]

    call("cue.execute", {"id": A, "action": "Start"})
    t.check("3 precond: tone_A running", wait_state(A, "Running", timeout=5))

    # Reset volume low so fade-up is triggered
    call("cue.set_property", {"id": A, "property": "volume", "value": 0.0})
    time.sleep(0.2)

    vc_result = call("cue.add", {
        "type": "VolumeControl",
        "properties": {
            "name": "VC Interrupt",
            "target_id": A,
            "volume": 0.8,
            "duration": 5000,
            "fade_type": "Linear",
        },
    })
    vc_id = vc_result["id"]
    time.sleep(0.3)

    call("cue.execute", {"id": vc_id, "action": "Start"})
    t.check(
        "3: VolumeControl enters Running",
        wait_state(vc_id, "Running", timeout=3),
    )

    # Interrupt mid-fade
    time.sleep(0.5)
    call("cue.execute", {"id": vc_id, "action": "Interrupt"})

    reached_stop = wait_state(vc_id, "Stop", timeout=3)
    t.check("3: VolumeControl reaches Stop after interrupt", reached_stop)

    stop_all()


def test_4_save_load_roundtrip(t, ids):
    """Save/load preserves target_id, volume, duration, fade_type."""
    print("\n=== Test 4: Save/load property round-trip ===")
    stop_all()

    A = ids["tone_A"]

    call("cue.add", {
        "type": "VolumeControl",
        "properties": {
            "name": "VC RoundTrip",
            "target_id": A,
            "volume": 0.65,
            "duration": 3000,
            "fade_type": "Quadratic",
        },
    })
    time.sleep(0.3)

    call("session.save", {"path": SAVE_PATH})
    call("session.load", {"path": SAVE_PATH})

    # Wait for VolumeControl to reappear after reload
    vc_after = _wait_for_vc(timeout=10)
    t.check("4: VolumeControl present after reload", vc_after is not None)
    if vc_after is None:
        return

    rid = vc_after["id"]

    t.check(
        "4: name preserved",
        cue_prop(rid, "name") == "VC RoundTrip",
    )
    # After reload the target tone cue has a new ID; find it by name
    reloaded_cues = call("cue.list")
    tone_a_after = next(
        (c for c in reloaded_cues if c["name"] == "tone_A"),
        None,
    )
    t.check("4: tone_A found after reload", tone_a_after is not None)
    if tone_a_after is not None:
        t.check(
            "4: target_id matches reloaded tone_A",
            cue_prop(rid, "target_id") == tone_a_after["id"],
        )

    t.check(
        "4: volume preserved",
        abs(cue_prop(rid, "volume") - 0.65) < 1e-6,
    )
    t.check(
        "4: duration preserved",
        cue_prop(rid, "duration") == 3000,
    )
    t.check(
        "4: fade_type preserved",
        cue_prop(rid, "fade_type") == "Quadratic",
    )


# ── Suite entry point ──────────────────────────────────────────


def run_tests(t):
    print("\nSetting up test cues...")
    ids = setup_with_tones()

    try:
        test_1_instant_jump(t, ids)
    except Exception as e:
        t.check(f"Test 1 error: {e}", False)

    # Re-setup to get clean cue list for each test
    ids = setup_with_tones()
    try:
        test_2_fade_up_while_playing(t, ids)
    except Exception as e:
        t.check(f"Test 2 error: {e}", False)

    ids = setup_with_tones()
    try:
        test_3_interrupt_mid_fade(t, ids)
    except Exception as e:
        t.check(f"Test 3 error: {e}", False)

    ids = setup_with_tones()
    try:
        test_4_save_load_roundtrip(t, ids)
    except Exception as e:
        t.check(f"Test 4 error: {e}", False)

    stop_all()


if __name__ == "__main__":
    run_suite("VolumeControl Cue", run_tests)
