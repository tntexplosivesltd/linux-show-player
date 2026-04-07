import pytest

from lisp.core.fade_functions import (
    fade_linear,
    fadein_quad,
    fadeout_quad,
    fade_inout_quad,
    ntime,
)


class TestFadeLinear:
    def test_start(self):
        # t=0: result = a*0 + b = b
        assert fade_linear(0, 1.0, 0.0) == 0.0

    def test_end(self):
        # t=1: result = a*1 + b = a + b
        assert fade_linear(1, 1.0, 0.0) == 1.0

    def test_midpoint(self):
        assert fade_linear(0.5, 1.0, 0.0) == pytest.approx(0.5)

    def test_with_offset(self):
        # t=1, a=2, b=3: result = 2*1 + 3 = 5
        assert fade_linear(1, 2.0, 3.0) == 5.0


class TestFadeinQuad:
    def test_start(self):
        assert fadein_quad(0, 1.0, 0.0) == 0.0

    def test_end(self):
        assert fadein_quad(1, 1.0, 0.0) == 1.0

    def test_midpoint_below_linear(self):
        # Quadratic fade-in is slower at start, so midpoint < 0.5
        assert fadein_quad(0.5, 1.0, 0.0) < 0.5


class TestFadeoutQuad:
    def test_start(self):
        assert fadeout_quad(0, 1.0, 0.0) == 0.0

    def test_end(self):
        assert fadeout_quad(1, 1.0, 0.0) == 1.0

    def test_midpoint_above_linear(self):
        # Quadratic fade-out is faster at start, so midpoint > 0.5
        assert fadeout_quad(0.5, 1.0, 0.0) > 0.5


class TestFadeInoutQuad:
    def test_start(self):
        assert fade_inout_quad(0, 1.0, 0.0) == 0.0

    def test_end(self):
        assert fade_inout_quad(1, 1.0, 0.0) == pytest.approx(1.0)

    def test_midpoint(self):
        assert fade_inout_quad(0.5, 1.0, 0.0) == pytest.approx(0.5)

    def test_first_half_below_linear(self):
        assert fade_inout_quad(0.25, 1.0, 0.0) < 0.25

    def test_second_half_above_linear(self):
        assert fade_inout_quad(0.75, 1.0, 0.0) > 0.75


class TestNtime:
    def test_at_begin(self):
        assert ntime(0, 0, 1) == 0.0

    def test_at_end(self):
        assert ntime(1, 0, 1) == 1.0

    def test_midpoint(self):
        assert ntime(500, 0, 1000) == 0.5

    def test_with_offset(self):
        assert ntime(50, 25, 75) == 0.5
