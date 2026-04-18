"""Shared helpers for E2E tests.

Provides connection config, LiSP lifecycle management, JSON-RPC
helpers, audio generation, setup utilities, and a test tracker.

Typical usage in a test file::

    from tests.e2e.helpers import run_suite, call, setup_with_tones

    def run_tests(t):
        ids = setup_with_tones()
        t.check("cue added", len(ids) == 4)
        ...

    if __name__ == "__main__":
        run_suite("My Test Suite", run_tests)
"""

import argparse
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
from contextlib import contextmanager

# Allow importing the test harness client without installing
sys.path.insert(
    0,
    os.path.join(
        os.path.dirname(__file__), "..", "..", "lisp", "plugins",
        "test_harness",
    ),
)
from client import send_request  # noqa: E402

# ── Connection config ──────────────────────────────────────────

HOST = "127.0.0.1"
PORT = 8070
STARTUP_TIMEOUT = 15

# ── Audio config ───────────────────────────────────────────────

AUDIO_DIR = "/tmp/lisp_test_audio"

# ── Internal state ─────────────────────────────────────────────

_lisp_proc = None


# ── LiSP lifecycle ─────────────────────────────────────────────

def _create_empty_session(layout="ListLayout"):
    """Create a minimal session file with the given layout type."""
    session = {
        "meta": {"version": "0.6"},
        "session": {"layout_type": layout},
        "cues": [],
    }
    fd, path = tempfile.mkstemp(suffix=".lsp")
    with os.fdopen(fd, "w") as f:
        json.dump(session, f)
    return path


def start_lisp(layout="ListLayout"):
    """Start LiSP with the given layout and wait for the harness."""
    global _lisp_proc

    session_path = _create_empty_session(layout)

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
                # Wait for session to fully load before proceeding.
                # session.info returns {"has_session": False} before
                # the session file loads — the harness registers
                # before the session is attached, so a successful
                # JSON-RPC result is not enough.
                try:
                    info = send_request(
                        HOST, PORT, "session.info"
                    )
                    result = info.get("result") or {}
                    if result.get("has_session"):
                        os.unlink(session_path)
                        return
                except Exception:
                    pass
        except (ConnectionRefusedError, ConnectionError, OSError):
            pass
        time.sleep(0.5)

    stop_lisp()
    print(
        f"ERROR: LiSP did not start within {STARTUP_TIMEOUT}s",
        file=sys.stderr,
    )
    sys.exit(2)


def stop_lisp():
    """Terminate LiSP gracefully."""
    global _lisp_proc
    if _lisp_proc is None:
        return
    if _lisp_proc.poll() is None:
        _lisp_proc.send_signal(signal.SIGTERM)
        try:
            _lisp_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _lisp_proc.kill()
    _lisp_proc = None


# ── JSON-RPC helpers ───────────────────────────────────────────

def call(method, params=None):
    """Call a harness method; return result or raise on error."""
    resp = send_request(HOST, PORT, method, params or {})
    if "error" in resp:
        raise RuntimeError(
            f"{method}: {resp['error']['message']}"
        )
    return resp.get("result")


def cue_state(cue_id):
    """Return state name string for a cue."""
    return call("cue.state", {"id": cue_id})["state_name"]


def cue_prop(cue_id, prop):
    """Return a cue property value."""
    return call("cue.get_property", {
        "id": cue_id, "property": prop,
    })["value"]


def cue_at(index):
    """Return cue dict at model index."""
    return call("layout.cue_at", {"index": index})


