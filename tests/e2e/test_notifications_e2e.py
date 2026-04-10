#!/usr/bin/env python3
"""End-to-end tests for toast notifications via the test harness.

Starts LiSP automatically, tests that exclusive cue blocking produces
notifications via the Application.notify signal, then shuts down.

Run:
    poetry run python tests/e2e/test_notifications_e2e.py

Options:
    --no-launch    Don't start/stop LiSP (attach to existing)
    --host HOST    Harness host (default: 127.0.0.1)
    --port PORT    Harness port (default: 8070)
"""

import argparse
import math
import os
import struct
import sys
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

# Reuse LiSP lifecycle helpers from the groups E2E suite
sys.path.insert(0, os.path.dirname(__file__))
from test_groups_e2e import (  # noqa: E402
    start_lisp,
    stop_lisp,
    stop_all,
)

_HOST = "127.0.0.1"
_PORT = 8070
AUDIO_DIR = "/tmp/lisp_test_audio"

_pass = 0
_fail = 0
_errors = []


# ── Helpers ──────────────────────────────────────────────────

def call(method, params=None):
    resp = send_request(_HOST, _PORT, method, params or {})
    if "error" in resp:
        raise RuntimeError(
            f"{method}: {resp['error']['message']}"
        )
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


def wait_state(cue_id, target, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        state = call(
            "cue.state", {"id": cue_id}
        )["state_name"]
        if state == target:
            return True
        time.sleep(0.2)
    return False


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
    path = os.path.join(AUDIO_DIR, "tone_notify.wav")
    if not os.path.exists(path):
        make_tone(path, 440, 8.0)
    return path


# ── Setup ────────────────────────────────────────────────────

def setup():
    """Remove all cues and add 2 fresh ones."""
    for cue in call("cue.list"):
        call("cue.remove", {"id": cue["id"]})
    time.sleep(0.3)

    audio_path = create_test_audio()

    call("cue.add_from_uri", {"files": [audio_path, audio_path]})
    time.sleep(1)

    cues = call("cue.list")
    assert len(cues) == 2, f"Expected 2 cues, got {len(cues)}"
    return cues[0]["id"], cues[1]["id"]


# ── Tests ────────────────────────────────────────────────────

def test_exclusive_notification(cue_a, cue_b):
    """Blocking a cue start via exclusive mode emits a notification."""
    print("\n=== Test: Exclusive cue notification ===")

    # Mark cue A as exclusive
    call("cue.set_property", {
        "id": cue_a, "property": "exclusive", "value": True,
    })

    # Subscribe to the notify signal
    sub = call("signals.subscribe", {
        "signal": "app.notify",
    })
    sub_id = sub["subscription_id"]

    # Start cue A (exclusive)
    call("cue.execute", {"id": cue_a})
    reached = wait_state(cue_a, "Running")
    check("Exclusive cue A is running", reached)

    # Try to start cue B — should be blocked
    call("cue.execute", {"id": cue_b})
    time.sleep(1.0)

    b_state = call("cue.state", {"id": cue_b})["state_name"]
    check("Cue B was blocked (not running)", b_state != "Running")

    # Check that a notification was emitted (poll buffered events)
    result = call("signals.poll", {
        "subscription_id": sub_id,
    })

    got_notification = False
    for event in result.get("events", []):
        args = event.get("args", [])
        if args and "Blocked by exclusive" in str(args[0]):
            got_notification = True
            break

    check("Notification emitted for blocked cue", got_notification)

    # Cleanup
    stop_all()
    call("cue.set_property", {
        "id": cue_a, "property": "exclusive", "value": False,
    })
    call("signals.unsubscribe", {"subscription_id": sub_id})


def test_exclusive_dedup(cue_a, cue_b):
    """Multiple blocked starts emit multiple notify signals."""
    print("\n=== Test: Exclusive notification dedup ===")

    call("cue.set_property", {
        "id": cue_a, "property": "exclusive", "value": True,
    })

    sub = call("signals.subscribe", {"signal": "app.notify"})
    sub_id = sub["subscription_id"]

    # Start exclusive cue
    call("cue.execute", {"id": cue_a})
    wait_state(cue_a, "Running")

    # Try to start cue B three times
    for _ in range(3):
        call("cue.execute", {"id": cue_b})
        time.sleep(0.3)

    time.sleep(1.0)

    result = call("signals.poll", {
        "subscription_id": sub_id,
    })

    notify_count = 0
    for event in result.get("events", []):
        args = event.get("args", [])
        if args and "Blocked by exclusive" in str(args[0]):
            notify_count += 1

    check(
        "Multiple notify signals emitted (>=2)",
        notify_count >= 2,
    )

    # Cleanup
    stop_all()
    call("cue.set_property", {
        "id": cue_a, "property": "exclusive", "value": False,
    })
    call("signals.unsubscribe", {"subscription_id": sub_id})


# ── Main ─────────────────────────────────────────────────────

def main():
    global _HOST, _PORT

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--no-launch", action="store_true",
        help="Don't start/stop LiSP",
    )
    parser.add_argument("--host", default=_HOST)
    parser.add_argument("--port", type=int, default=_PORT)
    args = parser.parse_args()

    _HOST = args.host
    _PORT = args.port

    if not args.no_launch:
        create_test_audio()
        print("Starting LiSP...")
        start_lisp()
        print("LiSP ready.\n")

    cue_a, cue_b = setup()

    try:
        test_exclusive_notification(cue_a, cue_b)
        test_exclusive_dedup(cue_a, cue_b)
    finally:
        stop_all()
        if not args.no_launch:
            print("\nStopping LiSP...")
            stop_lisp()

    print(f"\n{'=' * 40}")
    print(f"  {_pass} passed, {_fail} failed")
    if _errors:
        print(f"  Failures: {', '.join(_errors)}")
    print(f"{'=' * 40}")

    sys.exit(1 if _fail else 0)


if __name__ == "__main__":
    main()
