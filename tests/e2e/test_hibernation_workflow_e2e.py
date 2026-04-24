"""E2E: full hibernation intermission workflow.

Covers:
1. Start a tone (Media cue).
2. Trigger a Fade & Stop (action=Hibernate) targeting the tone.
3. Assert the tone's state includes both Pause and Hibernating.
4. Resume the tone directly; assert Hibernating clears.
5. Mid-fade abort leaves the bit unset.
"""
import time

from tests.e2e.helpers import (
    call, cue_signal, run_suite, setup_with_tones, wait_for_signal,
)


def _wait_for_state(cue_id, predicate, timeout=2.0):
    """Poll cue.state until predicate(state_name) is True or timeout."""
    deadline = time.time() + timeout
    state_name = ""
    while time.time() < deadline:
        state_name = call(
            "cue.state", {"id": cue_id},
        )["state_name"]
        if predicate(state_name):
            return state_name
        time.sleep(0.1)
    return state_name


def run_tests(t):
    ids = setup_with_tones()
    tone_a = ids["tone_A"]

    # --- Add a Fade & Stop (Hibernate) targeting tone_A
    stop_cue = call("cue.add", {
        "type": "StopCue",
        "properties": {
            "name": "Hibernate tone_A",
            "target_id": tone_a,
            "action": "Hibernate",
            "duration": 300,
        },
    })
    stop_id = stop_cue["id"]
    t.check("StopCue added", stop_id is not None)

    # --- Start tone_A, confirm Running
    with cue_signal(tone_a, "started") as sub:
        call("cue.start", {"id": tone_a})
        ev = wait_for_signal(sub, timeout=3.0)
    t.check("tone_A started", ev is not None)
    t.check(
        "tone_A state is Running",
        "Running" in call(
            "cue.state", {"id": tone_a},
        )["state_name"],
    )

    # --- Trigger Hibernate; wait for paused
    with cue_signal(tone_a, "paused") as sub:
        call("cue.start", {"id": stop_id})
        ev = wait_for_signal(sub, timeout=5.0)
    t.check("tone_A paused after hibernate fade", ev is not None)

    state_name = _wait_for_state(
        tone_a, lambda s: "Hibernating" in s,
    )
    t.check(
        f"tone_A includes Hibernating (got {state_name!r})",
        "Hibernating" in state_name,
    )
    t.check(
        "tone_A includes Pause",
        "Pause" in state_name,
    )

    # --- Resume; bit must clear
    with cue_signal(tone_a, "started") as sub:
        # Cue.start() from Pause = resume (base class handling).
        call("cue.start", {"id": tone_a})
        ev = wait_for_signal(sub, timeout=3.0)
    t.check("tone_A resumed", ev is not None)

    state_name = _wait_for_state(
        tone_a, lambda s: "Hibernating" not in s,
    )
    t.check(
        f"Hibernating cleared on resume (got {state_name!r})",
        "Hibernating" not in state_name,
    )
    t.check(
        "tone_A state includes Running again",
        "Running" in state_name,
    )

    # --- Mid-fade abort must NOT set the bit
    call("layout.stop_all")
    time.sleep(0.3)

    with cue_signal(tone_a, "started") as sub:
        call("cue.start", {"id": tone_a})
        wait_for_signal(sub, timeout=3.0)

    call("cue.start", {"id": stop_id})
    time.sleep(0.05)  # well short of the 300ms fade
    call("cue.stop", {"id": stop_id})
    time.sleep(0.5)

    state_name = call("cue.state", {"id": tone_a})["state_name"]
    t.check(
        f"mid-abort did not hibernate (got {state_name!r})",
        "Hibernating" not in state_name,
    )


if __name__ == "__main__":
    run_suite("Hibernation Workflow E2E", run_tests)
