#!/usr/bin/env python3
# This file is part of Linux Show Player
#
# Copyright 2026 Linux Show Player Contributors
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

"""E2E tests for TargetingCue invalid_target reactivity.

Covers: empty target_id is invalid; setting a valid target flips to
False; deleting the target flips back to True; re-pointing at a new
cue with the same id semantics (model-change reactivity); CollectionCue
with mixed valid/dangling rows is invalid; all-valid collection is
valid; empty collection is invalid.

Run:
    poetry run python tests/e2e/test_target_validity_e2e.py
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
    run_suite,
)


def _add_stop_cue(name, target_id=""):
    """Add a StopCue with the given target_id (empty by default)."""
    return call("cue.add", {
        "type": "StopCue",
        "properties": {
            "name": name,
            "target_id": target_id,
        },
    })["id"]


def _add_collection(name, targets):
    """Add a CollectionCue with the given targets list."""
    return call("cue.add", {
        "type": "CollectionCue",
        "properties": {
            "name": name,
            "targets": targets,
        },
    })["id"]


def _add_basic_cue(name):
    """Add a StopAll cue — any cue type works as a TargetingCue target."""
    return call("cue.add", {
        "type": "StopAll",
        "properties": {"name": name},
    })["id"]


def _invalid_target(cue_id):
    """Read the invalid_target property for the given cue."""
    return cue_prop(cue_id, "invalid_target")


def run_tests(t):
    # ── Test 1: empty target_id → invalid_target == True ──────────
    print("\n═══ Test 1: empty target_id is invalid ═══")
    stop1 = _add_stop_cue("Stop-empty")
    time.sleep(0.2)
    t.check(
        "empty target_id reports invalid_target=True",
        _invalid_target(stop1) is True,
    )

    # ── Test 2: set target_id to a real cue → invalid_target==False ─
    print("\n═══ Test 2: valid target_id clears invalid_target ═══")
    target_a = _add_basic_cue("Target-A")
    time.sleep(0.2)
    call("cue.update", {
        "id": stop1,
        "properties": {"target_id": target_a},
    })
    time.sleep(0.2)
    t.check(
        "after pointing at valid target, invalid_target=False",
        _invalid_target(stop1) is False,
    )

    # ── Test 3: delete target → invalid_target flips back to True ─
    print("\n═══ Test 3: deleting the target flips invalid_target back ═══")
    call("cue.remove", {"id": target_a})
    time.sleep(0.3)
    t.check(
        "after target removed, invalid_target=True again",
        _invalid_target(stop1) is True,
    )

    # ── Test 4: re-point at a new cue → flips back to False ───────
    # (simulates re-pointing a cue after its original target is gone)
    print("\n═══ Test 4: re-pointing at a new cue revives validity ═══")
    target_b = _add_basic_cue("Target-B")
    time.sleep(0.2)
    call("cue.update", {
        "id": stop1,
        "properties": {"target_id": target_b},
    })
    time.sleep(0.2)
    t.check(
        "after pointing at new target, invalid_target=False",
        _invalid_target(stop1) is False,
    )

    # ── Test 5: model-change reactivity — delete new target ────────
    # Verify that item_removed triggers recheck even for the new target
    print("\n═══ Test 5: removing new target also flips invalid ═══")
    call("cue.remove", {"id": target_b})
    time.sleep(0.3)
    t.check(
        "after new target removed, invalid_target=True",
        _invalid_target(stop1) is True,
    )

    # ── Test 6: CollectionCue with one valid + one dangling row ───
    print("\n═══ Test 6: CollectionCue with mixed rows ═══")
    target_c = _add_basic_cue("Target-C")
    time.sleep(0.2)
    coll_mixed = _add_collection(
        "Coll-mixed",
        [[target_c, "Default"], ["does-not-exist-id", "Default"]],
    )
    time.sleep(0.3)
    t.check(
        "collection with one dangling row reports invalid",
        _invalid_target(coll_mixed) is True,
    )

    # ── Test 7: CollectionCue with all-valid rows is valid ─────────
    print("\n═══ Test 7: CollectionCue with all valid rows ═══")
    target_d = _add_basic_cue("Target-D")
    time.sleep(0.2)
    coll_ok = _add_collection(
        "Coll-ok",
        [[target_c, "Default"], [target_d, "Default"]],
    )
    time.sleep(0.3)
    t.check(
        "all-valid collection reports valid",
        _invalid_target(coll_ok) is False,
    )

    # ── Test 8: empty CollectionCue is invalid ─────────────────────
    print("\n═══ Test 8: empty CollectionCue ═══")
    coll_empty = _add_collection("Coll-empty", [])
    time.sleep(0.3)
    t.check(
        "empty collection reports invalid",
        _invalid_target(coll_empty) is True,
    )

    # ── Test 9: delete one row from all-valid collection→invalid ──
    print("\n═══ Test 9: removing a target from valid collection ═══")
    call("cue.remove", {"id": target_c})
    time.sleep(0.3)
    t.check(
        "collection becomes invalid after one target removed",
        _invalid_target(coll_ok) is True,
    )


if __name__ == "__main__":
    run_suite("Target Validity E2E", run_tests)
