#!/usr/bin/env python3
"""E2E tests for static cue_number feature.

Covers:
    - Auto-assignment on cue.add (sequential 1, 2, 3...)
    - cue_number stays attached to its cue across reorders
    - Clones get a fresh number, not a duplicate
    - Custom labels (e.g. "Pre-1") don't break auto-increment
    - Save/load preserves cue_number
    - Loading a session without cue_number values backfills them

Run:
    poetry run python tests/e2e/test_cue_number_e2e.py
"""

import json
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from tests.e2e.helpers import (
    call,
    clear_cues,
    cue_prop,
    run_suite,
    start_lisp,
    stop_lisp,
)


def _add_cue(name="Untitled"):
    return call("cue.add", {
        "type": "StopAll",
        "properties": {"name": name},
    })["id"]


def _set_cue_number(cue_id, value):
    call("cue.set_property", {
        "id": cue_id, "property": "cue_number", "value": value,
    })


def _list_cue_numbers():
    """Return cue_numbers in current model order."""
    return [c["cue_number"] for c in call("cue.list")]


def run_tests(t):
    # --- Scenario 1: auto-assign on add ---
    clear_cues()
    a_id = _add_cue("Cue A")
    b_id = _add_cue("Cue B")
    c_id = _add_cue("Cue C")
    t.check(
        "1a: first cue gets '1'",
        cue_prop(a_id, "cue_number") == "1",
    )
    t.check(
        "1b: second cue gets '2'",
        cue_prop(b_id, "cue_number") == "2",
    )
    t.check(
        "1c: third cue gets '3'",
        cue_prop(c_id, "cue_number") == "3",
    )

    # --- Scenario 2: numbers travel with cues across reorders ---
    # Move cue A from index 0 to index 2. cue_number should stay "1".
    call("layout.move_cue", {"from_index": 0, "to_index": 2})
    time.sleep(0.2)
    t.check(
        "2a: moved cue keeps its number",
        cue_prop(a_id, "cue_number") == "1",
    )
    # And the order in cue.list (sorted by index) is now B, C, A
    # but their numbers are still 2, 3, 1.
    nums = _list_cue_numbers()
    t.check(
        "2b: list-order numbers reflect identity (B=2, C=3, A=1)",
        nums == ["2", "3", "1"],
    )

    # --- Scenario 3: clones get a fresh number ---
    # cue.add with the same type stands in for clone here — clone via
    # menu also funnels through CueFactory.create_cue, which is the
    # surface we're testing. A new cue gets max+1 = 4.
    d_id = _add_cue("Cue D")
    t.check(
        "3a: next add gets max+1 ('4')",
        cue_prop(d_id, "cue_number") == "4",
    )

    # --- Scenario 4: custom labels don't break auto-increment ---
    _set_cue_number(b_id, "Pre-1")
    time.sleep(0.1)
    t.check(
        "4a: custom label persisted",
        cue_prop(b_id, "cue_number") == "Pre-1",
    )
    e_id = _add_cue("Cue E")
    # Existing numeric values are 1, 3, 4. "Pre-1" is ignored.
    # max + 1 = 5.
    t.check(
        "4b: new cue skips non-numeric labels (max numeric+1 = '5')",
        cue_prop(e_id, "cue_number") == "5",
    )

    # --- Scenario 5: save / reload preserves numbers ---
    fd, save_path = tempfile.mkstemp(suffix=".lsp")
    os.close(fd)
    try:
        call("session.save", {"path": save_path})
        time.sleep(0.3)

        with open(save_path) as f:
            saved = json.load(f)
        saved_numbers = {c["name"]: c.get("cue_number")
                         for c in saved.get("cues", [])}
        t.check(
            "5a: cue_number written to saved JSON",
            saved_numbers == {
                "Cue A": "1",
                "Cue B": "Pre-1",
                "Cue C": "3",
                "Cue D": "4",
                "Cue E": "5",
            },
        )

        # Reload by stopping LiSP and starting against the saved file.
        stop_lisp()
        time.sleep(0.5)
        start_lisp_with_file(save_path)

        cues = call("cue.list")
        by_name = {c["name"]: c["cue_number"] for c in cues}
        expected = {
            "Cue A": "1",
            "Cue B": "Pre-1",
            "Cue C": "3",
            "Cue D": "4",
            "Cue E": "5",
        }
        if by_name != expected:
            print(f"  DEBUG 5b: got={by_name!r}")
            print(f"  DEBUG 5b: expected={expected!r}")
        t.check(
            "5b: cue_numbers survived save/reload",
            by_name == expected,
        )
    finally:
        if os.path.exists(save_path):
            os.unlink(save_path)

    # --- Scenario 7: programmatic add with a duplicate cue_number is uniquified ---
    # The Application hook on cue_model.item_added catches this even
    # when CueFactory.create_cue is bypassed or `properties` carries
    # an explicit value that collides with an existing cue.
    clear_cues()
    a_id = _add_cue("Cue A")
    # `cue.add` with properties={cue_number: "1"} — same as A's
    # auto-assigned value. The model hook should bump it to "2".
    dup_id = call("cue.add", {
        "type": "StopAll",
        "properties": {"name": "Dupe", "cue_number": "1"},
    })["id"]
    t.check(
        "7a: A keeps its number",
        cue_prop(a_id, "cue_number") == "1",
    )
    t.check(
        "7b: programmatic duplicate uniquified to next free",
        cue_prop(dup_id, "cue_number") == "2",
    )

    # --- Scenario 6: legacy session (no cue_number) gets backfilled ---
    fd, legacy_path = tempfile.mkstemp(suffix=".lsp")
    os.close(fd)
    legacy = {
        "meta": {"version": "0.6"},
        "session": {"layout_type": "ListLayout"},
        "cues": [
            {
                "_type_": "StopAll",
                "id": "legacy-1-id",
                "name": "Legacy 1",
                "index": 0,
            },
            {
                "_type_": "StopAll",
                "id": "legacy-2-id",
                "name": "Legacy 2",
                "index": 1,
            },
            {
                "_type_": "StopAll",
                "id": "legacy-3-id",
                "name": "Legacy 3",
                "index": 2,
            },
        ],
    }
    try:
        with open(legacy_path, "w") as f:
            json.dump(legacy, f)

        stop_lisp()
        time.sleep(0.5)
        start_lisp_with_file(legacy_path)

        cues = call("cue.list")
        by_name = {c["name"]: c["cue_number"] for c in cues}
        t.check(
            "6a: legacy cues backfilled with sequential numbers",
            by_name == {
                "Legacy 1": "1",
                "Legacy 2": "2",
                "Legacy 3": "3",
            },
        )
    finally:
        if os.path.exists(legacy_path):
            os.unlink(legacy_path)


def start_lisp_with_file(session_file):
    """Start LiSP against a specific session file and wait for the
    harness to be ready and the session to load."""
    import subprocess
    import signal as _signal
    from tests.e2e import helpers

    helpers._lisp_proc = subprocess.Popen(
        [
            sys.executable, "-m", "lisp.main",
            "-l", "warning",
            "-f", session_file,
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    deadline = time.time() + helpers.STARTUP_TIMEOUT
    while time.time() < deadline:
        try:
            resp = call("ping")
            if resp:
                info = call("session.info")
                if info.get("has_session"):
                    return
        except Exception:
            pass
        time.sleep(0.5)

    raise RuntimeError(
        f"LiSP did not start with {session_file} within "
        f"{helpers.STARTUP_TIMEOUT}s"
    )


if __name__ == "__main__":
    run_suite("Cue Number E2E", run_tests)
