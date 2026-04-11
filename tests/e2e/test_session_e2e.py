#!/usr/bin/env python3
"""E2E tests for session save/load fidelity.

Verifies that MediaCue and GroupCue properties round-trip through
session.save / session.load, that index ordering is preserved, that
commands.is_saved() reflects the correct state, and that
session.new resets the model cleanly.

Run:
    poetry run python tests/e2e/test_session_e2e.py

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
    clear_cues,
    cue_prop,
    run_suite,
    setup_with_tones,
    stop_all,
)

SAVE_PATH = "/tmp/lisp_session_e2e_test.lsp"
SAVE_PATH_2 = "/tmp/lisp_session_e2e_test2.lsp"


# ── Poll helpers ───────────────────────────────────────────────

def _wait_for_count(expected, timeout=10.0):
    """Poll cue.list until expected count arrives or timeout."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        cues = call("cue.list")
        if len(cues) == expected:
            return cues
        time.sleep(0.4)
    return call("cue.list")


def _wait_for_group(timeout=10.0):
    """Poll cue.list until a GroupCue appears; return it or None."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        cues = call("cue.list")
        group = next(
            (c for c in sorted(cues, key=lambda c: c["index"])
             if c["_type_"] == "GroupCue"),
            None,
        )
        if group is not None:
            return group
        time.sleep(0.4)
    return None


# ── Tests ──────────────────────────────────────────────────────

def test_1_mediacue_roundtrip(t):
    """MediaCue with custom name, volume, fades round-trips."""
    print("\n=== Test 1: MediaCue property round-trip ===")

    ids = setup_with_tones()
    cue_id = ids["tone_A"]

    # Set distinctive properties
    call("cue.set_property", {
        "id": cue_id, "property": "name",
        "value": "RoundTrip Tone",
    })
    call("cue.set_property", {
        "id": cue_id, "property": "fadein_duration",
        "value": 1.5,
    })
    call("cue.set_property", {
        "id": cue_id, "property": "fadeout_duration",
        "value": 2.5,
    })

    call("session.save", {"path": SAVE_PATH})
    call("session.load", {"path": SAVE_PATH})

    cues = _wait_for_count(4)
    reloaded = next(
        (c for c in cues if c["name"] == "RoundTrip Tone"),
        None,
    )

    t.check("1: Cue found after reload", reloaded is not None)
    if reloaded is None:
        return

    rid = reloaded["id"]
    t.check(
        "1: name preserved",
        cue_prop(rid, "name") == "RoundTrip Tone",
    )
    t.check(
        "1: fadein_duration preserved",
        abs(cue_prop(rid, "fadein_duration") - 1.5) < 1e-6,
    )
    t.check(
        "1: fadeout_duration preserved",
        abs(cue_prop(rid, "fadeout_duration") - 2.5) < 1e-6,
    )


def test_2_groupcue_roundtrip(t):
    """GroupCue crossfade, loop, group_mode, children preserved."""
    print("\n=== Test 2: GroupCue property round-trip ===")

    ids = setup_with_tones()
    A, B, C = ids["tone_A"], ids["tone_B"], ids["tone_C"]

    call("layout.context_action", {
        "action": "Group selected",
        "cue_ids": [A, B, C],
    })
    time.sleep(0.5)

    group = _wait_for_group()
    t.check("2: Group created", group is not None)
    if group is None:
        return
    gid = group["id"]

    call("cue.set_property", {
        "id": gid, "property": "group_mode", "value": "playlist",
    })
    call("cue.set_property", {
        "id": gid, "property": "crossfade", "value": 1.75,
    })
    call("cue.set_property", {
        "id": gid, "property": "loop", "value": True,
    })

    call("session.save", {"path": SAVE_PATH})
    call("session.load", {"path": SAVE_PATH})

    group_after = _wait_for_group()
    t.check("2: Group present after reload", group_after is not None)
    if group_after is None:
        return
    gid2 = group_after["id"]

    t.check(
        "2: group_mode preserved",
        cue_prop(gid2, "group_mode") == "playlist",
    )
    t.check(
        "2: crossfade preserved",
        abs(cue_prop(gid2, "crossfade") - 1.75) < 1e-6,
    )
    t.check(
        "2: loop preserved",
        cue_prop(gid2, "loop") is True,
    )
    t.check(
        "2: children count preserved",
        len(cue_prop(gid2, "children")) == 3,
    )


def test_3_children_retain_group_id(t):
    """Children retain group_id after save/load."""
    print("\n=== Test 3: Children retain group_id after reload ===")

    ids = setup_with_tones()
    A, B = ids["tone_A"], ids["tone_B"]

    call("layout.context_action", {
        "action": "Group selected",
        "cue_ids": [A, B],
    })
    time.sleep(0.5)

    group = _wait_for_group()
    t.check("3: Group created", group is not None)
    if group is None:
        return

    call("session.save", {"path": SAVE_PATH})
    call("session.load", {"path": SAVE_PATH})

    group_after = _wait_for_group()
    t.check("3: Group found after reload", group_after is not None)
    if group_after is None:
        return
    gid2 = group_after["id"]

    # Find children by scanning all cues for group_id == gid2
    cues = call("cue.list")
    children = [
        c for c in cues
        if c["_type_"] != "GroupCue"
        and cue_prop(c["id"], "group_id") == gid2
    ]
    t.check(
        "3: Children have correct group_id after reload",
        len(children) == 2,
    )


def test_4_index_ordering_preserved(t):
    """Cue index ordering is preserved after save/load."""
    print("\n=== Test 4: Index ordering preserved ===")

    setup_with_tones()

    # Record the pre-save ordering by name
    cues_before = sorted(
        call("cue.list"), key=lambda c: c["index"],
    )
    names_before = [c["name"] for c in cues_before]

    call("session.save", {"path": SAVE_PATH})
    call("session.load", {"path": SAVE_PATH})

    _wait_for_count(4)
    cues_after = sorted(
        call("cue.list"), key=lambda c: c["index"],
    )
    names_after = [c["name"] for c in cues_after]

    t.check(
        "4: Count preserved",
        len(names_after) == len(names_before),
    )
    t.check(
        "4: Name order preserved",
        names_after == names_before,
    )


def test_5_is_saved_after_save(t):
    """commands.is_saved() is True after save, False after mutation."""
    print("\n=== Test 5: is_saved state management ===")

    ids = setup_with_tones()
    cue_id = ids["tone_A"]

    call("session.save", {"path": SAVE_PATH})
    is_saved = call("commands.is_saved")["saved"]
    t.check("5: is_saved True after save", is_saved is True)

    # Mutate via command stack (UpdateCueCommand)
    call("cue.set_property", {
        "id": cue_id, "property": "name", "value": "Mutated",
    })
    is_saved = call("commands.is_saved")["saved"]
    t.check("5: is_saved False after mutation", is_saved is False)


def test_6_is_saved_after_load(t):
    """commands.is_saved() is True immediately after session.load."""
    print("\n=== Test 6: is_saved True after load ===")

    setup_with_tones()
    call("session.save", {"path": SAVE_PATH})

    # Dirty the session
    ids_now = {c["name"]: c["id"] for c in call("cue.list")}
    call("cue.set_property", {
        "id": next(iter(ids_now.values())),
        "property": "name",
        "value": "Dirty",
    })
    t.check(
        "6 precond: session dirty before load",
        call("commands.is_saved")["saved"] is False,
    )

    call("session.load", {"path": SAVE_PATH})
    _wait_for_count(4)

    is_saved = call("commands.is_saved")["saved"]
    t.check("6: is_saved True after load", is_saved is True)


def test_7_save_overwrite(t):
    """Save to an existing path (overwrite) succeeds."""
    print("\n=== Test 7: Save overwrite succeeds ===")

    ids = setup_with_tones()
    cue_id = ids["tone_A"]

    # First save
    call("session.save", {"path": SAVE_PATH})

    # Modify and save again to the same path
    call("cue.set_property", {
        "id": cue_id, "property": "name",
        "value": "Overwritten Name",
    })
    call("session.save", {"path": SAVE_PATH})
    is_saved = call("commands.is_saved")["saved"]
    t.check("7: is_saved True after overwrite save", is_saved is True)

    # Reload to verify overwritten content was written
    call("session.load", {"path": SAVE_PATH})
    _wait_for_count(4)

    cues = call("cue.list")
    found = any(c["name"] == "Overwritten Name" for c in cues)
    t.check("7: Overwritten name survives reload", found)


def test_8_session_new_resets_model(t):
    """session.new while cues exist resets the model cleanly."""
    print("\n=== Test 8: session.new resets model ===")

    setup_with_tones()
    t.check(
        "8 precond: 4 cues before new",
        call("cue.count")["count"] == 4,
    )

    call("session.new", {"layout_type": "ListLayout"})

    # Poll until model is empty (async reset)
    deadline = time.time() + 10.0
    count = call("cue.count")["count"]
    while count > 0 and time.time() < deadline:
        time.sleep(0.4)
        count = call("cue.count")["count"]

    t.check("8: Model empty after session.new", count == 0)

    # Verify session is usable — add a cue
    call("cue.add", {
        "type": "StopAll",
        "properties": {"name": "After Reset"},
    })
    time.sleep(0.3)
    t.check(
        "8: Can add cues after session.new",
        call("cue.count")["count"] == 1,
    )


# ── Suite entry point ──────────────────────────────────────────

def run_tests(t):
    try:
        test_1_mediacue_roundtrip(t)
    except Exception as e:
        t.check(f"Test 1 error: {e}", False)

    try:
        test_2_groupcue_roundtrip(t)
    except Exception as e:
        t.check(f"Test 2 error: {e}", False)

    try:
        test_3_children_retain_group_id(t)
    except Exception as e:
        t.check(f"Test 3 error: {e}", False)

    try:
        test_4_index_ordering_preserved(t)
    except Exception as e:
        t.check(f"Test 4 error: {e}", False)

    try:
        test_5_is_saved_after_save(t)
    except Exception as e:
        t.check(f"Test 5 error: {e}", False)

    try:
        test_6_is_saved_after_load(t)
    except Exception as e:
        t.check(f"Test 6 error: {e}", False)

    try:
        test_7_save_overwrite(t)
    except Exception as e:
        t.check(f"Test 7 error: {e}", False)

    try:
        test_8_session_new_resets_model(t)
    except Exception as e:
        t.check(f"Test 8 error: {e}", False)

    stop_all()


if __name__ == "__main__":
    run_suite("Session Save/Load", run_tests)
