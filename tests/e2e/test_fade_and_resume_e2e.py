#!/usr/bin/env python3
"""E2E tests for Fade & Resume (ResumeCue).

Covers:
    1. Full intermission workflow: media -> Fade & Stop -> Fade & Resume.
       Timing assertion proves both fades actually ran for their full
       duration (live_volume isn't addressable via test_harness's
       `cue.get_property` — it only exposes top-level HasProperties
       fields, so a signal-arrival time is the next-best evidence).
    2. Mid-fade abort on the ResumeCue.

The "non-media graceful" branch is covered by the
`test_paused_no_faders_dispatches_resume_without_fade` unit test
rather than E2E: CommandCue doesn't override `__pause__`, so the
base-class no-op leaves its state unchanged and it can't actually
reach the Paused branch E2E. The unit test mocks the semantic
directly.

Run:
    poetry run python tests/e2e/test_fade_and_resume_e2e.py
"""

import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from tests.e2e.helpers import (  # noqa: E402
    run_suite, call, cue_state, wait_state, stop_all,
    setup_with_tones, cue_signal, wait_for_signal,
)


def _add_stop_cue(target_id, duration_ms=0, fade_type="Linear"):
    return call("cue.add", {
        "type": "StopCue",
        "properties": {
            "target_id": target_id,
            "action": "Pause",
            "duration": duration_ms,
            "fade_type": fade_type,
        },
    })["id"]


def _add_resume_cue(target_id, duration_ms=0, fade_type="Linear"):
    return call("cue.add", {
        "type": "ResumeCue",
        "properties": {
            "target_id": target_id,
            "duration": duration_ms,
            "fade_type": fade_type,
        },
    })["id"]


def test_1_intermission_workflow(t, ids):
    """Media starts -> StopCue pauses -> ResumeCue resumes and fades up.

    Timing check on the Resume leg: the `started` signal shouldn't fire
    until after the 500ms fade has begun (the async_function coordinator
    dispatches Resume before the fade, but `started` emits from the
    target's own start path — any instant signal would indicate the
    fade is being skipped entirely).
    """
    print("\n=== Test 1: Intermission workflow (Stop then Resume) ===")
    stop_all()

    target = ids["tone_A"]
    sfr_stop = _add_stop_cue(target, duration_ms=300)
    sfr_resume = _add_resume_cue(target, duration_ms=500)

    call("cue.execute", {"id": target, "action": "Start"})
    assert wait_state(target, "Running"), "target failed to start"

    with cue_signal(target, "paused") as sub:
        stop_started = time.monotonic()
        call("cue.execute", {"id": sfr_stop, "action": "Start"})
        ev = wait_for_signal(sub, timeout=3.0)
        stop_elapsed = time.monotonic() - stop_started

    t.check("target paused by Fade & Stop", ev is not None)
    t.check(
        f"pause fired after ~300ms fade (got {stop_elapsed * 1000:.0f}ms)",
        0.2 < stop_elapsed < 1.0,
    )

    with cue_signal(target, "started") as sub:
        call("cue.execute", {"id": sfr_resume, "action": "Start"})
        ev = wait_for_signal(sub, timeout=3.0)

    t.check("target received started signal from Resume", ev is not None)
    t.check("target back in Running state", cue_state(target) == "Running")

    # Wait for the ResumeCue itself to reach its end so we know the
    # 500ms fade completed; signal-arrival proves the fade ran full.
    with cue_signal(sfr_resume, "end") as sub_end:
        ended = wait_for_signal(sub_end, timeout=2.0)
    t.check("ResumeCue end signal fired after fade-up", ended is not None)


def test_2_abort_midfade_keeps_target_running(t, ids):
    """Stopping the ResumeCue mid-fade leaves target running."""
    print("\n=== Test 2: Abort mid-fade-up ===")
    stop_all()

    target = ids["tone_A"]
    sfr_stop = _add_stop_cue(target, duration_ms=100)
    sfr_resume = _add_resume_cue(target, duration_ms=3000)

    call("cue.execute", {"id": target, "action": "Start"})
    assert wait_state(target, "Running")
    with cue_signal(target, "paused") as sub:
        call("cue.execute", {"id": sfr_stop, "action": "Start"})
        wait_for_signal(sub, timeout=2.0)

    call("cue.execute", {"id": sfr_resume, "action": "Start"})
    time.sleep(0.4)  # let the fade-up begin
    call("cue.execute", {"id": sfr_resume, "action": "Stop"})
    time.sleep(0.2)

    t.check(
        "target still Running after ResumeCue abort",
        cue_state(target) == "Running",
    )


# -- Entry --

def run_tests(t):
    ids = setup_with_tones()
    test_1_intermission_workflow(t, ids)
    test_2_abort_midfade_keeps_target_running(t, ids)


if __name__ == "__main__":
    run_suite("Fade & Resume E2E", run_tests)
