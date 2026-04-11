"""Tests for FaderGroup."""

import threading
import time

from lisp.core.fade_functions import FadeInType, FadeOutType
from lisp.core.fader import Fader
from lisp.core.fader_group import FaderGroup


class _Target:
    """Simple target object with a numeric attribute."""

    def __init__(self, value=0.0):
        self.level = value


class TestFaderGroupEmpty:
    def test_empty_group_fade_returns_true(self):
        group = FaderGroup()
        assert group.fade(1.0, [], FadeOutType.Linear) is True

    def test_empty_group_stop_is_noop(self):
        group = FaderGroup()
        group.stop()

    def test_empty_group_prepare_is_noop(self):
        group = FaderGroup()
        group.prepare()

    def test_empty_group_len_is_zero(self):
        group = FaderGroup()
        assert len(group) == 0

    def test_empty_group_is_falsy(self):
        group = FaderGroup()
        assert not group

    def test_empty_group_current_time_is_zero(self):
        group = FaderGroup()
        assert group.current_time() == 0


class TestFaderGroupSingle:
    def test_single_fader_reaches_target(self):
        target = _Target(1.0)
        fader = Fader(target, "level")
        group = FaderGroup([fader])

        group.prepare()
        result = group.fade(
            0.1, [0.0], FadeOutType.Linear
        )

        assert result is True
        assert abs(target.level) < 0.01

    def test_single_fader_len_is_one(self):
        target = _Target()
        fader = Fader(target, "level")
        group = FaderGroup([fader])
        assert len(group) == 1

    def test_single_fader_is_truthy(self):
        target = _Target()
        fader = Fader(target, "level")
        group = FaderGroup([fader])
        assert group


class TestFaderGroupMultiple:
    def test_two_faders_both_reach_targets(self):
        t1 = _Target(1.0)
        t2 = _Target(0.5)
        f1 = Fader(t1, "level")
        f2 = Fader(t2, "level")
        group = FaderGroup([f1, f2])

        group.prepare()
        result = group.fade(
            0.1, [0.0, 1.0], FadeOutType.Linear
        )

        assert result is True
        assert abs(t1.level) < 0.01
        assert abs(t2.level - 1.0) < 0.05

    def test_different_target_values(self):
        t1 = _Target(0.0)
        t2 = _Target(0.0)
        f1 = Fader(t1, "level")
        f2 = Fader(t2, "level")
        group = FaderGroup([f1, f2])

        group.prepare()
        group.fade(0.1, [0.8, 0.3], FadeInType.Linear)

        assert abs(t1.level - 0.8) < 0.05
        assert abs(t2.level - 0.3) < 0.05


class TestFaderGroupInterrupt:
    def test_stop_interrupts_fade(self):
        t1 = _Target(1.0)
        f1 = Fader(t1, "level")
        group = FaderGroup([f1])

        group.prepare()

        result_holder = [None]

        def do_fade():
            result_holder[0] = group.fade(
                5.0, [0.0], FadeOutType.Linear
            )

        thread = threading.Thread(target=do_fade)
        thread.start()

        time.sleep(0.05)
        group.stop()
        thread.join(timeout=2)

        assert result_holder[0] is False
        # Value should be somewhere between 0 and 1
        assert t1.level > 0.0

    def test_stop_when_not_running_is_noop(self):
        t1 = _Target(1.0)
        f1 = Fader(t1, "level")
        group = FaderGroup([f1])
        group.stop()


class TestFaderGroupNoMutableDefault:
    def test_separate_instances_have_separate_faders(self):
        """Regression: no mutable default class variable."""
        t1 = _Target()
        f1 = Fader(t1, "level")
        g1 = FaderGroup([f1])

        g2 = FaderGroup()

        assert len(g1) == 1
        assert len(g2) == 0
        assert g1.faders is not g2.faders
