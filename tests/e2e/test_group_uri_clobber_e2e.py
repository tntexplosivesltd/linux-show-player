#!/usr/bin/env python3
"""Repro: starting a re-grouped group clobbers the first child's URI.

Repro chain:

    1. Import N audio cues.
    2. Group them all → GroupCue at index 0, children at 1..N.
    3. Ungroup → group dissolved, children at 0..N-1.
    4. Group them all again → new GroupCue at 0, children at 1..N.
    5. Start the new group.

After step 5 the FIRST CHILD's UriInput.uri is reset to its
default ('.') and its duration is 0, even though every other child
keeps its URI/duration intact. The cue then fires `error` because
GStreamer can't open '.'.

Run as a standalone script — not via pytest::

    poetry run python tests/e2e/test_group_uri_clobber_e2e.py
"""

import os
import sys
import time

sys.path.insert(
    0, os.path.join(os.path.dirname(__file__))
)
from helpers import (  # noqa: E402
    AUDIO_DIR,
    call,
    create_test_audio,
    cue_prop,
    cue_state,
    parse_args,
    run_suite,
    start_lisp,
    stop_all,
    stop_lisp,
)


def _audio_files():
    return [
        os.path.join(AUDIO_DIR, f"tone_{x}.wav")
        for x in ("A", "B", "C", "D")
    ]


def _uri_for(cue_id):
    """Return the live UriInput.uri value for a media cue."""
    media = call("cue.get_property", {
        "id": cue_id, "property": "media",
    })["value"]
    return media.get("elements", {}).get("UriInput", {}).get("uri", "?")


def _media_duration(cue_id):
    media = call("cue.get_property", {
        "id": cue_id, "property": "media",
    })["value"]
    return media.get("duration", -1)


def _import_audio_cues():
    """Add the 4 standard test tones via the harness."""
    call("cue.add_from_uri", {"files": _audio_files()})
    # Allow async pipeline init / duration discovery to settle.
    time.sleep(1.5)


def _select_all_media_cues():
    """Drive the layout's selection so the inspector binds to the
    media-cue selection — mirrors the user pressing Ctrl+A."""
    cues = sorted(call("cue.list"), key=lambda c: c["index"])
    indices = [
        c["index"] for c in cues if c["_type_"] == "GstMediaCue"
    ]
    call("layout.select_cues", {"indices": indices})
    time.sleep(0.3)


def _select_only_group():
    """Move selection to the GroupCue so the inspector rebinds."""
    cues = sorted(call("cue.list"), key=lambda c: c["index"])
    g_idx = [
        c["index"] for c in cues if c["_type_"] == "GroupCue"
    ]
    call("layout.select_cues", {"indices": g_idx})
    time.sleep(0.3)


def _group_all():
    cue_ids = [c["id"] for c in call("cue.list")]
    assert len(cue_ids) >= 2, "need at least 2 cues to group"
    call("layout.context_action", {
        "action": "Group selected", "cue_ids": cue_ids,
    })
    time.sleep(0.5)


def _ungroup_existing():
    group = next(
        (c for c in call("cue.list") if c["_type_"] == "GroupCue"),
        None,
    )
    assert group is not None, "no group to ungroup"
    call("layout.context_action", {
        "action": "Ungroup", "cue_ids": [group["id"]],
    })
    time.sleep(0.5)


def _find_group_id():
    g = next(
        (c for c in call("cue.list") if c["_type_"] == "GroupCue"),
        None,
    )
    assert g is not None, "no group present"
    return g["id"]


def _children_in_order():
    """Return media-cue ids in display order (children of the group)."""
    cues = sorted(call("cue.list"), key=lambda c: c["index"])
    return [c["id"] for c in cues if c["_type_"] == "GstMediaCue"]


def run_tests(t):
    print("Generating test audio files...")
    create_test_audio()

    # ── Step 1: import audio cues ────────────────────────────
    print("\n═══ Step 1: import audio cues ═══")
    _import_audio_cues()
    cues = call("cue.list")
    t.check(
        f"imported {len(cues)} GstMediaCues",
        len(cues) == 4
        and all(c["_type_"] == "GstMediaCue" for c in cues),
    )

    # Capture the URI for what will become the first child.
    children_initial = _children_in_order()
    first_child = children_initial[0]
    expected_uri = _uri_for(first_child)
    t.check(
        "first child has a non-default URI after import",
        expected_uri not in (".", "", None),
    )
    print(f"  first_child id: {first_child}")
    print(f"  expected uri: {expected_uri}")

    # ── Step 2: group all ────────────────────────────────────
    print("\n═══ Step 2: group all cues ═══")
    _group_all()
    group_id = _find_group_id()
    t.check(
        "first child URI intact after group",
        _uri_for(first_child) == expected_uri,
    )

    # ── Step 3: select group, then expand it ─────────────────
    # Mirrors a single mouse click on the expand caret of a
    # collapsed group: the click first selects the group, then
    # toggles `collapsed` False. Both events are emitted
    # back-to-back.
    print("\n═══ Step 3: select group, then expand ═══")
    _select_only_group()
    # Yield so selection_changed is processed before the
    # property change.
    time.sleep(0.3)
    call("cue.set_property", {
        "id": group_id, "property": "collapsed", "value": False,
    })
    # Allow the inspector's debounced refresh + commit engine to
    # finish reacting to the property/selection events.
    time.sleep(0.5)
    t.check(
        "first child URI intact after select+expand",
        _uri_for(first_child) == expected_uri,
    )

    # ── Step 4: start the group ──────────────────────────────
    print("\n═══ Step 4: start group ═══")
    call("cue.execute", {"id": group_id, "action": "Start"})
    time.sleep(1.0)

    # Headline assertion: the first child's URI must NOT have been
    # reset to its default. This is the bug we're fixing.
    uri_after_start = _uri_for(first_child)
    duration_after_start = _media_duration(first_child)
    print(f"  uri after start:      {uri_after_start}")
    print(f"  duration after start: {duration_after_start}")

    t.check(
        "first child URI preserved after start of re-grouped group",
        uri_after_start == expected_uri,
    )
    t.check(
        "first child media.duration preserved after start",
        duration_after_start > 0,
    )
    t.check(
        "first child did NOT enter Error state",
        cue_state(first_child) != "Error",
    )

    # All siblings should still have their URIs intact.
    for cid in children_initial[1:]:
        u = _uri_for(cid)
        t.check(
            f"sibling URI intact for {cid[:8]}",
            u not in (".", "", None),
        )

    stop_all()


if __name__ == "__main__":
    run_suite("Group URI Clobber Repro", run_tests)
