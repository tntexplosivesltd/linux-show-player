#!/usr/bin/env python3
"""E2E tests for Fade & Stop (StopCue).

Covers:
    1. Instant dispatch when duration=0 on a running target.
    2. Fade then pause on a single MediaCue target.
    3. Fade then stop on a parallel GroupCue (cascade works).
    4. Non-media target (no fader) still receives the action after 0ms.
    5. Abort mid-fade via Stop on the StopCue itself (target stays running).

Run:
    poetry run python tests/e2e/test_fade_and_stop_e2e.py
"""

import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from tests.e2e.helpers import (  # noqa: E402
    run_suite, call, cue_state, cue_prop, wait_state, stop_all,
    setup_with_tones, cue_signal, wait_for_signal,
)


def _add_stop_cue(target_id, action="Stop", duration_ms=0, fade_type="Linear"):
    """Create a StopCue; return its id."""
    return call("cue.add", {
        "type": "StopCue",
        "properties": {
            "target_id": target_id,
            "action": action,
            "duration": duration_ms,
            "fade_type": fade_type,
        },
    })["id"]


def test_1_instant_stop(t, ids):
    """duration=0: StopCue dispatches Stop to a running target immediately."""
    print("\n=== Test 1: Instant stop (duration=0) ===")
    stop_all()

    target = ids["tone_A"]
    sfr = _add_stop_cue(target, action="Stop", duration_ms=0)

    call("cue.execute", {"id": target, "action": "Start"})
    assert wait_state(target, "Running"), "target failed to start"

    with cue_signal(target, "stopped") as sub:
        call("cue.execute", {"id": sfr, "action": "Start"})
        ev = wait_for_signal(sub, timeout=3.0)

    t.check("target received stopped signal", ev is not None)
    t.check("target is Stop state", cue_state(target) == "Stop")


def test_2_fade_then_pause(t, ids):
    """duration=500ms + action=Pause: target pauses after the fade runs.

    Timing assertion proves the fade actually ran — if StopCue skipped
    the fade and dispatched Pause immediately, the signal would fire in
    well under the 500ms duration.
    """
    print("\n=== Test 2: Fade 500ms then Pause ===")
    stop_all()

    target = ids["tone_A"]
    sfr = _add_stop_cue(target, action="Pause", duration_ms=500)

    call("cue.execute", {"id": target, "action": "Start"})
    assert wait_state(target, "Running")

    with cue_signal(target, "paused") as sub:
        start = time.monotonic()
        call("cue.execute", {"id": sfr, "action": "Start"})
        ev = wait_for_signal(sub, timeout=3.0)
        elapsed = time.monotonic() - start

    t.check("target received paused signal", ev is not None)
    t.check("target is Pause state", cue_state(target) == "Pause")
    t.check(
        f"pause fired after fade duration (got {elapsed * 1000:.0f}ms)",
        0.4 < elapsed < 1.5,
    )


def test_3_group_fan_out(t, ids):
    """StopCue on a parallel GroupCue stops every running child."""
    print("\n=== Test 3: Group fan-out ===")
    stop_all()

    a, b = ids["tone_A"], ids["tone_B"]
    call("layout.select_cues", {"indices": [0, 1]})
    call("layout.context_action", {
        "action": "Group selected",
        "cue_ids": [a, b],
    })
    cues = call("cue.list")
    group = next(c for c in cues if c["_type_"] == "GroupCue")
    group_id = group["id"]

    sfr = _add_stop_cue(group_id, action="Stop", duration_ms=400)

    call("cue.execute", {"id": group_id, "action": "Start"})
    assert wait_state(a, "Running") and wait_state(b, "Running"), \
        "group children failed to start"

    with cue_signal(a, "stopped") as sub_a, \
         cue_signal(b, "stopped") as sub_b:
        call("cue.execute", {"id": sfr, "action": "Start"})
        ev_a = wait_for_signal(sub_a, timeout=3.0)
        ev_b = wait_for_signal(sub_b, timeout=3.0)

    t.check("child A stopped", ev_a is not None)
    t.check("child B stopped", ev_b is not None)


def test_4_abort_midfade(t, ids):
    """Stopping the StopCue mid-fade leaves target running."""
    print("\n=== Test 4: Abort mid-fade ===")
    stop_all()

    target = ids["tone_A"]
    sfr = _add_stop_cue(target, action="Stop", duration_ms=3000)

    call("cue.execute", {"id": target, "action": "Start"})
    assert wait_state(target, "Running")

    call("cue.execute", {"id": sfr, "action": "Start"})
    time.sleep(0.3)  # let the fade begin
    call("cue.execute", {"id": sfr, "action": "Stop"})
    time.sleep(0.2)

    t.check(
        "target still Running after SFR abort",
        cue_state(target) == "Running",
    )


def test_5_non_media_target_graceful(t, ids):
    """StopCue on a target without faders still dispatches the action."""
    print("\n=== Test 5: Non-media target ===")
    stop_all()

    cmd = call("cue.add", {
        "type": "CommandCue",
        "properties": {"command": "true", "no_output": True},
    })["id"]
    sfr = _add_stop_cue(cmd, action="Stop", duration_ms=200)

    with cue_signal(sfr, "end") as sub_end:
        call("cue.execute", {"id": sfr, "action": "Start"})
        ev = wait_for_signal(sub_end, timeout=2.0)

    t.check("StopCue itself ended cleanly on non-media target", ev is not None)


# -- Entry --

def run_tests(t):
    ids = setup_with_tones()
    test_1_instant_stop(t, ids)
    test_2_fade_then_pause(t, ids)
    test_3_group_fan_out(t, ids)
    test_4_abort_midfade(t, ids)
    test_5_non_media_target_graceful(t, ids)


if __name__ == "__main__":
    run_suite("Fade & Stop E2E", run_tests)
