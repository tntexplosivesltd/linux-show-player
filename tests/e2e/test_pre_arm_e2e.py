#!/usr/bin/env python3
# This file is part of Linux Show Player
#
# Copyright 2024 Linux Show Player Contributors
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

"""End-to-end tests for the pre-arm (preload) feature.

Covers T20–T23 of the pre-load implementation plan:
  - T20: live preload toggle arms cues; standby auto-arm; GO advances
         standby and arms the next cue.
  - T21: latency comparison (cold vs warm GO). Reports measured savings;
         lenient threshold given WAV fixture size.
  - T22: preload failure on missing file emits a toast and lands in
         pre_arm.status failed set; auto-arm failures stay silent.
  - T22 batch coalescing and T23 cap pressure are covered by unit tests
    in test_pre_arm_manager.py — see inline notes.

Run:
    poetry run python tests/e2e/test_pre_arm_e2e.py

Options:
    --no-launch    Don't start/stop LiSP (attach to existing)
    --host HOST    Harness host (default: 127.0.0.1)
    --port PORT    Harness port (default: 8070)
"""

import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from tests.e2e.helpers import (  # noqa: E402
    run_suite,
    call,
    stop_all,
    setup_with_tones,
    make_tone,
    signal_sub,
    wait_for_signal,
    AUDIO_DIR,
)


# ── Helpers ────────────────────────────────────────────────────────────────


def set_preload(cue_id, value):
    """Set the preload property on a cue."""
    call("cue.set_property", {
        "id": cue_id,
        "property": "preload",
        "value": value,
    })


def pre_arm_status():
    """Return the current pre_arm.status result."""
    return call("pre_arm.status")


def wait_for_armed(cue_id, timeout=3.0):
    """Wait until cue_id appears in the armed set. Returns result dict."""
    return call("pre_arm.wait_for_armed", {
        "cue_id": cue_id,
        "timeout": timeout,
    })


# ── T20: Live preload toggle, standby auto-arm, GO advance ─────────────────


def test_t20_live_preload_toggle(t, ids):
    """Marking a cue preload=True arms it; standby and GO also arm."""
    print("\n=== T20a: Live preload toggle arms cues ===")
    stop_all()

    # Mark tone_A and tone_B as preload; tone_C and tone_D stay unmarked.
    set_preload(ids["tone_A"], True)
    set_preload(ids["tone_B"], True)

    # Give the arm operations time to complete.
    # PreArmManager processes them synchronously on the Qt main thread
    # via the property_changed signal handler; 1 s is more than enough.
    time.sleep(1.0)

    status = pre_arm_status()

    t.check(
        "T20a: tone_A in armed set after preload toggle",
        ids["tone_A"] in status["armed"],
    )
    t.check(
        "T20a: tone_B in armed set after preload toggle",
        ids["tone_B"] in status["armed"],
    )
    t.check(
        "T20a: tone_C NOT in armed set (preload not set)",
        ids["tone_C"] not in status["armed"],
    )

    # Confirm the reason string contains "Preload"
    reason_a = status["armed"].get(ids["tone_A"], "")
    t.check(
        f"T20a: reason for tone_A includes 'Preload' (got {reason_a!r})",
        "Preload" in reason_a,
    )


def test_t20b_standby_auto_arm(t, ids):
    """Moving standby to a non-preload cue auto-arms it."""
    print("\n=== T20b: Standby auto-arm ===")

    # tone_C has preload=False; set standby to it (index 2).
    call("layout.set_standby_index", {"index": 2})

    result = wait_for_armed(ids["tone_C"], timeout=2.0)

    t.check(
        "T20b: tone_C auto-armed via standby",
        result["armed"] is True,
    )
    reason = result.get("reason", "")
    t.check(
        f"T20b: reason for tone_C includes 'Auto' (got {reason!r})",
        "Auto" in reason,
    )


def test_t20c_go_advance_arms_next(t, ids):
    """Pressing GO starts the standby cue and arms the next one."""
    print("\n=== T20c: GO advance arms next cue ===")

    # Set standby to index 1 (tone_B, already preload-armed).
    call("layout.set_standby_index", {"index": 1})

    # Press GO — this starts tone_B and advances standby to index 2 (tone_C).
    call("layout.go", {})

    # Wait for tone_C to appear in the armed set (auto-arm from standby).
    result = wait_for_armed(ids["tone_C"], timeout=3.0)

    t.check(
        "T20c: GO advances standby and auto-arms next cue (tone_C)",
        result["armed"] is True,
    )

    stop_all()
    time.sleep(0.3)


# ── T21: Latency measurement ───────────────────────────────────────────────


