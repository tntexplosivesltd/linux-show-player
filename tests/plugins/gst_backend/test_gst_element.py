"""Tests for GstMediaElement hooks and GstMediaElements linking."""

from lisp.plugins.gst_backend.gi_repository import Gst
from lisp.plugins.gst_backend.gst_element import (
    GstMediaElement,
    GstMediaElements,
)


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


class _AudioElement(GstMediaElement):
    """Element with real GStreamer src/sink for audio chain."""

    def __init__(self, pipeline):
        super().__init__(pipeline)
        self._convert = Gst.ElementFactory.make(
            "audioconvert", None
        )
        pipeline.add(self._convert)

    def sink(self):
        return self._convert

    def src(self):
        return self._convert


class _VideoOnlyElement(GstMediaElement):
    """Element with no audio sink/src (like VideoAlpha)."""

    def sink(self):
        return None

    def src(self):
        return None


class _SinkElement(GstMediaElement):
    """Terminal audio sink element."""

    def __init__(self, pipeline):
        super().__init__(pipeline)
        self._sink = Gst.ElementFactory.make(
            "fakesink", None
        )
        pipeline.add(self._sink)

    def sink(self):
        return self._sink

    def src(self):
        return None


class TestGstMediaElementsAppend:
    def test_linear_chain_links(self):
        """Two audio elements link src->sink."""
        pipeline = Gst.Pipeline()
        elements = GstMediaElements()

        a = _AudioElement(pipeline)
        b = _SinkElement(pipeline)
        elements.append(a)
        elements.append(b)

        pad = a.src().get_static_pad("src")
        assert pad.get_peer() is not None

    def test_skips_video_only_element(self):
        """append() skips a video-only element (sink()=None)
        and links to the nearest audio-capable predecessor."""
        pipeline = Gst.Pipeline()
        elements = GstMediaElements()

        a = _AudioElement(pipeline)
        v = _VideoOnlyElement(pipeline)
        b = _SinkElement(pipeline)

        elements.append(a)
        elements.append(v)
        elements.append(b)

        # a should be linked to b, skipping v
        pad = a.src().get_static_pad("src")
        assert pad.get_peer() is not None

    def test_video_only_element_not_linked(self):
        """A video-only element doesn't get linked into the
        audio chain."""
        pipeline = Gst.Pipeline()
        elements = GstMediaElements()

        a = _AudioElement(pipeline)
        v = _VideoOnlyElement(pipeline)
        b = _SinkElement(pipeline)

        elements.append(a)
        elements.append(v)
        elements.append(b)

        assert len(elements) == 3
        assert elements[1] is v
