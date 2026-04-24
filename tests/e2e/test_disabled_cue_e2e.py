#!/usr/bin/env python3
"""E2E tests for the disabled-cue feature.

Covers:
    - Individual disable blocks GO and direct cue.execute
    - Group cascade: disabling a group makes all children inert
    - Session persistence: `disabled` survives save + reload

Run:
    poetry run python tests/e2e/test_disabled_cue_e2e.py
"""

import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from tests.e2e.helpers import (
    call,
    clear_cues,
    cue_prop,
    cue_signal,
    run_suite,
    setup_with_tones,
    signal_sub,
    stop_all,
    start_lisp,
    stop_lisp,
    wait_for_signal,
)


def _set_disabled(cue_id, value):
    call("cue.set_property", {
        "id": cue_id, "property": "disabled", "value": value,
    })


def _tone_ids(tones):
    """tones is {name: id}; return a deterministic-ordered list."""
    return [tones[name] for name in sorted(tones.keys())]


def run_tests(t):
    # --- Scenario 1: individual disable blocks GO ---
    tones = setup_with_tones()
    ids = _tone_ids(tones)
    t.check("1a: four tones added", len(ids) == 4)

    _set_disabled(ids[0], True)
    t.check(
        "1b: disabled=True persisted on model",
        cue_prop(ids[0], "disabled") is True,
    )

    call("layout.set_standby_index", {"index": 0})
    # Subscribe BEFORE triggering so we don't miss events.
    with cue_signal(ids[0], "started") as sub0, \
            cue_signal(ids[1], "started") as sub1:
        call("layout.go")
        # The first GO on a disabled standby should skip to cue 1.
        event1 = wait_for_signal(sub1, timeout=3.0)
        t.check("1c: cue 1 (enabled) started via GO", event1 is not None)
        # Confirm disabled cue did NOT start.
        event0 = wait_for_signal(sub0, timeout=0.5)
        t.check("1d: cue 0 (disabled) did not start", event0 is None)

    stop_all()
    _set_disabled(ids[0], False)

    # --- Scenario 2: cue.execute directly on disabled cue ---
    _set_disabled(ids[0], True)
    with cue_signal(ids[0], "started") as sub0:
        call("cue.execute", {"id": ids[0]})
        event = wait_for_signal(sub0, timeout=0.5)
        t.check(
            "2: disabled cue does not start on direct cue.execute",
            event is None,
        )

    stop_all()
    _set_disabled(ids[0], False)

    # --- Scenario 3: group cascade ---
    # Group cues 0 and 1. Disable the group. Neither child fires.
    # Subscribe to cue_model.item_added BEFORE triggering the group
    # action, so the GroupCue appearance is observed via signal
    # rather than sleep (avoids silent-skip on a slow CI runner).
    with signal_sub("cue_model.item_added") as add_sub:
        call("layout.select_cues", {"indices": [0, 1]})
        call("layout.context_action", {
            "action": "Group selected",
            "cue_ids": [ids[0], ids[1]],
        })
        wait_for_signal(add_sub, timeout=3.0)

    cues_now = call("cue.list")
    group = next(
        (c for c in cues_now if c["_type_"] == "GroupCue"),
        None,
    )
    # Hard failure if the group didn't appear — otherwise the rest
    # of the scenario would silently pass on a vacuous `if group`
    # branch.
    if group is None:
        t.check("3a: GroupCue created", False)
        raise AssertionError("Grouping failed; can't run 3b–3d")
    t.check("3a: GroupCue created", True)

    group_id = group["id"]
    _set_disabled(group_id, True)

    with cue_signal(ids[0], "started") as sub0, \
            cue_signal(ids[1], "started") as sub1:
        call("cue.execute", {"id": group_id})
        e0 = wait_for_signal(sub0, timeout=0.7)
        e1 = wait_for_signal(sub1, timeout=0.1)
        t.check("3b: child 0 skipped (cascade)", e0 is None)
        t.check("3c: child 1 skipped (cascade)", e1 is None)

    # Re-enable the group and confirm children can fire again.
    _set_disabled(group_id, False)
    with cue_signal(ids[0], "started") as sub0:
        call("cue.execute", {"id": ids[0]})
        t.check(
            "3d: re-enabled group allows child to fire",
            wait_for_signal(sub0, timeout=2.0) is not None,
        )
    stop_all()

    # --- Scenario 4: undo/redo of the disabled toggle ---
    # Re-enable everything first for a clean slate.
    clear_cues()
    tones = setup_with_tones()
    ids = _tone_ids(tones)

    _set_disabled(ids[0], True)
    t.check(
        "4a: disabled set",
        cue_prop(ids[0], "disabled") is True,
    )
    call("commands.undo")
    time.sleep(0.2)
    t.check(
        "4b: undo reverts disabled to False",
        cue_prop(ids[0], "disabled") is False,
    )
    call("commands.redo")
    time.sleep(0.2)
    t.check(
        "4c: redo restores disabled True",
        cue_prop(ids[0], "disabled") is True,
    )
    _set_disabled(ids[0], False)

    # --- Scenario 5: next-action chain skips disabled follower ---
    # A has next_action=TriggerAfterEnd; B is disabled; C enabled.
    # Playing A should end naturally, chain should skip B, fire C.
    clear_cues()
    tones = setup_with_tones()
    ids = _tone_ids(tones)

    # Set chain on cue 0, disable cue 1.
    call("cue.set_property", {
        "id": ids[0], "property": "next_action",
        "value": "TriggerAfterEnd",
    })
    _set_disabled(ids[1], True)

    with cue_signal(ids[1], "started") as sub1, \
            cue_signal(ids[2], "started") as sub2:
        call("cue.execute", {"id": ids[0]})
        # Wait for cue 2 to start (via chain skip). Test tones
        # are 8s each (helpers.create_test_audio), so the chain
        # needs >8s to fire after natural end. Give plenty of
        # headroom for slow CI.
        event2 = wait_for_signal(sub2, timeout=15.0)
        t.check(
            "5a: chain skipped disabled cue and fired next enabled",
            event2 is not None,
        )
        # Disabled cue 1 must not have started at any point.
        event1 = wait_for_signal(sub1, timeout=0.2)
        t.check("5b: disabled cue 1 never started", event1 is None)
    stop_all()

    # --- Scenario 6: session persistence ---
    clear_cues()
    tones = setup_with_tones()
    ids = _tone_ids(tones)

    _set_disabled(ids[0], True)

    session_path = "/tmp/lisp_disabled_e2e_session.lsp"
    call("session.save", {"path": session_path})

    stop_lisp()
    start_lisp()
    call("session.load", {"path": session_path})
    time.sleep(1.0)

    reloaded = call("cue.list")
    # `cue.list` returns briefs; check the `disabled` property per id.
    disabled_ids = [
        c["id"] for c in reloaded
        if cue_prop(c["id"], "disabled") is True
    ]
    t.check(
        "6: exactly one disabled cue after reload",
        len(disabled_ids) == 1,
    )

    try:
        os.unlink(session_path)
    except OSError:
        pass


if __name__ == "__main__":
    run_suite("Disabled Cue", run_tests)
