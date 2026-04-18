#!/usr/bin/env python3
"""End-to-end test: shuffle must fire when LiSP is restarted with a
saved session.

Simulates the real user flow:
  1. Start LiSP fresh
  2. Build a playlist group with shuffle=True
  3. Save session
  4. Terminate LiSP completely
  5. Relaunch LiSP with `-f session_file`
  6. Verify children order differs from the saved order
     (i.e. the shuffle handler ran at session-load)

Run:
    poetry run python tests/e2e/test_shuffle_restart.py
"""

import atexit
import json
import os
import signal
import subprocess
import sys
import time

sys.path.insert(
    0,
    os.path.join(
        os.path.dirname(__file__), "..", "..", "lisp", "plugins",
        "test_harness",
    ),
)
from client import send_request  # noqa: E402

HOST = "127.0.0.1"
PORT = 8070
STARTUP_TIMEOUT = 20
SESSION_PATH = "/tmp/lisp_shuffle_restart_session.lsp"

_pass = 0
_fail = 0
_errors = []
_proc = None


def call(method, params=None):
    resp = send_request(HOST, PORT, method, params or {})
    if "error" in resp:
        raise RuntimeError(f"{method}: {resp['error']['message']}")
    return resp.get("result")


def check(name, condition):
    global _pass, _fail
    if condition:
        _pass += 1
        print(f"  PASS: {name}")
    else:
        _fail += 1
        _errors.append(name)
        print(f"  FAIL: {name}")


def launch(session_file):
    global _proc
    _proc = subprocess.Popen(
        [sys.executable, "-m", "lisp.main", "-l", "warning",
         "-f", session_file],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    atexit.register(terminate)

    deadline = time.time() + STARTUP_TIMEOUT
    while time.time() < deadline:
        try:
            resp = send_request(HOST, PORT, "ping")
            if "result" in resp:
                return
        except (ConnectionRefusedError, ConnectionError, OSError):
            pass
        time.sleep(0.5)

    terminate()
    print(
        f"ERROR: LiSP didn't start within {STARTUP_TIMEOUT}s",
        file=sys.stderr,
    )
    sys.exit(2)


def terminate():
    global _proc
    if _proc and _proc.poll() is None:
        _proc.send_signal(signal.SIGTERM)
        try:
            _proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _proc.kill()
    _proc = None


def make_empty_session(path):
    with open(path, "w") as f:
        json.dump({
            "meta": {"version": "0.6"},
            "session": {"layout_type": "ListLayout"},
            "cues": [],
        }, f)


def add_stop_cue(name):
    """Add a StopAll cue (simple, no media) as group child."""
    resp = call("cue.add", {
        "type": "StopAll",
        "properties": {"name": name},
    })
    return resp["id"]


def main():
    print("═══ Shuffle-on-restart E2E ═══")

    # 1. Start LiSP fresh with an empty session
    make_empty_session(SESSION_PATH)
    print("Starting LiSP (empty session)...")
    launch(SESSION_PATH)
    print("LiSP ready.")

    # 2. Add six simple cues, then group them
    child_ids = [add_stop_cue(f"cue_{i}") for i in range(6)]
    group_res = call("layout.context_action", {
        "action": "Group selected",
        "cue_ids": child_ids,
    })
    # Find the group cue
    cues = call("cue.list")
    group = next(c for c in cues if c["_type_"] == "GroupCue")
    group_id = group["id"]

    # 3. Configure as playlist + shuffle=False (so no toggle-shuffle
    #    happens — we want to isolate the load-time behavior)
    call("cue.set_property", {
        "id": group_id, "property": "group_mode", "value": "playlist",
    })
    call("cue.set_property", {
        "id": group_id, "property": "shuffle", "value": False,
    })

    # 4. Capture the known-deterministic order, then enable shuffle.
    #    Setting shuffle True triggers an in-memory shuffle — we save
    #    AFTER that, so `saved_order` reflects what's on disk.
    call("cue.set_property", {
        "id": group_id, "property": "shuffle", "value": True,
    })
    time.sleep(0.3)
    saved_order = call("cue.get_property", {
        "id": group_id, "property": "children",
    })["value"]
    print(f"Order before save: {saved_order}")
    check("1: Group has 6 children before save", len(saved_order) == 6)

    # 5. Save + terminate LiSP
    call("session.save", {"path": SESSION_PATH})
    time.sleep(0.5)
    print("Terminating LiSP...")
    terminate()
    time.sleep(1.0)

    # 6. Verify save-file content
    with open(SESSION_PATH) as f:
        on_disk = json.load(f)
    on_disk_group = next(
        c for c in on_disk["cues"] if c.get("_type_") == "GroupCue"
    )
    check("2: On-disk shuffle is True",
          on_disk_group.get("shuffle") is True)
    check("2: On-disk children match saved_order",
          on_disk_group["children"] == saved_order)

    # 7. Relaunch LiSP with the saved session
    print("Relaunching LiSP with saved session...")
    launch(SESSION_PATH)
    print("LiSP ready.")
    time.sleep(1.0)

    # 8. Grab the group again and check its children order
    cues = call("cue.list")
    group = next(
        (c for c in cues if c["_type_"] == "GroupCue"), None,
    )
    check("3: Group exists after relaunch", group is not None)
    if group is None:
        terminate()
        _report()
        return

    reloaded = call("cue.get_property", {
        "id": group["id"], "property": "children",
    })["value"]
    print(f"Order after reload: {reloaded}")

    check("4: Shuffle property persisted",
          call("cue.get_property", {
              "id": group["id"], "property": "shuffle",
          })["value"] is True)

    check("4: Children count preserved after reload",
          len(reloaded) == len(saved_order))

    # The key check: order must differ (1/6! = 0.14% chance of same)
    check("5: Children reshuffled on session-load",
          reloaded != saved_order)

    # 9. UI indices match children order
    cue_by_id = {c["id"]: c for c in cues}
    ui_indices = [cue_by_id[cid]["index"] for cid in reloaded
                  if cid in cue_by_id]
    check("6: UI indices match children order after reload",
          ui_indices == sorted(ui_indices))

    terminate()
    _report()


def _report():
    print()
    print("═" * 40)
    print(f"  {_pass} passed, {_fail} failed")
    if _errors:
        print(f"  Failures: {', '.join(_errors)}")
    print("═" * 40)
    sys.exit(0 if _fail == 0 else 1)


if __name__ == "__main__":
    try:
        main()
    finally:
        terminate()
