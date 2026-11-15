"""Pixel checks under projection overload (tests/e2e/helpers.py).

A screen-pixel E2E check that fails while the projection sink drops
frames because the machine cannot render it in real time says nothing
about LiSP: it is inconclusive (a skip), not a failure. A pass, a
failure with few drops, or a failure without stats is judged as usual.
"""

import pytest

from tests.e2e import helpers
from tests.e2e.helpers import (
    OVERLOAD_DROP_RATE,
    check_pixels,
    projection_counts,
    projection_drop_rate,
)
from tests.e2e.tracker import EXIT_SKIP, TestTracker


class TestProjectionDropRate:
    def test_share_of_frames_dropped_in_the_window(self):
        assert projection_drop_rate((100, 5), (190, 15)) == 0.1

    @pytest.mark.parametrize("before, after", [
        (None, (10, 0)), ((10, 0), None), (None, None),
    ])
    def test_missing_reading_is_none(self, before, after):
        assert projection_drop_rate(before, after) is None

    def test_no_frames_in_the_window_is_none(self):
        assert projection_drop_rate((10, 2), (10, 2)) is None


class TestProjectionCounts:
    def test_reads_the_projection_sink_counters(self, monkeypatch):
        monkeypatch.setattr(helpers, "call", lambda m, p=None: {
            "exists": True,
            "projection": {"rendered": 7, "dropped": 2,
                           "average_rate": 0.0},
            "cues": [],
        })
        assert projection_counts() == (7, 2)

    @pytest.mark.parametrize("stats", [
        {"exists": False},
        {"exists": True, "projection": None, "cues": []},
    ])
    def test_no_projection_or_no_stats_is_none(self, monkeypatch, stats):
        monkeypatch.setattr(helpers, "call", lambda m, p=None: stats)
        assert projection_counts() is None

    def test_harness_error_is_none(self, monkeypatch):
        def broken(method, params=None):
            raise RuntimeError("no harness")

        monkeypatch.setattr(helpers, "call", broken)
        assert projection_counts() is None


class TestCheckPixels:
    def test_pass_counts_even_when_overloaded(self):
        t = TestTracker()
        assert check_pixels(t, "no black gap", True, 0.9)
        assert t.skipped is None
        assert t.summary() == 0

    def test_failure_with_few_drops_fails(self):
        t = TestTracker()
        assert check_pixels(t, "no black gap", False, 0.02)
        assert t.summary() == 1

    def test_failure_at_the_threshold_still_fails(self):
        t = TestTracker()
        check_pixels(t, "no black gap", False, OVERLOAD_DROP_RATE)
        assert t.summary() == 1

    def test_failure_without_stats_fails(self):
        t = TestTracker()
        assert check_pixels(t, "no black gap", False, None)
        assert t.summary() == 1

    def test_failure_while_overloaded_is_a_skip(self, capsys):
        t = TestTracker()
        judged = check_pixels(t, "no black gap", False, 0.39)
        assert not judged
        assert t.failed == 0
        assert t.summary() == EXIT_SKIP
        out = capsys.readouterr().out
        assert "no black gap: inconclusive" in out
        assert "39%" in out

    def test_reasons_accumulate(self):
        t = TestTracker()
        check_pixels(t, "mostly bright", False, 0.3)
        check_pixels(t, "no black gap", False, 0.3)
        assert "mostly bright" in t.skipped
        assert "no black gap" in t.skipped

    def test_other_failures_still_fail_the_run(self):
        # The harness-truth checks (advances, cue B started) stay hard.
        t = TestTracker()
        check_pixels(t, "no black gap", False, 0.3)
        t.check(">= 5 playlist auto-advances", False)
        assert t.summary() == 1
