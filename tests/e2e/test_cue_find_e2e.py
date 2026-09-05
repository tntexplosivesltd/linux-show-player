#!/usr/bin/env python3
"""E2E tests for the cue find & jump bar.

Covers:
    - text matches name or cue_number
    - colour narrows matches (AND with text)
    - find_jump moves the standby cursor through matches with wrap
    - closing the find (empty query) clears matches

Run:
    poetry run python tests/e2e/test_cue_find_e2e.py
"""

import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from tests.e2e.helpers import call, clear_cues, run_suite


def _add(name, color_name=""):
    cue_id = call("cue.add", {
        "type": "StopAll",
        "properties": {"name": name},
    })["id"]
    if color_name:
        call("cue.set_property", {
            "id": cue_id, "property": "color_name", "value": color_name,
        })
    return cue_id


def run_tests(t):
    clear_cues()
    # Model order 0..3. Auto-assigned cue_numbers are "1".."4".
    _add("Opening music", "Red")     # index 0, Q# 1
    _add("Thunder", "Blue")          # index 1, Q# 2
    _add("House lights", "Red")      # index 2, Q# 3
    _add("Blackout")                 # index 3, Q# 4
    time.sleep(0.5)

    # --- text matches name ---
    res = call("layout.find", {"text": "thunder"})
    t.check("1a: name match -> index 1", res["matches"] == [1])

    # --- text matches cue_number ---
    res = call("layout.find", {"text": "3"})
    t.check("2a: cue_number '3' match -> index 2", res["matches"] == [2])

    # --- colour narrows (AND) ---
    res = call("layout.find", {"text": "", "color": "Red"})
    t.check("3a: colour Red -> indices 0,2", res["matches"] == [0, 2])
    res = call("layout.find", {"text": "House", "color": "Red"})
    t.check("3b: text+colour anded -> index 2", res["matches"] == [2])
    res = call("layout.find", {"text": "Thunder", "color": "Red"})
    t.check("3c: text+wrong colour -> no match", res["matches"] == [])

    # --- jump moves standby through matches, wrapping ---
    call("layout.find", {"text": "", "color": "Red"})  # matches [0, 2]
    j1 = call("layout.find_jump", {"step": 1})
    t.check("4a: first next -> standby 0", j1["standby_index"] == 0)
    j2 = call("layout.find_jump", {"step": 1})
    t.check("4b: second next -> standby 2", j2["standby_index"] == 2)
    j3 = call("layout.find_jump", {"step": 1})
    t.check("4c: third next wraps -> standby 0", j3["standby_index"] == 0)
    j4 = call("layout.find_jump", {"step": -1})
    t.check("4d: prev wraps back -> standby 2", j4["standby_index"] == 2)

    # --- clearing the query deactivates search ---
    res = call("layout.find", {"text": "", "color": ""})
    t.check("5a: empty query -> no matches", res["matches"] == [])

    clear_cues()


if __name__ == "__main__":
    run_suite("Cue Find & Jump E2E", run_tests)
