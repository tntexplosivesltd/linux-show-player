"""E2E tests for the Playback Monitor plugin.

Verifies the monitor window opens, tracks playing cues, switches
when a new cue starts, and freezes on stop.
"""

import time

from tests.e2e.helpers import (
    call,
    create_test_audio,
    clear_cues,
    run_suite,
    stop_all,
    wait_state,
)


def run_tests(t):
    create_test_audio()
    clear_cues()

    # ── Test 1: Plugin is loaded ──────────────────────────────
    print("\n=== Test 1: Plugin loaded ===")
    state = call("playback_monitor.state")
    t.check("1: plugin is loaded", state.get("loaded") is True)

    # ── Test 2: Toggle window open ────────────────────────────
    print("\n=== Test 2: Toggle window open ===")
    result = call("playback_monitor.toggle")
    t.check("2: window visible after toggle", result.get("visible"))

    state = call("playback_monitor.state")
    t.check("2: state shows visible", state.get("visible"))
    t.check(
        "2: idle shows dash for name",
        state.get("cue_name") == "\u2014",
    )
    t.check(
        "2: idle shows 00:00 elapsed",
        state.get("elapsed") == "00:00",
    )

    # ── Test 3: Play a cue, monitor tracks it ─────────────────
    print("\n=== Test 3: Track playing cue ===")
    call("cue.add_from_uri", {
        "uri": "/tmp/lisp_test_audio/tone_A.wav",
    })
    time.sleep(1)

    cues = call("cue.list")
    t.check("3: cue A was added", len(cues) >= 1)
    if not cues:
        return
    cue_id_a = cues[0]["id"]

    call("cue.start", {"id": cue_id_a})
    wait_state(cue_id_a, "Running", timeout=5)

    # Wait >1s so elapsed ticks past 00:00 (MM:SS truncates)
    time.sleep(1.5)

    state = call("playback_monitor.state")
    t.check(
        "3: tracked cue id matches",
        state.get("tracked_cue_id") == cue_id_a,
    )
    t.check(
        "3: cue name is shown",
        state.get("cue_name") != "\u2014",
    )
    t.check(
        "3: elapsed is not 00:00",
        state.get("elapsed") != "00:00",
    )
    t.check(
        "3: remaining is not 00:00",
        state.get("remaining") not in ("00:00", "--:--"),
    )

    # ── Test 4: Start second cue, monitor switches ────────────
    print("\n=== Test 4: Switch to second cue ===")
    call("cue.add_from_uri", {
        "uri": "/tmp/lisp_test_audio/tone_B.wav",
    })
    time.sleep(1)

    cues = call("cue.list")
    t.check("4: cue B was added", len(cues) >= 2)
    if len(cues) < 2:
        return
    cue_id_b = cues[1]["id"]

    call("cue.start", {"id": cue_id_b})
    wait_state(cue_id_b, "Running", timeout=5)

    # Wait >1s so elapsed ticks past 00:00
    time.sleep(1.5)

    state = call("playback_monitor.state")
    t.check(
        "4: monitor switched to cue B",
        state.get("tracked_cue_id") == cue_id_b,
    )

    # ── Test 5: Stop cue, display freezes ─────────────────────
    print("\n=== Test 5: Freeze on stop ===")
    call("cue.stop", {"id": cue_id_b})
    wait_state(cue_id_b, "Stop", timeout=5)

    time.sleep(0.3)
    state_after_stop = call("playback_monitor.state")
    frozen_elapsed = state_after_stop.get("elapsed")

    # Wait a bit more and check it hasn't changed
    time.sleep(0.5)
    state_later = call("playback_monitor.state")
    t.check(
        "5: display is frozen (not resetting or counting)",
        state_later.get("elapsed") == frozen_elapsed,
    )
    t.check(
        "5: frozen elapsed is not 00:00",
        frozen_elapsed != "00:00",
    )

    # ── Test 6: Toggle window closed ──────────────────────────
    print("\n=== Test 6: Toggle window closed ===")
    call("playback_monitor.toggle")
    state = call("playback_monitor.state")
    t.check(
        "6: window not visible after toggle",
        not state.get("visible"),
    )

    # ── Cleanup ───────────────────────────────────────────────
    stop_all()
    clear_cues()


if __name__ == "__main__":
    run_suite("Playback Monitor", run_tests)
