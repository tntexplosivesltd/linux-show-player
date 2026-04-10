"""Tests for GstMediaElement post_link and video_src hooks."""

from lisp.plugins.gst_backend.gi_repository import Gst
from lisp.plugins.gst_backend.gst_element import GstMediaElement


class TestGstMediaElementHooks:
    def test_video_src_returns_none_by_default(self):
        pipeline = Gst.Pipeline()
        element = GstMediaElement(pipeline)
        assert element.video_src() is None

    def test_post_link_is_noop(self):
        pipeline = Gst.Pipeline()
        element = GstMediaElement(pipeline)
        # Should not raise
        element.post_link([element])

    def test_post_link_accepts_empty_list(self):
        pipeline = Gst.Pipeline()
        element = GstMediaElement(pipeline)
        element.post_link([])
