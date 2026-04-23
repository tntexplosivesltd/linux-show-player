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

"""E2E smoke test for group cue outlines.

Verifies the paint wiring doesn't crash when the conditions that
trigger repaints fire end-to-end: group creation, group_mode change,
collapse/expand, and ungroup.

Does NOT verify pixels — that's manual verification.

Run:
    poetry run python tests/e2e/test_group_outlines_e2e.py
"""

import atexit
import json
import os
import subprocess
import sys
import tempfile
import time

sys.path.insert(
    0,
    os.path.join(
        os.path.dirname(__file__), "..", "..",
        "lisp", "plugins", "test_harness",
    ),
)
from client import send_request  # noqa: E402

HOST = "127.0.0.1"
PORT = 8070
STARTUP_TIMEOUT = 30

_pass = 0
_fail = 0
_errors = []
_lisp_proc = None


def _create_empty_session():
    session = {
        "meta": {"version": "0.6"},
        "session": {"layout_type": "ListLayout"},
        "cues": [],
    }
    fd, path = tempfile.mkstemp(suffix=".lsp")
    with os.fdopen(fd, "w") as f:
        json.dump(session, f)
    return path


def start_lisp():
    global _lisp_proc
    session_path = _create_empty_session()
    log_fd, log_path = tempfile.mkstemp(suffix=".log")
    os.close(log_fd)
    log_file = open(log_path, "w")
    _lisp_proc = subprocess.Popen(
        [
            sys.executable, "-m", "lisp.main",
            "-l", "warning", "-f", session_path,
        ],
        stdout=log_file,
        stderr=subprocess.STDOUT,
    )
    atexit.register(stop_lisp)

    deadline = time.time() + STARTUP_TIMEOUT
    while time.time() < deadline:
        if _lisp_proc.poll() is not None:
            log_file.close()
            with open(log_path) as f:
                print("LiSP exited early:", file=sys.stderr)
                print(f.read(), file=sys.stderr)
            raise RuntimeError("LiSP process exited during startup")
        try:
            # Harness is ready once the socket answers AND the session
            # file (-f) has finished loading on the main thread.
            info = send_request(HOST, PORT, "session.info")
            if info.get("result", {}).get("has_session"):
                log_file.close()
                os.unlink(log_path)
                return
        except (ConnectionRefusedError, ConnectionError, OSError):
            pass
        time.sleep(0.5)

    log_file.close()
    with open(log_path) as f:
        print("LiSP startup log:", file=sys.stderr)
        print(f.read(), file=sys.stderr)
    raise RuntimeError("LiSP did not start within timeout")


def stop_lisp():
    global _lisp_proc
    if _lisp_proc is not None:
        _lisp_proc.terminate()
        try:
            _lisp_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _lisp_proc.kill()
        _lisp_proc = None


def call(method, params=None):
    r = send_request(HOST, PORT, method, params or {})
    if "error" in r:
        raise RuntimeError(f"{method} failed: {r['error']}")
    return r.get("result", {})


def check(name, cond):
    global _pass, _fail
    if cond:
        _pass += 1
        print(f"  ✓ {name}")
    else:
        _fail += 1
        _errors.append(name)
        print(f"  ✗ {name}")


def cue_prop(cue_id, prop):
    r = call("cue.get_property", {"id": cue_id, "property": prop})
    return r.get("value")


def test_outline_lifecycle():
    print("\n═══ Group outline lifecycle ═══")

    # Add three simple cues into the empty ListLayout session.
    r_a = call("cue.add", {"type": "StopAll", "properties": {"name": "A"}})
    r_b = call("cue.add", {"type": "StopAll", "properties": {"name": "B"}})
    call("cue.add", {"type": "StopAll", "properties": {"name": "C"}})
    a_id, b_id = r_a["id"], r_b["id"]

    # Group A and B
    call("layout.context_action", {
        "action": "Group selected",
        "cue_ids": [a_id, b_id],
    })
    time.sleep(0.3)

    cues = call("cue.list")
    group_cues = [c for c in cues if c["_type_"] == "GroupCue"]
    check("group created", len(group_cues) == 1)
    group_id = group_cues[0]["id"]

    # Flip group_mode parallel → playlist → parallel; each change
    # must not raise and must update the property.
    call("cue.set_property", {
        "id": group_id, "property": "group_mode", "value": "playlist",
    })
    time.sleep(0.2)
    check("mode changed to playlist",
          cue_prop(group_id, "group_mode") == "playlist")

    call("cue.set_property", {
        "id": group_id, "property": "group_mode", "value": "parallel",
    })
    time.sleep(0.2)
    check("mode changed back to parallel",
          cue_prop(group_id, "group_mode") == "parallel")

    # Collapse + expand
    call("cue.set_property", {
        "id": group_id, "property": "collapsed", "value": True,
    })
    time.sleep(0.2)
    check("group collapsed",
          cue_prop(group_id, "collapsed") is True)

    call("cue.set_property", {
        "id": group_id, "property": "collapsed", "value": False,
    })
    time.sleep(0.2)
    check("group expanded",
          cue_prop(group_id, "collapsed") is False)

    # Ungroup — the group disappears, outline wiring must tolerate it
    call("layout.context_action", {
        "action": "Ungroup", "cue_ids": [group_id],
    })
    time.sleep(0.3)

    cues_after = call("cue.list")
    group_cues_after = [c for c in cues_after if c["_type_"] == "GroupCue"]
    check("group removed", len(group_cues_after) == 0)

    # Ping once more — if paint crashed the main thread, this fails.
    r = send_request(HOST, PORT, "ping")
    check("app still responsive after ungroup", "result" in r)


def main():
    print("Group outline E2E smoke test")
    print("=" * 40)
    start_lisp()
    try:
        test_outline_lifecycle()
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