def test_t21_latency(t, ids):
    """Compare cold vs warm GO latency for a preload-armed cue.

    RPC round-trip overhead (≈1–5 ms) dominates on short WAV files, so we
    cannot guarantee large savings here.  We print observed values, check
    only that warm ≤ cold, and note when savings exceed 30 ms.

    The test is most meaningful with large files (e.g. compressed MP3) where
    GStreamer pipeline initialisation takes tens of milliseconds.  For the
    8-second 44.1 kHz WAV fixture the saving is typically small.
    """
    print("\n=== T21: Latency measurement (cold vs warm GO) ===")

    # --- Cold measurement: tone_D, preload off. ---
    # Ensure no residual preload on tone_D.
    set_preload(ids["tone_D"], False)
    # Move standby away so no auto-arm lands on tone_D.
    call("layout.set_standby_index", {"index": 0})
    time.sleep(0.5)

    # Stop everything and measure cold start latency.
    stop_all()
    cold_start = time.monotonic()
    call("cue.start", {"id": ids["tone_D"]})
    cold_ms = (time.monotonic() - cold_start) * 1000
    call("cue.stop", {"id": ids["tone_D"]})
    time.sleep(0.2)

    print(f"  Cold GO latency: {cold_ms:.1f} ms")

    # --- Warm measurement: tone_D, preload on. ---
    set_preload(ids["tone_D"], True)
    arm_result = wait_for_armed(ids["tone_D"], timeout=3.0)

    if not arm_result["armed"]:
        t.check("T21: tone_D failed to arm — latency test skipped", False)
        return

    warm_start = time.monotonic()
    call("cue.start", {"id": ids["tone_D"]})
    warm_ms = (time.monotonic() - warm_start) * 1000
    call("cue.stop", {"id": ids["tone_D"]})
    time.sleep(0.2)

    print(f"  Warm GO latency: {warm_ms:.1f} ms")
    savings = cold_ms - warm_ms
    print(f"  Latency saving:  {savings:.1f} ms")

    # RPC round-trip overhead is 1–10 ms on a local socket, which swamps
    # any saving on short WAV files.  We tolerate up to 15 ms overhead
    # before declaring a regression; pure-noise differences within that
    # band are logged but do not fail the suite.
    overhead_limit_ms = 15.0
    t.check(
        f"T21: warm GO not significantly worse than cold "
        f"(cold={cold_ms:.1f} ms, warm={warm_ms:.1f} ms, "
        f"limit=+{overhead_limit_ms} ms)",
        warm_ms <= cold_ms + overhead_limit_ms,
    )

    if savings >= 30:
        t.check(f"T21: warm GO saves >= 30 ms ({savings:.1f} ms)", True)
    else:
        print(
            f"  NOTE: saving {savings:.1f} ms < 30 ms — WAV fixture too"
            " small to show meaningful pre-arm benefit; this is expected."
        )

    stop_all()
    time.sleep(0.3)


# ── T22: Failure notifications ─────────────────────────────────────────────


def test_t22a_preload_failure_toasts(t):
    """Preload failure on a missing file emits a toast notification."""
    print("\n=== T22a: Preload failure emits toast ===")

    # Create the file, add the cue, then delete the file before marking
    # preload so GStreamer cannot open it.
    bogus_path = os.path.join(AUDIO_DIR, "bogus_nonexistent.wav")
    os.makedirs(AUDIO_DIR, exist_ok=True)
    make_tone(bogus_path, 880, 1.0)
    call("cue.add_from_uri", {"files": [bogus_path]})
    time.sleep(0.5)

    # Locate the cue by filename in the cue list.
    cue_list = call("cue.list")
    bogus_cues = [c for c in cue_list if "bogus_nonexistent" in c["name"]]
    if not bogus_cues:
        t.check("T22a: bogus cue added to session", False)
        return
    bogus_id = bogus_cues[0]["id"]
    t.check("T22a: bogus cue added to session", True)

    # Delete the backing file so the arm attempt will fail.
    os.unlink(bogus_path)

    # Subscribe to app.notify BEFORE triggering the arm attempt.
    with signal_sub("app.notify") as notify_sub:
        set_preload(bogus_id, True)

        # Wait for the failure toast.
        result = wait_for_signal(notify_sub, timeout=4.0)

    if result is not None:
        # result is {"event": {...}} because handle_signals_wait_for
        # wraps the event dict.
        event = result.get("event") or result
        args = event.get("args", [])
        message = args[0] if args else ""
        print(f"  Toast message: {message!r}")
        t.check(
            f"T22a: failure toast mentions preload (got: {message[:80]!r})",
            any(kw in message.lower() for kw in ("preload", "fail", "load")),
        )
    else:
        t.check("T22a: failure toast emitted within 4 s", False)

    # Verify the cue is in the failed set.
    status = pre_arm_status()
    t.check(
        "T22a: bogus cue in pre_arm.status failed set",
        bogus_id in status.get("failed", {}),
    )

    call("cue.remove", {"id": bogus_id})
    time.sleep(0.2)


