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

    # --- Fade & Resume clears the hibernation bit
    call("layout.stop_all")
    time.sleep(0.3)

    resume_cue = call("cue.add", {
        "type": "ResumeCue",
        "properties": {
            "name": "Fade & Resume tone_A",
            "target_id": tone_a,
            "duration": 200,
        },
    })
    resume_id = resume_cue["id"]
    t.check("ResumeCue added", resume_id is not None)

    # Play → Hibernate → Fade & Resume
    with cue_signal(tone_a, "started") as sub:
        call("cue.start", {"id": tone_a})
        wait_for_signal(sub, timeout=3.0)
    with cue_signal(tone_a, "paused") as sub:
        call("cue.start", {"id": stop_id})
        wait_for_signal(sub, timeout=5.0)
    state_name = _wait_for_state(
        tone_a, lambda s: "Hibernating" in s,
    )
    t.check(
        "hibernated before Fade & Resume",
        "Hibernating" in state_name,
    )

    with cue_signal(tone_a, "started") as sub:
        call("cue.start", {"id": resume_id})
        wait_for_signal(sub, timeout=5.0)
    state_name = _wait_for_state(
        tone_a, lambda s: "Hibernating" not in s,
    )
    t.check(
        f"Fade & Resume cleared Hibernating (got {state_name!r})",
        "Hibernating" not in state_name,
    )
    t.check(
        "Fade & Resume restored Running",
        "Running" in state_name,
    )

    # --- Multiple StopCues targeting the same cue are idempotent
    call("layout.stop_all")
    time.sleep(0.3)
    stop_cue_b = call("cue.add", {
        "type": "StopCue",
        "properties": {
            "name": "Hibernate tone_A (dup)",
            "target_id": tone_a,
            "action": "Hibernate",
            "duration": 0,  # instant — no fade
        },
    })
    stop_id_b = stop_cue_b["id"]

    with cue_signal(tone_a, "started") as sub:
        call("cue.start", {"id": tone_a})
        wait_for_signal(sub, timeout=3.0)
    # Fire the first StopCue, wait for pause.
    with cue_signal(tone_a, "paused") as sub:
        call("cue.start", {"id": stop_id})
        wait_for_signal(sub, timeout=5.0)
    _wait_for_state(tone_a, lambda s: "Hibernating" in s)
    # Now fire the second (already-hibernated target). Should be a
    # no-op — second StopCue's paused-dispatch is blocked because
    # the target is already paused.
    call("cue.start", {"id": stop_id_b})
    time.sleep(0.3)
    state_name = call("cue.state", {"id": tone_a})["state_name"]
    t.check(
        f"second StopCue idempotent (got {state_name!r})",
        "Hibernating" in state_name and "Pause" in state_name,
    )
    call("cue.remove", {"id": stop_id_b})

    # --- GroupCue cascade: hibernating a group cascades to children
    call("layout.stop_all")
    time.sleep(0.3)
    # Wake tone_A so subsequent scenarios start fresh.
    call("cue.start", {"id": tone_a})
    time.sleep(0.2)
    call("layout.stop_all")
    time.sleep(0.3)

    # Select tone_A + tone_B and group them.
    tone_b = ids["tone_B"]
    call("layout.selection_mode", {"enable": True})
    call("layout.select_cues", {"indices": [0, 1]})
    call("layout.context_action", {
        "action": "Group selected",
        "cue_ids": [tone_a, tone_b],
    })
    time.sleep(0.5)
    # The group cue is the new first entry; its children follow.
    cues = call("cue.list")
    group_id = None
    for c in cues:
        if c["_type_"] == "GroupCue":
            group_id = c["id"]
            break
    t.check("GroupCue created", group_id is not None)

    # StopCue targeting the group with action=Hibernate.
    group_stop = call("cue.add", {
        "type": "StopCue",
        "properties": {
            "name": "Hibernate group",
            "target_id": group_id,
            "action": "Hibernate",
            "duration": 0,
        },
    })
    group_stop_id = group_stop["id"]

    # Start the group (parallel mode default → both children run).
    call("cue.start", {"id": group_id})
    time.sleep(0.5)

    # Hibernate the group.
    call("cue.start", {"id": group_stop_id})
    time.sleep(0.5)

    group_state = call("cue.state", {"id": group_id})["state_name"]
    a_state = call("cue.state", {"id": tone_a})["state_name"]
    b_state = call("cue.state", {"id": tone_b})["state_name"]
    t.check(
        f"group hibernating (got {group_state!r})",
        "Hibernating" in group_state,
    )
    t.check(
        f"child tone_A hibernating (got {a_state!r})",
        "Hibernating" in a_state,
    )
    t.check(
        f"child tone_B hibernating (got {b_state!r})",
        "Hibernating" in b_state,
    )

    # Resume only tone_A → its bit clears, tone_B stays hibernating.
    with cue_signal(tone_a, "started") as sub:
        call("cue.start", {"id": tone_a})
        wait_for_signal(sub, timeout=3.0)
    time.sleep(0.2)
    a_state = call("cue.state", {"id": tone_a})["state_name"]
    b_state = call("cue.state", {"id": tone_b})["state_name"]
    t.check(
        f"tone_A cleared on resume (got {a_state!r})",
        "Hibernating" not in a_state,
    )
    t.check(
        f"tone_B still hibernating (got {b_state!r})",
        "Hibernating" in b_state,
    )

    # --- Session save/load: hibernation is runtime-only
    call("layout.stop_all")
    time.sleep(0.3)

    with cue_signal(tone_a, "started") as sub:
        call("cue.start", {"id": tone_a})
        wait_for_signal(sub, timeout=3.0)
    with cue_signal(tone_a, "paused") as sub:
        call("cue.start", {"id": stop_id})
        wait_for_signal(sub, timeout=5.0)
    _wait_for_state(tone_a, lambda s: "Hibernating" in s)

    import tempfile
    save_path = tempfile.NamedTemporaryFile(
        suffix=".lsp", delete=False,
    ).name
    call("session.save", {"path": save_path})
    time.sleep(0.3)
    call("session.load", {"path": save_path})
    time.sleep(1.0)

    # After reload, cues are in Stopped state. Look up by name
    # because ids change on reload.
    cues_after = call("cue.list")
    tone_a_new = next(
        (c for c in cues_after if c["name"] == "tone_A"), None,
    )
    t.check("tone_A present after reload", tone_a_new is not None)
    if tone_a_new is not None:
        t.check(
            f"tone_A state is Stopped after reload "
            f"(got {tone_a_new['state_name']!r})",
            tone_a_new["state_name"] == "Stop",
        )
        t.check(
            "tone_A has no Hibernating bit after reload",
            "Hibernating" not in tone_a_new["state_name"],
        )

    import os
    try:
        os.unlink(save_path)
    except OSError:
        pass


if __name__ == "__main__":
    run_suite("Hibernation Workflow E2E", run_tests)
