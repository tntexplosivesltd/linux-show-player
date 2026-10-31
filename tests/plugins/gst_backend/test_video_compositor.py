"""Tests for VideoCompositor build-plan and register bookkeeping."""

from unittest.mock import MagicMock, patch

from lisp.plugins.gst_backend import video_compositor as vc


class TestPlanPipeline:
    def test_gl_plan_when_gl_available(self):
        # All GL factories present → GL plan.
        with patch.object(vc, "_have_factory", return_value=True):
            plan = vc.plan_pipeline()
        assert plan["gl"] is True
        assert plan["upload"] == "glupload"
        assert plan["mixer"] == "glvideomixer"
        assert plan["sink"] == "glimagesink"

    def test_fallback_plan_when_no_gl(self):
        # glvideomixer missing → system-memory fallback, no upload.
        def fake(name):
            return name in ("compositor", "xvimagesink")

        with patch.object(vc, "_have_factory", side_effect=fake):
            plan = vc.plan_pipeline()
        assert plan["gl"] is False
        assert plan["upload"] is None
        assert plan["mixer"] == "compositor"
        assert plan["sink"] == "xvimagesink"

    def test_fallback_sink_autovideosink_when_no_xv(self):
        def fake(name):
            return name == "compositor"

        with patch.object(vc, "_have_factory", side_effect=fake):
            plan = vc.plan_pipeline()
        assert plan["sink"] == "autovideosink"


def _fake_windows():
    out = MagicMock()
    out.window_handle.return_value = 111
    mon = MagicMock()
    mon.window_handle.return_value = 222
    return out, mon


class TestVideoCompositorLifecycle:
    def test_available_true_when_pipeline_reaches_playing(self):
        out, mon = _fake_windows()

        def fake_build(self):
            self.pipeline = MagicMock()
            self.mixer = MagicMock()
            self._clock = MagicMock()
            return True

        with patch.object(vc.VideoCompositor, "_build", fake_build):
            comp = vc.VideoCompositor(out, mon)
        assert comp.available is True
        assert comp.clock() is comp._clock

    def test_available_false_when_build_fails(self):
        out, mon = _fake_windows()
        with patch.object(
            vc.VideoCompositor, "_build", autospec=True,
            return_value=False,
        ):
            comp = vc.VideoCompositor(out, mon)
        assert comp.available is False

    def test_window_handles_captured_before_build(self):
        # winId() creates the native window; it must happen on the
        # constructing (main) thread, not in the streaming-thread
        # prepare-window-handle callback.
        out, mon = _fake_windows()
        seen = {}

        def fake_build(self):
            seen["handles"] = (self._output_handle, self._monitor_handle)
            return True

        with patch.object(vc.VideoCompositor, "_build", fake_build):
            vc.VideoCompositor(out, mon)
        assert seen["handles"] == (111, 222)