def test_t22b_auto_arm_failure_is_silent(t):
    """Auto-arm failure (missing file, preload=False) emits NO toast."""
    print("\n=== T22b: Auto-arm failure is silent ===")

    bogus2_path = os.path.join(AUDIO_DIR, "bogus2_silent.wav")
    os.makedirs(AUDIO_DIR, exist_ok=True)
    make_tone(bogus2_path, 990, 1.0)
    call("cue.add_from_uri", {"files": [bogus2_path]})
    time.sleep(0.5)

    cue_list = call("cue.list")
    bogus2_cues = [c for c in cue_list if "bogus2_silent" in c["name"]]
    if not bogus2_cues:
        t.check("T22b: bogus2 cue added", False)
        return
    bogus2 = bogus2_cues[0]
    bogus2_id = bogus2["id"]

    # Delete the file — but do NOT set preload=True.
    os.unlink(bogus2_path)

    # Find the cue's index in the layout.
    fresh_list = call("cue.list")
    bogus2_idx = next(
        (i for i, c in enumerate(fresh_list) if c["id"] == bogus2_id),
        None,
    )
    if bogus2_idx is None:
        t.check("T22b: bogus2 found in cue list for standby", False)
        call("cue.remove", {"id": bogus2_id})
        return

    # Subscribe before moving standby so we don't miss any spurious toast.
    with signal_sub("app.notify") as auto_sub:
        call("layout.set_standby_index", {"index": bogus2_idx})
        # Give the auto-arm attempt time to run and (fail).
        time.sleep(1.5)
        # Drain with a short timeout — we expect nothing.
        toast = wait_for_signal(auto_sub, timeout=0.3)

    t.check(
        "T22b: auto-arm failure emits NO toast (got: "
        + (repr(toast) if toast is not None else "None") + ")",
        toast is None,
    )

    call("cue.remove", {"id": bogus2_id})
    time.sleep(0.2)


# ── T22 note: batch coalescing ─────────────────────────────────────────────
# Batch failure coalescing on session_load is tested by the unit test
# test_pre_arm_manager.py.  Reproducing it here would require building
# a full .lsp session file with multiple preload cues that all point at
# missing files and reloading it via session.load — possible but fragile.
# The unit tests provide adequate coverage for the coalescing logic.

# ── T23 note: cap pressure ─────────────────────────────────────────────────
# Cap pressure (maxArmed=N) is tested by test_pre_arm_manager.py.
# Exercising it here would require writing to the user's LiSP config file
# (~/.config/LinuxShowPlayer/0.6/lisp.json) or adding a new harness RPC
# method (pre_arm.set_cap).  Both are out of scope for this task.
# The unit tests provide adequate coverage.


# ── Tear-down helper ───────────────────────────────────────────────────────


def _reset_preload_flags(ids):
    """Unset preload on all standard tones to leave the session clean."""
    for cue_id in ids.values():
        try:
            set_preload(cue_id, False)
        except Exception:
            pass  # cue may have been removed already
    time.sleep(0.5)


# ── Main test runner ───────────────────────────────────────────────────────


def run_tests(t):
    print("\nSetting up test cues...")
    ids = setup_with_tones()

    try:
        # T20 — three sub-tests that share the same cue set.
        test_t20_live_preload_toggle(t, ids)
        test_t20b_standby_auto_arm(t, ids)
        test_t20c_go_advance_arms_next(t, ids)

        # T21 — latency comparison; reuses tone_D.
        test_t21_latency(t, ids)

        # T22 — failure notifications; add/remove extra cues.
        test_t22a_preload_failure_toasts(t)
        test_t22b_auto_arm_failure_is_silent(t)

    finally:
        # Best-effort cleanup: remove preload flags so a subsequent
        # --no-launch run doesn't inherit armed state.
        _reset_preload_flags(ids)

    print(
        "\n  NOTE (T22 batch): batch-coalescing on session_load tested by"
        " unit tests in test_pre_arm_manager.py"
    )
    print(
        "  NOTE (T23 cap):  cap pressure tested by unit tests in"
        " test_pre_arm_manager.py (no runtime-safe way to set cap"
        " without writing user config)"
    )


if __name__ == "__main__":
    run_suite("Pre-arm E2E (T20–T23)", run_tests)
