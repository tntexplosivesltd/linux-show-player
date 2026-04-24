#!/usr/bin/env python3
"""E2E test that Volume.live_volume interpolates during a fade.

The cue-volume indicator is a pure function of Volume.live_volume
(the unit-test suite in tests/plugins/list_layout/test_volume_indicator.py
covers the formatting). This suite proves the live_volume side of
that contract: a Volume-Control cue actually drives the value down
and lands on the target within tolerance.

Run:
    poetry run python tests/e2e/test_volume_indicator_fade_e2e.py
"""

import math
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from tests.e2e.helpers import (  # noqa: E402
    run_suite, call, setup_with_tones, stop_all, wait_state,
    cue_signal, wait_for_signal,
)


def _linear_from_db(db):
    return 10 ** (db / 20)


def _live_volume(cue_id):
    return call("cue.get_element_property", {
        "id": cue_id,
        "element": "Volume",
        "property": "live_volume",
    })["value"]


def test_fade_interpolates_live_volume(t, ids):
    """A VolumeControl cue fading to -12 dB decreases live_volume
    monotonically and lands near 0.251 linear (= -12 dB) within
    tolerance.
    """
    print("\n=== Test: live_volume fades monotonically ===")
    stop_all()

    target = ids["tone_A"]
    call("cue.execute", {"id": target, "action": "Start"})
    assert wait_state(target, "Running")

    # Let the pipeline settle so live_volume reflects the cue's
    # configured unity gain rather than a mid-ramp value from the
    # fade-in action.
    time.sleep(0.5)

    v0 = _live_volume(target)
    t.check(
        f"initial live_volume near unity (got {v0:.3f})",
        abs(v0 - 1.0) < 0.05,
    )

    vc_id = call("cue.add", {
        "type": "VolumeControl",
        "properties": {
            "target_id": target,
            "volume": _linear_from_db(-12),
            "duration": 1000,
            "fade_type": "Linear",
        },
    })["id"]

    samples = []
    with cue_signal(vc_id, "end") as sub:
        call("cue.execute", {"id": vc_id, "action": "Start"})
        t_start = time.monotonic()
        while time.monotonic() - t_start < 1.2:
            samples.append(_live_volume(target))
            time.sleep(0.1)
        wait_for_signal(sub, timeout=2.0)

    t.check(
        "samples decrease monotonically",
        all(a >= b - 0.005 for a, b in zip(samples, samples[1:])),
    )

    final = _live_volume(target)
    expected = _linear_from_db(-12)
    t.check(
        f"final live_volume ~= -12 dB ({expected:.3f}); got {final:.3f}",
        math.isclose(final, expected, abs_tol=0.03),
    )


def run_tests(t):
    ids = setup_with_tones()
    test_fade_interpolates_live_volume(t, ids)


if __name__ == "__main__":
    sys.exit(run_suite(
        "Volume Indicator Fade E2E",
        run_tests,
    ))