def wait_state(cue_id, target, timeout=5.0):
    """Poll until cue reaches target state or timeout."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if cue_state(cue_id) == target:
            return True
        time.sleep(0.2)
    return False


# ── Signal-based waits (preferred over polling) ──────────────

def subscribe_cue(cue_id, signal_name):
    """Subscribe to a per-cue signal; return subscription id.

    Per-cue signals: started, stopped, paused, interrupted,
    error, end, next, fadein_start/end, fadeout_start/end,
    prewait_start/ended/paused/stopped,
    postwait_start/ended/paused/stopped, property_changed.
    """
    sub = call("signals.subscribe", {
        "signal": f"cue.{signal_name}",
        "cue_id": cue_id,
    })
    return sub["subscription_id"]


def subscribe(signal_path):
    """Subscribe to a global signal path (e.g. 'cue_model.item_added')."""
    sub = call("signals.subscribe", {"signal": signal_path})
    return sub["subscription_id"]


def wait_for_signal(sub_id, timeout=5.0, match=None):
    """Block until the subscribed signal fires, or timeout.

    Returns the event dict on success, or None on timeout.  All
    other harness errors propagate.  Use this instead of
    ``wait_state`` when the test has already subscribed BEFORE
    triggering the action that causes the state change.
    """
    params = {"subscription_id": sub_id, "timeout": timeout}
    if match is not None:
        params["match"] = match
    try:
        return call("signals.wait_for", params)
    except RuntimeError as e:
        msg = str(e).lower()
        if "timed out" in msg or "timeout" in msg:
            return None
        raise


def unsubscribe(sub_id):
    """Release a subscription; silently ignores 'not found'."""
    try:
        call("signals.unsubscribe", {"subscription_id": sub_id})
    except RuntimeError:
        pass


@contextmanager
def cue_signal(cue_id, signal_name):
    """Subscribe, yield the subscription id, unsubscribe on exit.

    Typical pattern::

        with cue_signal(cue_id, "started") as sub:
            call("cue.start", {"id": cue_id})
            assert wait_for_signal(sub, timeout=5)
    """
    sub_id = subscribe_cue(cue_id, signal_name)
    try:
        yield sub_id
    finally:
        unsubscribe(sub_id)


@contextmanager
def signal_sub(signal_path):
    """Context manager variant of ``subscribe`` for global signals."""
    sub_id = subscribe(signal_path)
    try:
        yield sub_id
    finally:
        unsubscribe(sub_id)


def stop_all():
    """Stop all cues and wait briefly."""
    call("layout.stop_all")
    time.sleep(0.3)


# ── Test tracking ──────────────────────────────────────────────

class TestTracker:
    """Tracks pass/fail counts and error names."""

    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.errors = []

    def check(self, name, condition):
        """Assert with pass/fail tracking and printing."""
        if condition:
            self.passed += 1
            print(f"  PASS: {name}")
        else:
            self.failed += 1
            self.errors.append(name)
            print(f"  FAIL: {name}")

    def summary(self):
        """Print final summary and return exit code."""
        print(f"\n{'=' * 40}")
        print(f"  {self.passed} passed, {self.failed} failed")
        if self.errors:
            print(f"  Failures: {', '.join(self.errors)}")
        print(f"{'=' * 40}")
        return 1 if self.failed else 0


# ── Audio generation ───────────────────────────────────────────

def make_tone(filename, freq, duration_s, sample_rate=44100):
    """Generate a sine wave WAV file."""
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
    """Create standard test tones A/B/C/D (8s each)."""
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


# ── Setup helpers ──────────────────────────────────────────────

def clear_cues():
    """Remove all cues from the session."""
    for cue in call("cue.list"):
        call("cue.remove", {"id": cue["id"]})
    time.sleep(0.3)


def add_test_tones():
    """Add 4 standard test tones and return {name: id} dict."""
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


def setup_with_tones():
    """Clear cues, add 4 standard test tones, return {name: id}."""
    clear_cues()
    return add_test_tones()


# ── CLI helpers ────────────────────────────────────────────────

def parse_args(description):
    """Parse --host, --port, --no-launch args. Return args namespace."""
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--host", default=HOST)
    parser.add_argument("--port", type=int, default=PORT)
    parser.add_argument(
        "--no-launch", action="store_true",
        help="Don't start/stop LiSP (attach to existing)",
    )
    return parser.parse_args()


def run_suite(description, test_fn, layout="ListLayout"):
    """Full lifecycle: parse args, start LiSP, run test_fn, exit.

    Parses --host/--port/--no-launch, generates test audio, starts
    (or attaches to) LiSP, calls test_fn(tracker), prints summary,
    and exits with code 0 (all passed) or 1 (any failures).

    test_fn receives a single TestTracker argument.
    """
    global HOST, PORT

    args = parse_args(description)
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
            print("Is LiSP running with TestHarness enabled?")
            sys.exit(2)
    else:
        print("Starting LiSP...")
        start_lisp(layout)
        print("LiSP ready.")

    t = TestTracker()
    try:
        test_fn(t)
    finally:
        stop_all()
        if not args.no_launch:
            print("\nStopping LiSP...")
            stop_lisp()

    sys.exit(t.summary())
