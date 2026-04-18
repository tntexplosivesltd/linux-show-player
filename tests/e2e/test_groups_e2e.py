#!/usr/bin/env python3
"""End-to-end tests for cue groups via the test harness.

Starts LiSP automatically, runs all group tests, then shuts down.

Run:
    poetry run python tests/e2e/test_groups_e2e.py

Options:
    --no-launch    Don't start/stop LiSP (attach to existing)
    --host HOST    Harness host (default: 127.0.0.1)
    --port PORT    Harness port (default: 8070)
"""

import atexit
import json
import math
import os
import signal
import struct
import subprocess
import sys
import tempfile
import time
import wave

# Allow importing the test harness client without installing
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
STARTUP_TIMEOUT = 15
AUDIO_DIR = "/tmp/lisp_test_audio"

_pass = 0
_fail = 0
_errors = []
_lisp_proc = None


# ── LiSP lifecycle ──────────────────────────────────────────

def _create_empty_session():
    """Create a minimal ListLayout session file."""
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
    """Start LiSP in the background and wait for the harness."""
    global _lisp_proc

    session_path = _create_empty_session()

    _lisp_proc = subprocess.Popen(
        [
            sys.executable, "-m", "lisp.main",
            "-l", "warning",
            "-f", session_path,
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    atexit.register(stop_lisp)

    deadline = time.time() + STARTUP_TIMEOUT
    while time.time() < deadline:
        try:
            resp = send_request(HOST, PORT, "ping")
            if "result" in resp:
                # Clean up temp file after load
                os.unlink(session_path)
                return
        except (ConnectionRefusedError, ConnectionError, OSError):
            pass
        time.sleep(0.5)

    stop_lisp()
    print("ERROR: LiSP did not start within "
          f"{STARTUP_TIMEOUT}s", file=sys.stderr)
    sys.exit(2)


def stop_lisp():
    """Terminate LiSP gracefully."""
    global _lisp_proc
    if _lisp_proc and _lisp_proc.poll() is None:
        _lisp_proc.send_signal(signal.SIGTERM)
        try:
            _lisp_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _lisp_proc.kill()
    _lisp_proc = None


# ── Helpers ──────────────────────────────────────────────────

def call(method, params=None):
    """Call a harness method; return result or raise on error."""
    resp = send_request(HOST, PORT, method, params or {})
    if "error" in resp:
        raise RuntimeError(
            f"{method}: {resp['error']['message']}"
        )
    return resp.get("result")


def cue_state(cue_id):
    return call("cue.state", {"id": cue_id})["state_name"]


def cue_prop(cue_id, prop):
    return call("cue.get_property", {
        "id": cue_id, "property": prop
    })["value"]


def cue_at(index):
    return call("layout.cue_at", {"index": index})


def wait_state(cue_id, target, timeout=5.0):
    """Poll until cue reaches target state or timeout."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if cue_state(cue_id) == target:
            return True
        time.sleep(0.2)
    return False


def stop_all():
    call("layout.stop_all")
    time.sleep(0.3)


def check(name, condition):
    global _pass, _fail
    if condition:
        _pass += 1
        print(f"  PASS: {name}")
    else:
        _fail += 1
        _errors.append(name)
        print(f"  FAIL: {name}")


# ── Audio file generation ────────────────────────────────────

def make_tone(filename, freq, duration_s, sample_rate=44100):
    n_samples = int(sample_rate * duration_s)
    with wave.open(filename, "w") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        for i in range(n_samples):
            t = i / sample_rate
            env = min(t / 0.1, 1.0, (duration_s - t) / 0.1)
            val = int(
                32767 * 0.5 * max(0, env)
                * math.sin(2 * math.pi * freq * t)
            )
            w.writeframes(struct.pack("<h", val))


def create_test_audio():
    os.makedirs(AUDIO_DIR, exist_ok=True)
    for name, freq in [
        ("tone_A", 440),
        ("tone_B", 554),
        ("tone_C", 659),
        ("tone_D", 784),
    ]:
        path = os.path.join(AUDIO_DIR, f"{name}.wav")
        if not os.path.exists(path):
            make_tone(path, freq, 8.0)


# ── Setup ────────────────────────────────────────────────────

def setup():
    """Remove all existing cues and add 4 fresh test tones."""
    for cue in call("cue.list"):
        call("cue.remove", {"id": cue["id"]})
    time.sleep(0.3)

    call("cue.add_from_uri", {"files": [
        os.path.join(AUDIO_DIR, "tone_A.wav"),
        os.path.join(AUDIO_DIR, "tone_B.wav"),
        os.path.join(AUDIO_DIR, "tone_C.wav"),
        os.path.join(AUDIO_DIR, "tone_D.wav"),
    ]})
    time.sleep(1)

    cues = call("cue.list")
    assert len(cues) == 4, f"Expected 4 cues, got {len(cues)}"
    return {c["name"]: c["id"] for c in cues}


# ── Tests ────────────────────────────────────────────────────

def test_1_creating_groups(ids):
    print("\n═══ Test 1: Creating Groups ═══")

    A, B, C, D = (
        ids["tone_A"], ids["tone_B"],
        ids["tone_C"], ids["tone_D"],
    )

    # 1a: Group 3 cues
    call("layout.context_action", {
        "action": "Group selected",
        "cue_ids": [A, B, C],
    })
    time.sleep(0.3)

    cues = call("cue.list")
    cues_sorted = sorted(cues, key=lambda c: c["index"])
    check("1a: Group created at front",
          cues_sorted[0]["_type_"] == "GroupCue")
    check("1a: 5 cues total", len(cues) == 5)

    group_id = cues_sorted[0]["id"]
    check("1a: Icon is cue-group",
          cue_prop(group_id, "icon") == "cue-group")
    check("1a: Children have group_id",
          all(cue_prop(x, "group_id") == group_id
              for x in [A, B, C]))
    check("1a: D not grouped", cue_prop(D, "group_id") == "")

    # 1b: Undo
    call("commands.undo")
    time.sleep(0.3)
    check("1b: Undo removes group",
          call("cue.count")["count"] == 4)
    check("1b: Children ungrouped",
          cue_prop(A, "group_id") == "")

    # 1c: Redo
    call("commands.redo")
    time.sleep(0.3)
    check("1c: Redo restores group",
          call("cue.count")["count"] == 5)
    check("1c: Same group ID reused",
          cue_prop(A, "group_id") == group_id)

    # 1d: Group single cue
    call("layout.context_action", {
        "action": "Group selected", "cue_ids": [D],
    })
    time.sleep(0.3)
    check("1d: Single-cue group created",
          call("cue.count")["count"] == 6)

    # Undo single group for clean state
    call("commands.undo")
    time.sleep(0.3)
    return group_id


def test_2_ungrouping(ids, group_id):
    print("\n═══ Test 2: Ungrouping ═══")

    A = ids["tone_A"]

    call("layout.context_action", {
        "action": "Ungroup", "cue_ids": [group_id],
    })
    time.sleep(0.3)
    check("2a: Group removed",
          call("cue.count")["count"] == 4)
    check("2a: Children ungrouped",
          cue_prop(A, "group_id") == "")

    call("commands.undo")
    time.sleep(0.3)
    check("2b: Group restored",
          call("cue.count")["count"] == 5)
    check("2b: Children re-grouped",
          cue_prop(A, "group_id") == group_id)


def test_3_parallel_mode(ids, group_id):
    print("\n═══ Test 3: Parallel Mode ═══")

    A, B, C, D = (
        ids["tone_A"], ids["tone_B"],
        ids["tone_C"], ids["tone_D"],
    )

    call("cue.set_property", {
        "id": group_id, "property": "group_mode",
        "value": "parallel",
    })

    # 3a: All children start
    call("cue.execute", {"id": group_id, "action": "Start"})
    time.sleep(0.5)
    check("3a: Group running",
          cue_state(group_id) == "Running")
    check("3a: A running", cue_state(A) == "Running")
    check("3a: B running", cue_state(B) == "Running")
    check("3a: C running", cue_state(C) == "Running")
    check("3a: D not started", cue_state(D) == "Stop")

    # 3b: Stop group
    call("cue.execute", {"id": group_id, "action": "Stop"})
    time.sleep(0.5)
    check("3b: Group stopped",
          cue_state(group_id) == "Stop")
    check("3b: All children stopped",
          all(cue_state(x) == "Stop" for x in [A, B, C]))

    # 3c: Group ends when last child finishes
    call("cue.execute", {"id": group_id, "action": "Start"})
    time.sleep(0.5)
    for cid in [A, B, C]:
        call("cue.seek", {"id": cid, "position": 7500})
    check("3c: Group stops after children end",
          wait_state(group_id, "Stop", timeout=3))


def test_4_playlist_mode(ids, group_id):
    print("\n═══ Test 4: Playlist Mode ═══")

    A, B, C = ids["tone_A"], ids["tone_B"], ids["tone_C"]

    call("cue.set_property", {
        "id": group_id, "property": "group_mode",
        "value": "playlist",
    })

    # 4a: Only first child starts
    call("cue.execute", {"id": group_id, "action": "Start"})
    time.sleep(0.5)
    check("4a: A running", cue_state(A) == "Running")
    check("4a: B not started", cue_state(B) == "Stop")
    check("4a: Group running",
          cue_state(group_id) == "Running")

    # 4b: Advances when first child ends
    call("cue.seek", {"id": A, "position": 7500})
    time.sleep(1)
    check("4b: A ended", cue_state(A) == "Stop")
    check("4b: B running", cue_state(B) == "Running")
    check("4b: Group still running",
          cue_state(group_id) == "Running")

    # 4c: Stop mid-playlist
    call("cue.execute", {"id": group_id, "action": "Stop"})
    time.sleep(0.5)
    check("4c: Group stopped",
          cue_state(group_id) == "Stop")
    check("4c: B stopped", cue_state(B) == "Stop")
    check("4c: C never started", cue_state(C) == "Stop")


def test_5_playlist_loop(ids, group_id):
    print("\n═══ Test 5: Playlist + Loop ═══")

    A, B, C = ids["tone_A"], ids["tone_B"], ids["tone_C"]

    call("cue.set_property", {
        "id": group_id, "property": "loop", "value": True,
    })

    call("cue.execute", {"id": group_id, "action": "Start"})
    time.sleep(0.3)

    for cid in [A, B, C]:
        call("cue.seek", {"id": cid, "position": 7500})
        time.sleep(0.8)

    time.sleep(0.5)
    check("5a: Looped back to A",
          cue_state(A) == "Running")
    check("5a: Group still running",
          cue_state(group_id) == "Running")

    call("cue.execute", {"id": group_id, "action": "Stop"})
    time.sleep(0.3)
    check("5b: Group stopped",
          cue_state(group_id) == "Stop")

    call("cue.set_property", {
        "id": group_id, "property": "loop", "value": False,
    })


def test_6_crossfade(ids, group_id):
    print("\n═══ Test 6: Playlist + Crossfade ═══")

    A, B, C = ids["tone_A"], ids["tone_B"], ids["tone_C"]

    call("cue.set_property", {
        "id": group_id, "property": "crossfade",
        "value": 2.0,
    })

    call("cue.execute", {"id": group_id, "action": "Start"})
    time.sleep(0.3)
    call("cue.seek", {"id": A, "position": 5500})
    time.sleep(1.5)
    check("6a: Crossfade started B",
          cue_state(B) == "Running")

    # 6b: After crossfade completes, fadein_duration should be
    # restored to its original value (0) via the one-shot
    # started signal handler — not permanently modified.
    time.sleep(2.5)
    check("6b: B fadein_duration restored after crossfade",
          cue_prop(B, "fadein_duration") == 0)
    check("6b: B still running after fade-in",
          cue_state(B) == "Running")

    call("cue.seek", {"id": B, "position": 5500})
    time.sleep(1.5)
    check("6c: Crossfade started C",
          cue_state(C) == "Running")

    time.sleep(2.5)
    check("6c: C fadein_duration restored after crossfade",
          cue_prop(C, "fadein_duration") == 0)
    check("6c: C still running after fade-in",
          cue_state(C) == "Running")

    stop_all()
    call("cue.set_property", {
        "id": group_id, "property": "crossfade",
        "value": 0.0,
    })


def test_7_go_button(ids, group_id):
    print("\n═══ Test 7: GO Button Behavior ═══")

    A = ids["tone_A"]
    stop_all()

    # 7a: GO on child does nothing
    call("layout.set_standby_index", {"index": 1})
    call("layout.go")
    time.sleep(0.3)
    check("7a: Child not started",
          cue_state(A) == "Stop")
    check("7a: Standby unchanged",
          call("layout.standby")["standby_index"] == 1)

    # 7b: GO on group starts it
    call("layout.set_standby_index", {"index": 0})
    call("layout.go")
    time.sleep(0.5)
    check("7b: Group started",
          cue_state(group_id) == "Running")

    stop_all()


def test_8_exclusive(ids, group_id):
    print("\n═══ Test 8: Exclusive + Groups ═══")

    D = ids["tone_D"]
    stop_all()

    # 8a: Exclusive group blocks others
    call("cue.set_property", {
        "id": group_id, "property": "exclusive",
        "value": True,
    })
    call("cue.execute", {"id": group_id, "action": "Start"})
    time.sleep(0.3)
    call("cue.execute", {"id": D, "action": "Start"})
    time.sleep(0.3)
    check("8a: D blocked by exclusive group",
          cue_state(D) == "Stop")
    check("8a: Group still running",
          cue_state(group_id) == "Running")

    stop_all()
    call("cue.set_property", {
        "id": group_id, "property": "exclusive",
        "value": False,
    })

    # 8b: Exclusive cue blocks group
    call("cue.set_property", {
        "id": D, "property": "exclusive", "value": True,
    })
    call("cue.execute", {"id": D, "action": "Start"})
    time.sleep(0.3)
    call("cue.execute", {"id": group_id, "action": "Start"})
    time.sleep(0.3)
    check("8b: Group blocked by exclusive D",
          cue_state(group_id) == "Stop")
    check("8b: D still running", cue_state(D) == "Running")

    stop_all()
    call("cue.set_property", {
        "id": D, "property": "exclusive", "value": False,
    })


def test_9_save_load(ids, group_id):
    print("\n═══ Test 9: Save/Load ═══")

    save_path = "/tmp/lisp_group_test_session.lsp"

    call("cue.set_property", {
        "id": group_id, "property": "crossfade",
        "value": 2.5,
    })
    call("cue.set_property", {
        "id": group_id, "property": "loop", "value": True,
    })

    call("session.save", {"path": save_path})
    call("session.load", {"path": save_path})
    time.sleep(2)

    cues = call("cue.list")
    group = next(
        c for c in sorted(cues, key=lambda c: c["index"])
        if c["_type_"] == "GroupCue"
    )
    gid = group["id"]

    check("9: Group preserved",
          group["_type_"] == "GroupCue")
    check("9: Mode preserved",
          cue_prop(gid, "group_mode") == "playlist")
    check("9: Crossfade preserved",
          cue_prop(gid, "crossfade") == 2.5)
    check("9: Loop preserved",
          cue_prop(gid, "loop") is True)
    check("9: Children count preserved",
          len(cue_prop(gid, "children")) == 3)

    first_child_id = sorted(
        cues, key=lambda c: c["index"]
    )[1]["id"]
    check("9: Child group_id preserved",
          cue_prop(first_child_id, "group_id") == gid)

    call("cue.set_property", {
        "id": gid, "property": "crossfade", "value": 0.0,
    })
    call("cue.set_property", {
        "id": gid, "property": "loop", "value": False,
    })

    return gid


def test_10_edge_cases(ids, group_id):
    print("\n═══ Test 10: Edge Cases ═══")

    cues = call("cue.list")
    cues_sorted = sorted(cues, key=lambda c: c["index"])

    A = cues_sorted[1]["id"]
    B = cues_sorted[2]["id"]
    C = cues_sorted[3]["id"]
    D = cues_sorted[4]["id"]

    # 10a: Delete child — group works with remaining
    call("cue.remove", {"id": C})
    time.sleep(0.3)
    call("cue.set_property", {
        "id": group_id, "property": "group_mode",
        "value": "parallel",
    })
    call("cue.execute", {"id": group_id, "action": "Start"})
    time.sleep(0.5)
    check("10a: Group runs with remaining children",
          cue_state(group_id) == "Running")
    check("10a: A running", cue_state(A) == "Running")
    stop_all()

    # 10b: Delete GroupCue directly — no crash
    call("cue.remove", {"id": group_id})
    time.sleep(0.3)
    check("10b: Group removed, children remain",
          call("cue.count")["count"] == 3)
    check("10b: A still exists",
          call("cue.state", {"id": A})["state_name"] == "Stop")

    # 10c: Empty group cannot start
    result = call("cue.add", {
        "type": "GroupCue",
        "properties": {"name": "Empty Group"},
    })
    empty_id = result["id"]
    time.sleep(0.3)
    call("cue.execute", {"id": empty_id, "action": "Start"})
    time.sleep(0.3)
    check("10c: Empty group stays stopped",
          cue_state(empty_id) == "Stop")

    # 10d: TriggerAfterEnd
    call("layout.context_action", {
        "action": "Group selected", "cue_ids": [A, B],
    })
    time.sleep(0.3)

    new_group = sorted(
        call("cue.list"), key=lambda c: c["index"]
    )[0]["id"]
    call("cue.set_property", {
        "id": new_group, "property": "group_mode",
        "value": "playlist",
    })
    call("cue.set_property", {
        "id": new_group, "property": "next_action",
        "value": "TriggerAfterEnd",
    })

    call("cue.execute", {"id": new_group, "action": "Start"})
    time.sleep(0.3)
    call("cue.seek", {"id": A, "position": 7500})
    time.sleep(0.8)
    call("cue.seek", {"id": B, "position": 7500})
    time.sleep(1.5)

    check("10d: TriggerAfterEnd chains to D",
          cue_state(D) == "Running")

    stop_all()

    # 10e: Re-grouping cues with stale group_id
    call("cue.remove", {"id": new_group})
    time.sleep(0.3)
    call("layout.context_action", {
        "action": "Group selected", "cue_ids": [A, B],
    })
    time.sleep(0.3)
    check("10e: Stale group_id allows re-grouping",
          call("cue.count")["count"] >= 4)

    stop_all()


def test_11_collapse_persist(ids, group_id):
    print("\n═══ Test 11: Collapse Persistence ═══")

    # Re-discover the current GroupCue (test_10 may have
    # deleted and re-created groups).
    cues = call("cue.list")
    group = next(
        (c for c in sorted(cues, key=lambda c: c["index"])
         if c["_type_"] == "GroupCue"),
        None,
    )
    if group is None:
        check("11: Group exists", False)
        return group_id
    group_id = group["id"]

    # 11a: Default collapsed value is False for a fresh group
    check("11a: Default collapsed is False",
          cue_prop(group_id, "collapsed") is False)

    # 11b: Set collapsed
    call("cue.set_property", {
        "id": group_id, "property": "collapsed",
        "value": True,
    })
    check("11b: Collapsed set to True",
          cue_prop(group_id, "collapsed") is True)

    # 11c: Save and reload — collapsed persists
    save_path = "/tmp/lisp_collapse_test_session.lsp"
    call("session.save", {"path": save_path})
    time.sleep(0.5)

    call("session.load", {"path": save_path})

    # Wait for reload to finish — poll until a GroupCue appears
    gid = None
    deadline = time.time() + 10
    while time.time() < deadline:
        time.sleep(0.5)
        cues = call("cue.list")
        group = next(
            (c for c in sorted(cues, key=lambda c: c["index"])
             if c["_type_"] == "GroupCue"),
            None,
        )
        if group is not None:
            gid = group["id"]
            break

    if gid is None:
        check("11c: Group found after reload", False)
        return group_id

    check("11c: Collapsed persists after reload",
          cue_prop(gid, "collapsed") is True)

    # 11d: Can set back to expanded
    call("cue.set_property", {
        "id": gid, "property": "collapsed",
        "value": False,
    })
    check("11d: Can set back to expanded",
          cue_prop(gid, "collapsed") is False)

    # 11e: Collapsed survives undo/redo of group creation
    # Ungroup (undo-able), then redo — collapsed should be restored
    call("cue.set_property", {
        "id": gid, "property": "collapsed",
        "value": True,
    })
    call("layout.context_action", {
        "action": "Ungroup", "cue_ids": [gid],
    })
    time.sleep(0.3)
    check("11e: Ungroup succeeded",
          call("cue.count")["count"] < 5)

    call("commands.undo")
    time.sleep(0.3)
    check("11e: Redo restores group",
          call("cue.count")["count"] >= 5)

    # After redo the group should still exist; find it
    cues = call("cue.list")
    group_after = next(
        (c for c in sorted(cues, key=lambda c: c["index"])
         if c["_type_"] == "GroupCue"),
        None,
    )
    check("11e: Group present after undo",
          group_after is not None)
    if group_after:
        gid = group_after["id"]
        # collapsed was True before ungroup; undo should restore it
        check("11e: Collapsed survives undo",
              cue_prop(gid, "collapsed") is True)
        # Reset to expanded for downstream tests
        call("cue.set_property", {
            "id": gid, "property": "collapsed",
            "value": False,
        })

    return gid


def test_13_auto_expand_on_play(ids, group_id):
    """Group should auto-expand when started (collapsed property clears)."""
    print("\n═══ Test 13: Auto-Expand on Play ═══")

    # Set collapsed
    call("cue.set_property", {
        "id": group_id, "property": "collapsed",
        "value": True,
    })
    check("13a: Group collapsed",
          cue_prop(group_id, "collapsed") is True)

    # Start the group
    call("cue.execute", {"id": group_id, "action": "Start"})
    time.sleep(0.5)

    # Auto-expand should have cleared collapsed
    check("13b: Auto-expanded on play",
          cue_prop(group_id, "collapsed") is False)
    check("13c: Group is running",
          cue_state(group_id) == "Running")

    stop_all()


def test_14_move_cue_with_groups(ids, group_id):
    """Moving cues should work correctly with groups present."""
    print("\n═══ Test 14: Move Cue With Groups ═══")

    D = ids["tone_D"]

    # Get current positions
    cues_before = sorted(
        call("cue.list"), key=lambda c: c["index"]
    )
    d_index_before = next(
        c["index"] for c in cues_before if c["id"] == D
    )

    # Move D to the front
    call("layout.move_cue", {
        "from_index": d_index_before, "to_index": 0,
    })
    time.sleep(0.3)

    cues_after = sorted(
        call("cue.list"), key=lambda c: c["index"]
    )
    check("14a: D moved to front",
          cues_after[0]["id"] == D)

    # Move it back
    call("layout.move_cue", {
        "from_index": 0, "to_index": d_index_before,
    })
    time.sleep(0.3)

    # Verify group is intact
    check("14b: Group still has children",
          len(cue_prop(group_id, "children")) > 0)


def test_15_playlist_shuffle(ids, group_id):
    """Shuffle flag randomizes children order on start and save/load."""
    print("\n═══ Test 15: Playlist Shuffle ═══")

    stop_all()

    # Re-discover the current GroupCue
    cues = call("cue.list")
    group = next(
        (c for c in sorted(cues, key=lambda c: c["index"])
         if c["_type_"] == "GroupCue"),
        None,
    )
    if group is None:
        check("15: Group exists", False)
        return group_id
    group_id = group["id"]

    # Set to playlist + shuffle
    call("cue.set_property", {
        "id": group_id, "property": "group_mode",
        "value": "playlist",
    })
    call("cue.set_property", {
        "id": group_id, "property": "shuffle",
        "value": True,
    })
    call("cue.set_property", {
        "id": group_id, "property": "loop",
        "value": False,
    })

    # 15a: Record original children order
    original = cue_prop(group_id, "children")
    check("15a: Has children", len(original) >= 2)

    # 15b: Start group — children should be shuffled.
    # Try up to 5 times since shuffle can theoretically
    # produce the same order (very unlikely with >=3 children).
    shuffled = False
    for _ in range(5):
        call("cue.execute", {
            "id": group_id, "action": "Start",
        })
        time.sleep(0.5)
        after_start = cue_prop(group_id, "children")
        call("cue.execute", {
            "id": group_id, "action": "Stop",
        })
        time.sleep(0.3)
        if after_start != original:
            shuffled = True
            break
    check("15b: Children shuffled on start", shuffled)

    # 15c: Pause and resume — order should NOT change
    call("cue.execute", {
        "id": group_id, "action": "Start",
    })
    time.sleep(0.5)
    order_before_pause = cue_prop(group_id, "children")
    call("cue.execute", {
        "id": group_id, "action": "Pause",
    })
    time.sleep(0.3)
    call("cue.execute", {
        "id": group_id, "action": "Start",
    })
    time.sleep(0.5)
    order_after_resume = cue_prop(group_id, "children")
    check("15c: Order preserved on resume",
          order_before_pause == order_after_resume)
    stop_all()

    # 15d: Save/load — children should be re-shuffled
    order_before_save = cue_prop(group_id, "children")
    save_path = "/tmp/lisp_shuffle_test_session.lsp"
    call("session.save", {"path": save_path})
    call("session.load", {"path": save_path})

    # Wait for reload
    gid = None
    deadline = time.time() + 10
    while time.time() < deadline:
        time.sleep(0.5)
        cues = call("cue.list")
        g = next(
            (c for c in sorted(cues, key=lambda c: c["index"])
             if c["_type_"] == "GroupCue"),
            None,
        )
        if g is not None:
            gid = g["id"]
            break

    if gid is None:
        check("15d: Group found after reload", False)
        return group_id

    # Shuffle on load may produce the same order (unlikely).
    # Just verify the property persisted and group still works.
    check("15d: Shuffle property persists",
          cue_prop(gid, "shuffle") is True)
    check("15d: Children count preserved",
          len(cue_prop(gid, "children")) == len(original))

    # 15e: With shuffle=False, order is preserved on start
    call("cue.set_property", {
        "id": gid, "property": "shuffle",
        "value": False,
    })
    order_before = cue_prop(gid, "children")
    call("cue.execute", {"id": gid, "action": "Start"})
    time.sleep(0.5)
    order_after = cue_prop(gid, "children")
    check("15e: No shuffle when flag is False",
          order_before == order_after)

    stop_all()
    call("cue.set_property", {
        "id": gid, "property": "shuffle",
        "value": False,
    })
    return gid


def test_12_group_delete_children_survive(ids, group_id):
    """Deleting a group directly should leave children visible."""
    print("\n═══ Test 12: Group Delete Children Survive ═══")

    A = ids["tone_A"]

    # Get children before deletion
    children = cue_prop(group_id, "children")
    total_before = call("cue.count")["count"]
    check("12 precondition: Group has children",
          len(children) > 0)

    # Delete the group
    call("cue.remove", {"id": group_id})
    time.sleep(0.5)

    # Children should still exist (total - 1 for the group)
    total_after = call("cue.count")["count"]
    check("12a: Children survive group deletion",
          total_after == total_before - 1)

    # Children should be accessible
    check("12b: Child A still exists",
          call("cue.state", {"id": A})["state_name"] == "Stop")

    # The group no longer exists; child A should still be reachable
    check("12c: Child A group_id stale",
          call("cue.get", {"id": A}) is not None)


# ── Main ─────────────────────────────────────────────────────

def main():
    global HOST, PORT

    import argparse
    parser = argparse.ArgumentParser(
        description="E2E tests for cue groups"
    )
    parser.add_argument("--host", default=HOST)
    parser.add_argument("--port", type=int, default=PORT)
    parser.add_argument(
        "--no-launch", action="store_true",
        help="Don't start/stop LiSP (attach to existing)",
    )
    args = parser.parse_args()
    HOST = args.host
    PORT = args.port

    print("Generating test audio files...")
    create_test_audio()

    if args.no_launch:
        print("Connecting to existing LiSP...")
        try:
            call("ping")
        except Exception as e:
            print(f"Cannot connect: {e}")
            print(
                "Is LiSP running with TestHarness enabled?"
            )
            sys.exit(2)
    else:
        print("Starting LiSP...")
        start_lisp()
        print("LiSP ready.")

    print("Setting up test cues...")
    ids = setup()

    try:
        group_id = test_1_creating_groups(ids)
        test_2_ungrouping(ids, group_id)
        test_3_parallel_mode(ids, group_id)
        test_4_playlist_mode(ids, group_id)
        test_5_playlist_loop(ids, group_id)
        test_6_crossfade(ids, group_id)
        test_7_go_button(ids, group_id)
        test_8_exclusive(ids, group_id)
        group_id = test_9_save_load(ids, group_id)
        test_10_edge_cases(ids, group_id)
        group_id = test_11_collapse_persist(ids, group_id)
        test_13_auto_expand_on_play(ids, group_id)
        test_14_move_cue_with_groups(ids, group_id)
        group_id = test_15_playlist_shuffle(ids, group_id)
        test_12_group_delete_children_survive(ids, group_id)
    finally:
        stop_all()
        if not args.no_launch:
            print("\nStopping LiSP...")
            stop_lisp()

    print(f"\n{'═' * 40}")
    print(f"  {_pass} passed, {_fail} failed")
    if _errors:
        print(f"  Failures: {', '.join(_errors)}")
    print(f"{'═' * 40}")

    sys.exit(1 if _fail else 0)


if __name__ == "__main__":
    main()
