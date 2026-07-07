"""E2E tests for the Playback Monitor plugin.

Verifies the monitor window opens, tracks playing cues, switches
when a new cue starts, freezes on stop, and remaining changes.
"""

import time

from tests.e2e.helpers import (
    call,
    create_test_audio,
    clear_cues,
    run_suite,
    stop_all,
    wait_current_time,
    wait_state,
)


def _wait_elapsed_ticks(timeout=5.0):
    """Poll until the monitor's displayed elapsed passes 00:00.

    ``playback_monitor.state["elapsed"]`` returns the live QLabel text,
    refreshed by a ``Connection.QtQueued`` slot on the 33 ms CueTime
    clock.  MM:SS truncation means it reads "00:00" for the first second
    of playback, and under sustained load the Qt event loop can starve
    the queued slot so the label stays stale even after the cue's clock
    has passed 1 s.  Wait for a fresh, advanced tick rather than a fixed
    sleep.  Returns the monitor state dict (last-seen on timeout).
    """
    deadline = time.time() + timeout
    state = call("playback_monitor.state")
    while time.time() < deadline:
        state = call("playback_monitor.state")
        if state.get("elapsed") not in (None, "00:00"):
            return state
        time.sleep(0.1)
    return state


def _wait_tracked(cue_id, timeout=5.0):
    """Poll until the monitor is tracking ``cue_id``.

    The monitor switches tracked cue via a queued signal handler that,
    like the elapsed label, can lag under load.  Returns the monitor
    state dict (last-seen on timeout).
    """
    deadline = time.time() + timeout
    state = call("playback_monitor.state")
    while time.time() < deadline:
        state = call("playback_monitor.state")
        if state.get("tracked_cue_id") == cue_id:
            return state
        time.sleep(0.1)
    return state


def run_tests(t):
    create_test_audio()
    clear_cues()

    # ── Test 1: Plugin is loaded ──────────────────────────────
    print("\n=== Test 1: Plugin loaded ===")
    state = call("playback_monitor.state")
    t.check(
        "1: plugin is loaded",
        state.get("loaded") is True,
    )

    # ── Test 2: Toggle window open ────────────────────────────
    print("\n=== Test 2: Toggle window open ===")
    result = call("playback_monitor.toggle")
    t.check(
        "2: window visible after toggle",
        result.get("visible"),
    )

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

    # Poll until the monitor's displayed elapsed ticks past 00:00
    # (MM:SS truncates; the QtQueued label can lag under load) rather
    # than sleeping a fixed 1.5 s and hoping.
    state = _wait_elapsed_ticks(timeout=5.0)
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

    # ── Test 3b: Remaining actually changes ───────────────────
    print("\n=== Test 3b: Remaining changes over time ===")
    remaining_1 = state.get("remaining")
    # Poll until the monitor's remaining label changes instead of
    # sleeping a fixed 2 s (the QtQueued label can lag under load).
    deadline = time.time() + 5.0
    remaining_2 = remaining_1
    while time.time() < deadline:
        remaining_2 = call("playback_monitor.state").get("remaining")
        if remaining_2 != remaining_1:
            break
        time.sleep(0.1)
    t.check(
        "3b: remaining decreased",
        remaining_2 != remaining_1,
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

    # Test 5 asserts the monitor freezes a *non-zero* elapsed when B is
    # stopped.  The monitor has no stopped-handler: it simply freezes at
    # the last value the 33ms QtQueued tick wrote.  Two independent races
    # can leave that "00:00", so guard against both, in order:
    #   1. wait_current_time — B's own pipeline clock passes 1s, after
    #      which NO tick can ever format B's position as "00:00".
    #   2. _wait_elapsed_ticks — force a fresh non-zero tick into the
    #      label (the display can otherwise be stuck on an old B tick or
    #      cue A's leftover value) before Test 5 stops the cue.
    state = _wait_tracked(cue_id_b, timeout=5.0)
    wait_current_time(cue_id_b, min_ms=1000, timeout=5)
    _wait_elapsed_ticks(timeout=5.0)
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
    frozen_remaining = state_after_stop.get("remaining")

    time.sleep(0.5)
    state_later = call("playback_monitor.state")
    t.check(
        "5: elapsed is frozen",
        state_later.get("elapsed") == frozen_elapsed,
    )
    t.check(
        "5: remaining is frozen",
        state_later.get("remaining") == frozen_remaining,
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
