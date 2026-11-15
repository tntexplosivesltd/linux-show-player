"""Pixel checks under projection overload (tests/e2e/helpers.py).

A screen-pixel E2E check that fails while the machine cannot render
the projection in real time says nothing about LiSP: it is
inconclusive (a skip), not a failure. Overload needs BOTH frames
reaching the sink below real-time rate and many of them dropped; a
LiSP timing bug drops frames at the full rate and must still fail.
"""

import pytest

from tests.e2e import helpers
from tests.e2e.helpers import (
    MIN_LOAD_FRAMES,
    OVERLOAD_ARRIVAL_FPS,
    OVERLOAD_DROP_RATE,
    PROJECTION_FPS,
    ProjectionLoad,
    check_pixels,
    describe_load,
    is_overloaded,
    projection_counts,
    projection_load,
)
from tests.e2e.tracker import EXIT_SKIP, TestTracker

# Measured shapes (CI image, 2026-11-15).
OVERLOADED = ProjectionLoad(drop_rate=0.39, arrival_fps=24.9)
UNTHROTTLED = ProjectionLoad(drop_rate=0.003, arrival_fps=29.9)
# A LiSP timestamping bug: every frame arrives, every frame dropped.
MIS_STAMPED = ProjectionLoad(drop_rate=1.0, arrival_fps=30.0)


class TestProjectionLoad:
    def test_drop_share_and_arrival_rate_over_the_window(self):
        load = projection_load((100, 5, 10.0), (190, 15, 13.0))
        assert load.drop_rate == pytest.approx(0.1)
        assert load.arrival_fps == pytest.approx(100 / 3)

    @pytest.mark.parametrize("before, after", [
        (None, (10, 0, 1.0)), ((10, 0, 0.0), None), (None, None),
    ])
    def test_missing_reading_is_none(self, before, after):
        assert projection_load(before, after) is None

    @pytest.mark.parametrize("before, after", [
        # The projection was rebuilt mid-window: a new sink counts from
        # 0, so a counter goes down. Judged strictly, never "overload".
        ((100, 0, 0.0), (20, 90, 3.0)),
        ((100, 50, 0.0), (180, 10, 3.0)),
    ])
    def test_counter_reset_is_none(self, before, after):
        assert projection_load(before, after) is None

    def test_too_few_frames_is_none(self):
        n = MIN_LOAD_FRAMES - 1
        assert projection_load((10, 2, 0.0), (10 + n, 2, 1.0)) is None

    def test_no_time_elapsed_is_none(self):
        assert projection_load((10, 0, 5.0), (40, 10, 5.0)) is None


class TestIsOverloaded:
    def test_measured_overload(self):
        assert is_overloaded(OVERLOADED)

    def test_unthrottled_is_not(self):
        assert not is_overloaded(UNTHROTTLED)

    def test_dropping_at_full_rate_is_not_overload(self):
        # The case the gate must never excuse: frames arrive on time
        # (the machine keeps up) but LiSP stamped them so the sink drops
        # them all.
        assert not is_overloaded(MIS_STAMPED)

    def test_slow_arrival_with_few_drops_is_not(self):
        assert not is_overloaded(ProjectionLoad(0.05, 20.0))

    def test_thresholds_are_exclusive(self):
        assert not is_overloaded(
            ProjectionLoad(OVERLOAD_DROP_RATE, 20.0))
        assert not is_overloaded(
            ProjectionLoad(0.5, OVERLOAD_ARRIVAL_FPS))
        assert is_overloaded(
            ProjectionLoad(OVERLOAD_DROP_RATE + 0.001,
                           OVERLOAD_ARRIVAL_FPS - 0.1))

    def test_no_reading_is_not(self):
        assert not is_overloaded(None)

    def test_arrival_bound_is_below_the_mixer_rate(self):
        assert OVERLOAD_ARRIVAL_FPS < PROJECTION_FPS


class TestProjectionCounts:
    def test_reads_the_counters_with_a_timestamp(self, monkeypatch):
        monkeypatch.setattr(helpers, "call", lambda m, p=None: {
            "exists": True,
            "projection": {"rendered": 7, "dropped": 2,
                           "average_rate": 0.0},
            "cues": [],
        })
        monkeypatch.setattr(helpers.time, "monotonic", lambda: 42.5)
        assert projection_counts() == (7, 2, 42.5)

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
        assert check_pixels(t, "no black gap", True, OVERLOADED)
        assert t.skipped is None
        assert t.summary() == 0

    def test_failure_on_a_machine_that_keeps_up_fails(self):
        t = TestTracker()
        assert check_pixels(t, "no black gap", False, UNTHROTTLED)
        assert t.summary() == 1

    def test_failure_from_mis_stamped_frames_fails(self):
        t = TestTracker()
        assert check_pixels(t, "no black gap", False, MIS_STAMPED)
        assert t.skipped is None
        assert t.summary() == 1

    def test_failure_without_a_reading_fails(self):
        t = TestTracker()
        assert check_pixels(t, "no black gap", False, None)
        assert t.summary() == 1

    def test_failure_while_overloaded_is_a_skip(self, capsys):
        t = TestTracker()
        judged = check_pixels(t, "no black gap", False, OVERLOADED)
        assert not judged
        assert t.failed == 0
        assert t.summary() == EXIT_SKIP
        out = capsys.readouterr().out
        assert "no black gap: inconclusive" in out
        assert "39%" in out
        assert "24.9/30" in out

    def test_reasons_accumulate(self):
        t = TestTracker()
        check_pixels(t, "mostly bright", False, OVERLOADED)
        check_pixels(t, "no black gap", False, OVERLOADED)
        assert "mostly bright" in t.skipped
        assert "no black gap" in t.skipped

    def test_other_failures_still_fail_the_run(self):
        # The harness-truth checks (advances, cue B started) stay hard.
        t = TestTracker()
        check_pixels(t, "no black gap", False, OVERLOADED)
        t.check(">= 5 playlist auto-advances", False)
        assert t.summary() == 1


class TestDescribeLoad:
    def test_reports_both_measures_and_the_verdict(self):
        line = describe_load(OVERLOADED)
        assert "39.0% dropped" in line
        assert "24.9 frames/s" in line
        assert "overloaded=True" in line

    def test_no_reading(self):
        assert "not measured" in describe_load(None)
