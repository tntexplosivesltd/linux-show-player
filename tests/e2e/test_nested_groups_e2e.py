#!/usr/bin/env python3
"""E2E: nested GroupCues built via the harness 'Group selected'.

Builds outer-parallel containing [tone_A, inner-playlist[tone_B,
tone_C]] and confirms:
  - the second 'Group selected' invocation accepts a GroupCue
    in its selection
  - the resulting hierarchy has correct group_id chains
  - starting the outer group fires both branches (tone_A AND
    tone_B), and after tone_B ends, tone_C starts (playlist
    advance through nesting)
  - sessions roundtrip the nested structure intact

Run:
    poetry run python tests/e2e/test_nested_groups_e2e.py
"""
import time

from tests.e2e.helpers import (
    call,
    cue_prop,
    cue_signal,
    run_suite,
    setup_with_tones,
    stop_all,
    wait_for_signal,
)


def run_tests(t):
    cues = setup_with_tones()
    A, B, C = cues["tone_A"], cues["tone_B"], cues["tone_C"]

    # 1. Group [B, C] -> inner_group (playlist mode, looping)
    call("layout.context_action", {
        "action": "Group selected",
        "cue_ids": [B, C],
    })
    time.sleep(0.3)

    listing = call("cue.list")
    inner_group = next(
        c for c in listing if c["_type_"] == "GroupCue"
    )
    call("cue.set_property", {
        "id": inner_group["id"],
        "property": "group_mode",
        "value": "playlist",
    })
    call("cue.set_property", {
        "id": inner_group["id"],
        "property": "loop",
        "value": True,
    })

    # 2. Group [A, inner_group] -> outer_group (parallel mode)
    call("layout.context_action", {
        "action": "Group selected",
        "cue_ids": [A, inner_group["id"]],
    })
    time.sleep(0.3)

    listing = call("cue.list")
    outer_groups = [
        c for c in listing
        if c["_type_"] == "GroupCue" and c["id"] != inner_group["id"]
    ]
    t.check(
        "outer group created",
        len(outer_groups) == 1,
    )
    if not outer_groups:
        return
    outer_group = outer_groups[0]

    # 3. Verify hierarchy: A and inner_group are children of outer
    t.check(
        "A is child of outer_group",
        cue_prop(A, "group_id") == outer_group["id"],
    )
    t.check(
        "inner_group is child of outer_group",
        cue_prop(inner_group["id"], "group_id") == outer_group["id"],
    )
    t.check(
        "B is still child of inner_group",
        cue_prop(B, "group_id") == inner_group["id"],
    )

    # 4. Subscribe to A.started and B.started, then start outer
    with cue_signal(A, "started") as sub_a, \
         cue_signal(B, "started") as sub_b:
        call("cue.start", {"id": outer_group["id"]})
        ev_a = wait_for_signal(sub_a, timeout=5)
        ev_b = wait_for_signal(sub_b, timeout=5)
        t.check("A started via outer", ev_a is not None)
        t.check("B started via outer/inner", ev_b is not None)

    # 5. Wait for B to end and confirm C starts (playlist advance
    # through nesting)
    with cue_signal(C, "started") as sub_c:
        ev_c = wait_for_signal(sub_c, timeout=20)
        t.check("C started after B ended", ev_c is not None)

    stop_all()
    time.sleep(0.5)

    # 6. Roundtrip via session save/load
    save_path = "/tmp/lisp_nested_groups_roundtrip.lsp"
    call("session.save", {"path": save_path})
    call("session.load", {"path": save_path})
    time.sleep(0.5)

    listing = call("cue.list")
    outer_after = next(
        (c for c in listing if c["id"] == outer_group["id"]),
        None,
    )
    inner_after = next(
        (c for c in listing if c["id"] == inner_group["id"]),
        None,
    )
    t.check("outer survived roundtrip", outer_after is not None)
    t.check("inner survived roundtrip", inner_after is not None)
    if inner_after is not None:
        t.check(
            "inner.group_id still points at outer after reload",
            cue_prop(inner_group["id"], "group_id") == outer_group["id"],
        )

    # 7. Ungroup the inner group. B and C must remain under
    # outer_group, not be promoted to top-level (Phase 2 fix).
    call("layout.context_action", {
        "action": "Ungroup",
        "cue_ids": [inner_group["id"]],
    })
    time.sleep(0.3)

    t.check(
        "B promoted to outer (not top-level) after ungroup",
        cue_prop(B, "group_id") == outer_group["id"],
    )
    t.check(
        "C promoted to outer (not top-level) after ungroup",
        cue_prop(C, "group_id") == outer_group["id"],
    )
    inner_present = any(
        c["id"] == inner_group["id"] for c in call("cue.list")
    )
    t.check("inner_group dissolved by ungroup", not inner_present)

    # 8. Restore the nested structure from the on-disk save and
    # exercise the delete path: cue.remove on the inner group
    # must leave B and C inside outer_group (Phase 3 fix).
    call("session.load", {"path": save_path})
    time.sleep(0.5)

    t.check(
        "inner restored after reload (pre-delete)",
        cue_prop(inner_group["id"], "group_id") == outer_group["id"],
    )

    call("cue.remove", {"id": inner_group["id"]})
    time.sleep(0.3)

    t.check(
        "B retained outer parentage after inner deletion",
        cue_prop(B, "group_id") == outer_group["id"],
    )
    t.check(
        "C retained outer parentage after inner deletion",
        cue_prop(C, "group_id") == outer_group["id"],
    )
    inner_present_2 = any(
        c["id"] == inner_group["id"] for c in call("cue.list")
    )
    t.check(
        "inner_group removed by cue.remove",
        not inner_present_2,
    )


if __name__ == "__main__":
    run_suite("Nested Groups E2E", run_tests)
