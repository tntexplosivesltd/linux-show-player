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

"""E2E: "Group selected" works on a mixed StopCue + ResumeCue selection.

Both are `(TargetingCue, Cue)`. The cue menu used to resolve such a
selection to the TargetingCue mixin, which matches no menu actions, so
the context menu came up empty and grouping failed with "Context
action not found". No media, nothing plays.

Run:
    poetry run python tests/e2e/test_group_action_cues_e2e.py
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from tests.e2e.helpers import call, start_lisp, stop_lisp  # noqa: E402

STARTUP_TIMEOUT = 30

_pass = 0
_fail = 0
_errors = []


def check(name, cond):
    global _pass, _fail
    if cond:
        _pass += 1
        print(f"  ✓ {name}")
    else:
        _fail += 1
        _errors.append(name)
        print(f"  ✗ {name}")


def group_of(cue_id):
    r = call("cue.get_property", {"id": cue_id, "property": "group_id"})
    return r.get("value")


def test_group_stop_and_resume():
    print("\n═══ Group a Fade & Stop with a Fade & Resume ═══")

    target = call("cue.add", {"type": "StopAll",
                              "properties": {"name": "Target"}})["id"]
    stop = call("cue.add", {"type": "StopCue", "properties": {
        "name": "Stop it", "target_id": target}})["id"]
    resume = call("cue.add", {"type": "ResumeCue", "properties": {
        "name": "Resume it", "target_id": target}})["id"]

    try:
        call("layout.context_action", {
            "action": "Group selected", "cue_ids": [stop, resume],
        })
        error = None
    except Exception as e:  # harness raises on a JSON-RPC error
        error = str(e)
    check(f"'Group selected' offered for Stop + Resume ({error or 'ok'})",
          error is None)
    # No wait needed: context_action blocks until the action has run
    # on the main thread.

    groups = [c for c in call("cue.list") if c["_type_"] == "GroupCue"]
    check("one group created", len(groups) == 1)
    if groups:
        gid = groups[0]["id"]
        check("Stop cue is in the group", group_of(stop) == gid)
        check("Resume cue is in the group", group_of(resume) == gid)
        check("target cue left outside the group", group_of(target) != gid)


def main():
    print("Group action cues E2E test")
    print("=" * 40)
    start_lisp(timeout=STARTUP_TIMEOUT)
    try:
        test_group_stop_and_resume()
    finally:
        stop_lisp()

    print()
    print(f"Passed: {_pass}")
    print(f"Failed: {_fail}")
    if _errors:
        for e in _errors:
            print(f"  - {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
