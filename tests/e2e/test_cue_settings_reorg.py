#!/usr/bin/env python3
# This file is part of Linux Show Player
#
# Copyright 2026 Francesco Ceruti <ceppofrancy@gmail.com>
#
# Linux Show Player is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# Linux Show Player is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Linux Show Player.  If not, see <http://www.gnu.org/licenses/>.

"""E2E tests for the cue-settings dialog reorganisation.

Covers two concerns:

1. Canonical ordering — calls the new ``settings.list_cue_pages``
   harness method for every cue type that drives the refactor and
   asserts the returned list matches the canonical slot table.
2. Settings round-trip — creates cues with every settings-key the
   merged ``CueGeneralSettingsPage`` / ``CueTimingPage`` own, saves
   the session, stops LiSP, relaunches against the saved file, and
   asserts every property survives a full restart. Guards against
   silent session-schema regressions from the page merge.

Run:
    poetry run python tests/e2e/test_cue_settings_reorg.py
"""

import os
import signal
import subprocess
import sys
import time

sys.path.insert(
    0, os.path.join(os.path.dirname(__file__), "..", ".."),
)
from tests.e2e.helpers import (  # noqa: E402
    HOST,
    PORT,
    STARTUP_TIMEOUT,
    call,
    cue_prop,
    run_suite,
    stop_all,
)
from tests.e2e import helpers as _h  # noqa: E402
from client import send_request  # noqa: E402


SAVE_PATH = "/tmp/lisp_cue_settings_reorg_test.lsp"


# ── Canonical expectations ────────────────────────────────────

# Cue-type-specific pages all share slot 30; sort_order is the
# canonical class attribute introduced by this refactor.
EXPECTED = {
    "Cue": [
        ("General", 10),
        ("Timing", 20),
        ("Triggers", 40),
        ("Cue Control", 50),
    ],
    "StopAll": [
        ("General", 10),
        ("Timing", 20),
        ("Stop Settings", 30),
        ("Triggers", 40),
        ("Cue Control", 50),
    ],
    "GroupCue": [
        ("General", 10),
        ("Timing", 20),
        ("Group Settings", 30),
        ("Triggers", 40),
        ("Cue Control", 50),
    ],
    "MediaCue": [
        ("General", 10),
        ("Timing", 20),
        ("Triggers", 40),
        ("Cue Control", 50),
        ("Media Cue", 60),
        ("Media Settings", 70),
        ("Timecode", 80),
    ],
    "MidiCue": [
        ("General", 10),
        ("Timing", 20),
        ("MIDI Settings", 30),
        ("Triggers", 40),
        ("Cue Control", 50),
    ],
    "CommandCue": [
        ("General", 10),
        ("Timing", 20),
        ("Command", 30),
        ("Triggers", 40),
        ("Cue Control", 50),
    ],
    "SeekCue": [
        ("General", 10),
        ("Timing", 20),
        ("Seek Settings", 30),
        ("Triggers", 40),
        ("Cue Control", 50),
    ],
}


# ── LiSP restart helper ───────────────────────────────────────

