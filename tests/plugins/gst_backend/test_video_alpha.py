"""Tests for VideoAlpha element."""

from lisp.backend.media_element import ElementType, MediaType
from lisp.plugins.gst_backend.gi_repository import Gst
from lisp.plugins.gst_backend.elements.video_alpha import (
    VideoAlpha,
)


class TestVideoAlphaProperties:
    def test_media_type(self):
        assert VideoAlpha.MediaType == MediaType.Video

    def test_element_type(self):
        assert VideoAlpha.ElementType == ElementType.Plugin

    def test_default_alpha(self):
        pipeline = Gst.Pipeline()
        element = VideoAlpha(pipeline)
        assert element.alpha == 1.0


class TestVideoAlphaConstruction:
    def test_creates_compositor(self):
        pipeline = Gst.Pipeline()
        element = VideoAlpha(pipeline)
        assert element.gst_compositor is not None

    def test_creates_videoconvert(self):
        pipeline = Gst.Pipeline()
        element = VideoAlpha(pipeline)
        assert element.gst_videoconvert is not None

    def test_has_sink_pad(self):
        pipeline = Gst.Pipeline()
        element = VideoAlpha(pipeline)
        assert element._sink_pad is not None

    def test_compositor_background_is_black(self):
        pipeline = Gst.Pipeline()
        element = VideoAlpha(pipeline)
        bg = element.gst_compositor.get_property("background")
        # 1 = black in GstCompositorBackground enum
        assert bg == 1

    def test_sink_returns_none(self):
        """Not in the linear audio chain."""
        pipeline = Gst.Pipeline()
        element = VideoAlpha(pipeline)
        assert element.sink() is None

    def test_src_returns_none(self):
        """Not in the linear audio chain."""
        pipeline = Gst.Pipeline()
        element = VideoAlpha(pipeline)
        assert element.src() is None

    def test_video_sink_returns_compositor(self):
        pipeline = Gst.Pipeline()
        element = VideoAlpha(pipeline)
        assert element.video_sink() is element.gst_compositor

    def test_video_src_returns_videoconvert(self):
        pipeline = Gst.Pipeline()
        element = VideoAlpha(pipeline)
        assert element.video_src() is element.gst_videoconvert


class TestVideoAlphaLiveAlpha:
    def test_live_alpha_reads_from_pad(self):
        pipeline = Gst.Pipeline()
        element = VideoAlpha(pipeline)
        # Default pad alpha is 1.0
        assert element.live_alpha == 1.0

    def test_live_alpha_writes_to_pad(self):
        pipeline = Gst.Pipeline()
        element = VideoAlpha(pipeline)
        element.live_alpha = 0.5
        assert abs(element.live_alpha - 0.5) < 0.01

    def test_stop_restores_saved_alpha(self):
        pipeline = Gst.Pipeline()
        element = VideoAlpha(pipeline)
        element.alpha = 0.8
        element.live_alpha = 0.0
        element.stop()
        assert abs(element.live_alpha - 0.8) < 0.01


class TestVideoAlphaFader:
    def test_get_fader_returns_fader(self):
        pipeline = Gst.Pipeline()
        element = VideoAlpha(pipeline)
        fader = element.get_fader("live_alpha")
        assert fader is not None

    def test_get_fader_unknown_returns_none(self):
        pipeline = Gst.Pipeline()
        element = VideoAlpha(pipeline)
        fader = element.get_fader("nonexistent")
        assert fader is None


class TestVideoAlphaDispose:
    def test_dispose_removes_elements(self):
        pipeline = Gst.Pipeline()
        element = VideoAlpha(pipeline)
        comp_name = element.gst_compositor.get_name()
        conv_name = element.gst_videoconvert.get_name()

        element.dispose()

        assert pipeline.get_by_name(comp_name) is None
        assert pipeline.get_by_name(conv_name) is None
