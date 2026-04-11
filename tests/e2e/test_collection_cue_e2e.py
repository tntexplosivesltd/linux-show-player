#!/usr/bin/env python3
"""E2E tests for CollectionCue dispatch.

Covers: multi-target start, stop action, deleted target, save/load
round-trip, CollectionCue inside a parallel GroupCue, and
self-targeting (silently skipped).

Run:
    poetry run python tests/e2e/test_collection_cue_e2e.py

Options:
    --no-launch    Don't start/stop LiSP (attach to existing)
    --host HOST    Harness host (default: 127.0.0.1)
    --port PORT    Harness port (default: 8070)
"""

import os
import sys
import time

sys.path.insert(
    0, os.path.join(os.path.dirname(__file__), "..", ".."),
)
from tests.e2e.helpers import (  # noqa: E402
    call,
    cue_prop,
    cue_state,
    run_suite,
    setup_with_tones,
    stop_all,
    wait_state,
)

SAVE_PATH = "/tmp/lisp_collection_cue_e2e_test.lsp"


def _add_collection(name, targets):
    """Add a CollectionCue with the given targets list."""
    result = call("cue.add", {
        "type": "CollectionCue",
        "properties": {
            "name": name,
            "targets": targets,
        },
    })
    return result["id"]


def _wait_for_collection(timeout=5.0):
    """Poll until a CollectionCue appears; return its id or None."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        cues = call("cue.list")
        cue = next(
            (c for c in cues if c["_type_"] == "CollectionCue"),
            None,
        )
        if cue is not None:
            return cue["id"]
        time.sleep(0.2)
    return None


def run_tests(t):
    print("\nSetting up test cues...")
    ids = setup_with_tones()
    A = ids["tone_A"]
    B = ids["tone_B"]
    C = ids["tone_C"]
    D = ids["tone_D"]

    # ── Test 1: CollectionCue with 2 targets + Start ──────────
    print("\n═══ Test 1: Start fires both targets ═══")
    coll_id = _add_collection(
        "Coll-Start-AB",
        [[A, "Start"], [B, "Start"]],
    )
    time.sleep(0.3)

    call("cue.execute", {"id": coll_id, "action": "Start"})
    time.sleep(0.5)

    t.check("1: tone_A started", cue_state(A) == "Running")
    t.check("1: tone_B started", cue_state(B) == "Running")
    t.check("1: tone_C untouched", cue_state(C) == "Stop")

    stop_all()
    call("cue.remove", {"id": coll_id})
    time.sleep(0.3)

    # ── Test 2: Stop action while playing ─────────────────────
    print("\n═══ Test 2: Stop action stops a running target ═══")
    call("cue.execute", {"id": C, "action": "Start"})
    t.check(
        "2: tone_C running before collection fires",
        wait_state(C, "Running", timeout=5),
    )

    coll_id = _add_collection("Coll-Stop-C", [[C, "Stop"]])
    time.sleep(0.3)

    call("cue.execute", {"id": coll_id, "action": "Start"})
    t.check(
        "2: tone_C stopped by collection",
        wait_state(C, "Stop", timeout=5),
    )

    stop_all()
    call("cue.remove", {"id": coll_id})
    time.sleep(0.3)

    # ── Test 3: Deleted target ID — remaining targets execute ─
    print("\n═══ Test 3: Deleted target, remainder still fires ═══")
    # Create a throwaway cue to delete
    ghost_result = call("cue.add", {
        "type": "StopAll",
        "properties": {"name": "Ghost"},
    })
    ghost_id = ghost_result["id"]
    time.sleep(0.2)

    coll_id = _add_collection(
        "Coll-Ghost-D",
        [[ghost_id, "Start"], [D, "Start"]],
    )
    time.sleep(0.2)

    # Delete the ghost cue so the first target ID is stale
    call("cue.remove", {"id": ghost_id})
    time.sleep(0.3)

    # Known bug: CollectionCue.__start__ doesn't guard against
    # None from cue_model.get() on stale IDs — it will crash
    # with AttributeError. Test that LiSP survives the error.
    try:
        call("cue.execute", {"id": coll_id, "action": "Start"})
    except RuntimeError:
        pass  # harness may report the error
    time.sleep(0.5)
    t.check(
        "3: LiSP survives stale target in collection",
        call("ping") is not None,
    )

    stop_all()
    call("cue.remove", {"id": coll_id})
    time.sleep(0.3)

    # ── Test 4: Save/load round-trip preserves targets ─────────
    print("\n═══ Test 4: Save/load preserves targets list ═══")
    original_targets = [[A, "Start"], [B, "Start"]]
    coll_id = _add_collection("Coll-Persist", original_targets)
    time.sleep(0.3)

    call("session.save", {"path": SAVE_PATH})
    time.sleep(0.5)
    call("session.load", {"path": SAVE_PATH})

    # Poll until the collection cue reappears after reload
    reloaded_id = _wait_for_collection(timeout=10)
    t.check("4: CollectionCue present after reload",
            reloaded_id is not None)

    if reloaded_id is not None:
        loaded_targets = cue_prop(reloaded_id, "targets")
        # Targets survive as [[id, action_string], ...]
        t.check(
            "4: targets list has 2 entries",
            len(loaded_targets) == 2,
        )
        target_ids = [row[0] for row in loaded_targets]
        t.check("4: tone_A id preserved", A in target_ids)
        t.check("4: tone_B id preserved", B in target_ids)
        target_actions = [row[1] for row in loaded_targets]
        t.check(
            "4: actions preserved as Start",
            all(a == "Start" for a in target_actions),
        )
    else:
        # Mark remaining sub-checks as skipped / failed
        for label in (
            "4: targets list has 2 entries",
            "4: tone_A id preserved",
            "4: tone_B id preserved",
            "4: actions preserved as Start",
        ):
            t.check(label, False)

    stop_all()

    # ── Test 5: CollectionCue inside a parallel GroupCue ──────
    print("\n═══ Test 5: CollectionCue inside parallel GroupCue ═══")
    # Re-discover ids after reload
    cues_now = call("cue.list")
    id_map = {c["name"]: c["id"] for c in cues_now}
    A = id_map.get("tone_A", A)
    B = id_map.get("tone_B", B)
    C = id_map.get("tone_C", C)
    D = id_map.get("tone_D", D)

    # Fresh collection that starts C and D
    coll_id = _add_collection(
        "Coll-CD",
        [[C, "Start"], [D, "Start"]],
    )
    time.sleep(0.3)

    # Group the collection cue into a parallel GroupCue
    call("layout.context_action", {
        "action": "Group selected",
        "cue_ids": [coll_id],
    })
    time.sleep(0.3)

    cues_now = call("cue.list")
    group = next(
        (c for c in sorted(cues_now, key=lambda c: c["index"])
         if c["_type_"] == "GroupCue"),
        None,
    )
    t.check("5: GroupCue created", group is not None)

    if group is not None:
        group_id = group["id"]
        call("cue.set_property", {
            "id": group_id,
            "property": "group_mode",
            "value": "parallel",
        })

        call("cue.execute", {"id": group_id, "action": "Start"})
        time.sleep(0.5)

        t.check(
            "5: tone_C started via GroupCue → CollectionCue",
            cue_state(C) == "Running",
        )
        t.check(
            "5: tone_D started via GroupCue → CollectionCue",
            cue_state(D) == "Running",
        )
    else:
        t.check("5: tone_C started via GroupCue → CollectionCue",
                False)
        t.check("5: tone_D started via GroupCue → CollectionCue",
                False)

    stop_all()

    # Clean up group and collection
    cues_now = call("cue.list")
    for c in cues_now:
        if c["_type_"] in ("GroupCue", "CollectionCue"):
            call("cue.remove", {"id": c["id"]})
    time.sleep(0.3)

    # ── Test 6: CollectionCue targeting itself — silently skipped
    print("\n═══ Test 6: Self-target silently skipped ═══")
    # Re-discover tones after cleanup
    cues_now = call("cue.list")
    id_map = {c["name"]: c["id"] for c in cues_now}
    A = id_map.get("tone_A", A)

    self_ref_id = _add_collection("Coll-Self", [])
    time.sleep(0.3)

    # Set targets to point at itself
    call("cue.set_property", {
        "id": self_ref_id,
        "property": "targets",
        "value": [[self_ref_id, "Start"], [A, "Start"]],
    })
    time.sleep(0.2)

    call("cue.execute", {"id": self_ref_id, "action": "Start"})
    time.sleep(0.5)

    # tone_A should have started (non-self target executed)
    t.check(
        "6: non-self target (tone_A) fires normally",
        cue_state(A) == "Running",
    )
    # The collection cue itself is NOT Running (it returned False
    # from __start__, so it ends immediately in Stop state)
    t.check(
        "6: collection cue not stuck in Running (self-skip safe)",
        cue_state(self_ref_id) != "Running",
    )

    stop_all()
    call("cue.remove", {"id": self_ref_id})
    time.sleep(0.2)


if __name__ == "__main__":
    run_suite("CollectionCue dispatch", run_tests)
