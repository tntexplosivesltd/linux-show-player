"""E2E tests for the QLab-style cue inspector.

Verifies that the inspector follows the layout selection, drives
edits straight back into the cue model, supports multi-cue
selections with mixed-value indication, and stays in sync with
external mutations (undo/redo, RPC writes).
"""

import os
import time

from tests.e2e.helpers import (
    AUDIO_DIR,
    add_test_tones,
    call,
    clear_cues,
    cue_prop,
    run_suite,
    setup_with_tones,
    stop_all,
)


GENERAL = "General"
MEDIA = "Media Cue"


def _select(indices):
    """Switch the layout into selection mode and pick by index."""
    call("layout.selection_mode", {"enable": True})
    call("layout.select_cues", {"indices": list(indices)})
    # Selection emit timer fires on a 50ms debounce.
    time.sleep(0.2)


def run_tests(t):
    setup_with_tones()

    # ── Test 1: Empty selection → empty inspector ─────────────
    print("\n=== Test 1: Empty selection ===")
    call("layout.selection_mode", {"enable": True})
    call("layout.select_cues", {"indices": []})
    time.sleep(0.2)

    state = call("inspector.state")
    t.check(
        "1: no cues bound when selection empty",
        state["cue_ids"] == [],
    )
    t.check(
        "1: tab row is empty when no cue is selected",
        state["tab_count"] == 0,
    )

    # ── Test 2: Single-cue selection populates tabs ───────────
    print("\n=== Test 2: Single-cue selection ===")
    cues = call("cue.list")
    cue_a_id = cues[0]["id"]
    _select([0])

    state = call("inspector.state")
    t.check(
        "2: inspector binds to selected cue",
        state["cue_ids"] == [cue_a_id],
    )
    t.check(
        "2: General tab is present",
        GENERAL in state["page_names"],
    )
    t.check(
        "2: Media Cue tab is present (audio cue)",
        MEDIA in state["page_names"],
    )

    field = call("inspector.get_field", {
        "page_name": GENERAL,
        "object_name": "cueNameEdit",
    })
    t.check(
        "2: name field reflects cue name",
        field["value"] == cues[0]["name"],
    )
    t.check(
        "2: name field is not in mixed state",
        field["mixed"] is False,
    )

    # ── Test 3: Editing a field commits to the cue ────────────
    print("\n=== Test 3: Field edit → cue update ===")
    new_name = "Inspector Renamed"
    call("inspector.set_field", {
        "page_name": GENERAL,
        "object_name": "cueNameEdit",
        "value": new_name,
    })
    # set_field issues an explicit flush; a brief settle is enough
    # for the property_changed → external-refresh tick to drain.
    time.sleep(0.1)

    t.check(
        "3: cue.name updated via inspector",
        cue_prop(cue_a_id, "name") == new_name,
    )

    # The inspector itself should also reflect the new value (no
    # divergence between the snapshot and the live cue).
    field = call("inspector.get_field", {
        "page_name": GENERAL,
        "object_name": "cueNameEdit",
    })
    t.check(
        "3: inspector field still shows new name",
        field["value"] == new_name,
    )

    # ── Test 4: Edit is undoable ──────────────────────────────
    print("\n=== Test 4: Undo restores previous name ===")
    call("commands.undo")
    time.sleep(0.5)

    original_name = cues[0]["name"]
    t.check(
        "4: undo restores cue name",
        cue_prop(cue_a_id, "name") == original_name,
    )
    field = call("inspector.get_field", {
        "page_name": GENERAL,
        "object_name": "cueNameEdit",
    })
    t.check(
        "4: inspector reflects undone state",
        field["value"] == original_name,
    )

    # ── Test 5: External RPC edit refreshes inspector ─────────
    print("\n=== Test 5: External edit ===")
    call("cue.set_property", {
        "id": cue_a_id,
        "property": "name",
        "value": "RPC Direct",
    })
    time.sleep(0.5)
    field = call("inspector.get_field", {
        "page_name": GENERAL,
        "object_name": "cueNameEdit",
    })
    t.check(
        "5: inspector picks up RPC-driven name change",
        field["value"] == "RPC Direct",
    )

    # ── Test 6: Multi-cue selection shows mixed indicator ─────
    print("\n=== Test 6: Multi-cue mixed state ===")
    # Names are distinct (the four tones), so the cueNameEdit
    # should render as mixed; the loop value is the same default
    # (0) on every audio cue, so spinLoop should not be mixed.
    _select([0, 1, 2, 3])

    state = call("inspector.state")
    t.check(
        "6: inspector is bound to all 4 cues",
        len(state["cue_ids"]) == 4,
    )

    field = call("inspector.get_field", {
        "page_name": GENERAL,
        "object_name": "cueNameEdit",
    })
    t.check(
        "6: name field marked as mixed across cues",
        field["mixed"] is True,
    )

    field = call("inspector.get_field", {
        "page_name": MEDIA,
        "object_name": "spinLoop",
    })
    t.check(
        "6: loop field is shared (not mixed)",
        field["mixed"] is False,
    )

    # ── Test 7: Multi-cue commit fans out to every cue ────────
    print("\n=== Test 7: Multi-edit applies to all selected ===")
    # Switch to the Media Cue tab so the field is hosted by the
    # currently bound page; spinLoop only commits when that page
    # is the active one.
    call("inspector.set_active_page", {"page_name": MEDIA})
    time.sleep(0.05)

    # In multi-edit mode, each property sits inside a checkable
    # QGroupBox that must be checked before its value is included
    # in getSettings(). Mimic the user ticking the "apply this" box.
    call("inspector.set_group_enabled", {
        "page_name": MEDIA,
        "group_name": "loopGroup",
        "enabled": True,
    })
    call("inspector.set_field", {
        "page_name": MEDIA,
        "object_name": "spinLoop",
        "value": 5,
    })
    time.sleep(0.1)

    cues = call("cue.list")
    loops = [
        cue_prop(c["id"], "media")["loop"] for c in cues
    ]
    t.check(
        "7: every selected cue received loop=5",
        loops == [5, 5, 5, 5],
    )

    # ── Test 8: Toggle inspector visibility ───────────────────
    print("\n=== Test 8: Toggle visibility ===")
    initial = call("inspector.state")["visible"]
    after = call("inspector.toggle")
    t.check(
        "8: toggle flips visibility",
        after["visible"] != initial,
    )
    # Restore prior state so subsequent runs in --no-launch mode
    # don't drift the user's UI.
    call("inspector.toggle", {"visible": initial})
    t.check(
        "8: explicit visible param honored",
        call("inspector.state")["visible"] == initial,
    )

    # ── Test 9: Direct bind bypasses selection ────────────────
    print("\n=== Test 9: inspector.bind ===")
    call("layout.select_cues", {"indices": []})
    time.sleep(0.1)
    t.check(
        "9 precond: inspector unbound after deselect",
        call("inspector.state")["cue_ids"] == [],
    )

    cues = call("cue.list")
    target = cues[1]["id"]
    call("inspector.bind", {"cue_ids": [target]})
    time.sleep(0.1)
    t.check(
        "9: inspector bound directly via RPC",
        call("inspector.state")["cue_ids"] == [target],
    )

    # ── Test 10: Bound cue is removed → inspector clears ──────
    print("\n=== Test 10: Cue removal clears inspector ===")
    call("inspector.bind", {"cue_ids": [target]})
    time.sleep(0.1)
    call("cue.remove", {"id": target})
    time.sleep(0.3)
    state = call("inspector.state")
    t.check(
        "10: inspector forgets removed cue",
        target not in state["cue_ids"],
    )

    # ── Cleanup ───────────────────────────────────────────────
    stop_all()
    clear_cues()


if __name__ == "__main__":
    # Sanity-check audio directory before run_suite handles the rest.
    if not os.path.isdir(AUDIO_DIR):
        os.makedirs(AUDIO_DIR, exist_ok=True)
    # add_test_tones is exercised through setup_with_tones in
    # run_tests; importing it here ensures the helper lives where
    # we expect even if helpers.py is refactored.
    _ = add_test_tones
    run_suite("Inspector", run_tests)
