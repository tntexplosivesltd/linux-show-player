"""Tests for VideoCompositor build-plan and register bookkeeping."""

from unittest.mock import patch

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