def _relaunch_lisp_with(session_path):
    """Stop the running LiSP and relaunch against a saved session.

    Mirrors ``helpers.start_lisp`` but passes an existing .lsp path
    instead of synthesising an empty session. Waits for the harness
    to report ``has_session=True`` before returning.
    """
    # Stop the current process — reuse helpers' bookkeeping.
    _h.stop_lisp()

    proc = subprocess.Popen(
        [
            sys.executable, "-m", "lisp.main",
            "-l", "warning",
            "-f", session_path,
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    _h._lisp_proc = proc

    deadline = time.time() + STARTUP_TIMEOUT
    while time.time() < deadline:
        try:
            resp = send_request(HOST, PORT, "ping")
            if "result" in resp:
                info = send_request(HOST, PORT, "session.info")
                result = info.get("result") or {}
                if result.get("has_session"):
                    return
        except (ConnectionRefusedError, ConnectionError, OSError):
            pass
        time.sleep(0.5)

    raise RuntimeError(
        f"LiSP did not relaunch within {STARTUP_TIMEOUT}s"
    )


# ── Tests ─────────────────────────────────────────────────────

def test_1_canonical_ordering(t):
    """settings.list_cue_pages returns the canonical slot order."""
    print("\n=== Test 1: Canonical cue-settings page ordering ===")

    for cue_type, expected in EXPECTED.items():
        try:
            pages = call(
                "settings.list_cue_pages", {"cue_type": cue_type}
            )
        except RuntimeError as exc:
            t.check(f"1: {cue_type} lookup succeeds ({exc})", False)
            continue

        got = [(p["name"], p["sort_order"]) for p in pages]
        t.check(
            f"1: {cue_type} canonical order matches "
            f"(expected {expected}, got {got})",
            got == expected,
        )


def test_2_general_timing_roundtrip(t):
    """Every key touched by the merged General/Timing pages
    survives a save → restart → load round-trip."""
    print("\n=== Test 2: General/Timing settings round-trip ===")

    # Clear any existing cues.
    for cue in call("cue.list"):
        call("cue.remove", {"id": cue["id"]})
    time.sleep(0.2)

    # Properties that live on every Cue (merged General page owns
    # all of these, plus the three Timing keys). Values chosen to
    # be distinctive so any corruption shows up.
    properties = {
        "name": "Reorg RoundTrip",
        "description": "first line\nsecond line",
        "stylesheet": (
            "background:#112233;color:#ffeedd;font-size:14pt;"
        ),
        "pre_wait": 1.25,
        "post_wait": 2.75,
        "next_action": "DoNothing",
        # Use real CueAction string values — "Default" (the enum's 0
        # value) rounds-trips vacuously because every cue starts there.
        "default_start_action": "FadeInStart",
        "default_stop_action": "FadeOutStop",
        "fadein_type": "Linear",
        "fadein_duration": 1.5,
        "fadeout_type": "Quadratic",
        "fadeout_duration": 2.5,
    }

    call("cue.add", {
        "type": "StopAll",
        "properties": properties,
    })
    time.sleep(0.3)

    cues = call("cue.list")
    t.check("2: cue created", len(cues) == 1)
    if not cues:
        return

    pre_id = cues[0]["id"]

    # Snapshot values in-memory before save, to catch writes that
    # were silently dropped or coerced by update_properties.
    snapshot = {
        key: cue_prop(pre_id, key) for key in properties
    }

    # Save → full LiSP restart → the reloaded session must contain
    # exactly one cue with every property preserved.
    call("session.save", {"path": SAVE_PATH})
    time.sleep(0.3)

    _relaunch_lisp_with(SAVE_PATH)

    cues = call("cue.list")
    t.check("2: cue present after restart", len(cues) == 1)
    if len(cues) != 1:
        return

    post_id = cues[0]["id"]
    # Name is on the cue dict — cheap sanity check first.
    t.check(
        "2: name preserved after restart",
        cues[0]["name"] == "Reorg RoundTrip",
    )

    for key, original in snapshot.items():
        actual = cue_prop(post_id, key)
        ok = (
            abs(actual - original) < 1e-6
            if isinstance(original, float)
            else actual == original
        )
        t.check(
            f"2: {key} preserved "
            f"(before={original!r}, after={actual!r})",
            ok,
        )


def test_3_exclusive_and_icon_roundtrip(t):
    """``exclusive`` (bool) and ``icon`` (str) were owned by pages
    that disappeared in the merge — extra coverage for both."""
    print("\n=== Test 3: exclusive + icon round-trip ===")

    for cue in call("cue.list"):
        call("cue.remove", {"id": cue["id"]})
    time.sleep(0.2)

    call("cue.add", {
        "type": "StopAll",
        "properties": {
            "name": "Exclusive One",
            "exclusive": True,
            "icon": "audio",
        },
    })
    time.sleep(0.2)

    call("session.save", {"path": SAVE_PATH})
    _relaunch_lisp_with(SAVE_PATH)

    cues = call("cue.list")
    t.check("3: cue present after restart", len(cues) == 1)
    if not cues:
        return

    cid = cues[0]["id"]
    t.check(
        "3: exclusive preserved",
        cue_prop(cid, "exclusive") is True,
    )
    t.check(
        "3: icon preserved",
        cue_prop(cid, "icon") == "audio",
    )


def test_4_groupcue_general_roundtrip(t):
    """Same General/Timing keys must survive on a GroupCue — it
    inherits the merged page via the Cue base class, so this
    protects against regressions in subclass hook-up."""
    print("\n=== Test 4: GroupCue General/Timing round-trip ===")

    for cue in call("cue.list"):
        call("cue.remove", {"id": cue["id"]})
    time.sleep(0.2)

    properties = {
        "name": "Group RoundTrip",
        "description": "group desc",
        "pre_wait": 0.5,
        "post_wait": 1.5,
        "next_action": "DoNothing",
        "fadein_type": "Linear",
        "fadein_duration": 0.75,
        "fadeout_type": "Linear",
        "fadeout_duration": 0.75,
    }

    call("cue.add", {
        "type": "GroupCue",
        "properties": properties,
    })
    time.sleep(0.3)

    cues = call("cue.list")
    t.check("4: cue created", len(cues) == 1)
    if not cues:
        return

    pre_id = cues[0]["id"]
    snapshot = {k: cue_prop(pre_id, k) for k in properties}

    call("session.save", {"path": SAVE_PATH})
    _relaunch_lisp_with(SAVE_PATH)

    cues = call("cue.list")
    t.check("4: cue present after restart", len(cues) == 1)
    if len(cues) != 1:
        return

    t.check(
        "4: type preserved as GroupCue",
        cues[0]["_type_"] == "GroupCue",
    )

    post_id = cues[0]["id"]
    for key, original in snapshot.items():
        actual = cue_prop(post_id, key)
        ok = (
            abs(actual - original) < 1e-6
            if isinstance(original, float)
            else actual == original
        )
        t.check(
            f"4: {key} preserved "
            f"(before={original!r}, after={actual!r})",
            ok,
        )


# ── Suite entry point ─────────────────────────────────────────

def run_tests(t):
    try:
        test_1_canonical_ordering(t)
    except Exception as e:
        t.check(f"Test 1 error: {e}", False)

    try:
        test_2_general_timing_roundtrip(t)
    except Exception as e:
        t.check(f"Test 2 error: {e}", False)

    try:
        test_3_exclusive_and_icon_roundtrip(t)
    except Exception as e:
        t.check(f"Test 3 error: {e}", False)

    try:
        test_4_groupcue_general_roundtrip(t)
    except Exception as e:
        t.check(f"Test 4 error: {e}", False)

    stop_all()


if __name__ == "__main__":
    run_suite(
        "Cue Settings Reorg (canonical order + round-trip)",
        run_tests,
    )
