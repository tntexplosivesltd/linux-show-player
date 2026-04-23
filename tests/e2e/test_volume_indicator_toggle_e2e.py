#!/usr/bin/env python3
"""E2E test for the cue volume indicator visibility toggle.

Covers:
    1. With show.volumeIndicators=false (default), the indicator
       is hidden on a running MediaCue.
    2. Flipping the layout-level toggle via layout.set_property
       reveals the indicator with a valid dB-formatted text.
    3. Flipping it back hides the indicator again.

Run:
    poetry run python tests/e2e/test_volume_indicator_toggle_e2e.py
"""

import os
import re
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from tests.e2e.helpers import (  # noqa: E402
    run_suite, call, setup_with_tones, stop_all, wait_state,
)

DB_PATTERN = re.compile(r"^[-+](\d+\.\d+ dB|∞ dB)$")


def _widget_info_for(cue_id):
    """Return the running-widget info dict for `cue_id`, or None."""
    for entry in call("layout.running_widget_info"):
        if entry["cue_id"] == cue_id:
            return entry
    return None


def test_toggle_visibility(t, ids):
    """Enabling show.volumeIndicators reveals the label; disabling hides it."""
    print("\n=== Test: Volume indicator toggle ===")
    stop_all()

    target = ids["tone_A"]
    call("cue.execute", {"id": target, "action": "Start"})
    assert wait_state(target, "Running"), "target failed to start"

    # Default off — indicator should be hidden on the running cue.
    info = _widget_info_for(target)
    t.check(
        "indicator hidden by default",
        info is not None and info["volume_indicator_visible"] is False,
    )

    # Enable the toggle through the layout proxy-property setter.
    call("layout.set_property", {
        "name": "volume_indicators_visible",
        "value": True,
    })
    time.sleep(0.2)

    info = _widget_info_for(target)
    t.check(
        "indicator visible after enable",
        info is not None and info["volume_indicator_visible"] is True,
    )
    t.check(
        "indicator text matches dB format",
        info is not None and bool(DB_PATTERN.match(
            info["volume_indicator_text"]
        )),
    )

    # Disable and confirm hide.
    call("layout.set_property", {
        "name": "volume_indicators_visible",
        "value": False,
    })
    time.sleep(0.2)

    info = _widget_info_for(target)
    t.check(
        "indicator hidden after disable",
        info is not None and info["volume_indicator_visible"] is False,
    )


def run_tests(t):
    ids = setup_with_tones()
    test_toggle_visibility(t, ids)


if __name__ == "__main__":
    sys.exit(run_suite(
        "Volume Indicator Toggle E2E",
        run_tests,
    ))
