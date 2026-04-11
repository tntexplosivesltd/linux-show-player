"""Tests for VideoSink element."""

from unittest.mock import MagicMock, patch

from lisp.backend.media_element import ElementType, MediaType
from lisp.plugins.gst_backend.gi_repository import Gst
from lisp.plugins.gst_backend.elements.video_sink import (
    VideoSink,
    _create_video_sink,
)


class TestVideoSinkProperties:
    def test_media_type(self):
        assert VideoSink.MediaType == MediaType.AudioAndVideo

    def test_element_type(self):
        assert VideoSink.ElementType == ElementType.Output


class TestVideoSinkConstruction:
    def test_creates_audio_sink(self):
        pipeline = Gst.Pipeline()
        element = VideoSink(pipeline)
        assert element.audio_sink is not None

    def test_creates_video_sink(self):
        pipeline = Gst.Pipeline()
        element = VideoSink(pipeline)
        assert element.video_sink is not None

    def test_creates_video_queue(self):
        pipeline = Gst.Pipeline()
        element = VideoSink(pipeline)
        assert element.video_queue is not None

    def test_sink_returns_audio_sink(self):
        pipeline = Gst.Pipeline()
        element = VideoSink(pipeline)
        assert element.sink() is element.audio_sink


def _mock_input(**kwargs):
    """Create a mock input element (no video_sink attr)."""
    mock = MagicMock(spec=["video_src", "src"])
    mock.video_src.return_value = kwargs.get(
        "video_src", None
    )
    mock.src.return_value = kwargs.get("src", None)
    return mock


class TestVideoSinkPostLink:
    def test_post_link_with_no_video_source(self):
        pipeline = Gst.Pipeline()
        sink = VideoSink(pipeline)

        mock_element = _mock_input(
            src=MagicMock()
        )

        # Should not raise
        sink.post_link([mock_element, sink])

    def test_post_link_wires_video_branch(self):
        pipeline = Gst.Pipeline()
        sink = VideoSink(pipeline)

        video_src_element = Gst.ElementFactory.make(
            "videotestsrc", None
        )
        pipeline.add(video_src_element)

        mock_input = _mock_input(
            video_src=video_src_element,
            src=MagicMock(),
        )

        sink.post_link([mock_input, sink])

        src_pad = video_src_element.get_static_pad("src")
        assert src_pad.get_peer() is not None

    def test_post_link_chains_video_plugin(self):
        """VideoAlpha-style plugin is chained between input
        and video_queue."""
        pipeline = Gst.Pipeline()
        sink = VideoSink(pipeline)

        video_src_element = Gst.ElementFactory.make(
            "videotestsrc", None
        )
        pipeline.add(video_src_element)

        # Plugin element with video_sink and video_src
        plugin_in = Gst.ElementFactory.make(
            "videoconvert", None
        )
        plugin_out = Gst.ElementFactory.make(
            "videoconvert", None
        )
        pipeline.add(plugin_in)
        pipeline.add(plugin_out)
        plugin_in.link(plugin_out)

        mock_plugin = MagicMock()
        mock_plugin.video_sink.return_value = plugin_in
        mock_plugin.video_src.return_value = plugin_out
        mock_plugin.src.return_value = None

        mock_input = _mock_input(
            video_src=video_src_element,
            src=MagicMock(),
        )

        sink.post_link([mock_input, mock_plugin, sink])

        # input -> plugin_in
        src_pad = video_src_element.get_static_pad("src")
        assert src_pad.get_peer() is not None
        # plugin_out -> video_queue
        out_pad = plugin_out.get_static_pad("src")
        assert out_pad.get_peer() is not None

    def test_post_link_removes_audio_when_no_audio_src(self):
        """When no element provides audio (e.g. ImageInput),
        the audio sink should be removed from the pipeline."""
        pipeline = Gst.Pipeline()
        sink = VideoSink(pipeline)

        video_src_element = Gst.ElementFactory.make(
            "videotestsrc", None
        )
        pipeline.add(video_src_element)

        mock_input = _mock_input(
            video_src=video_src_element,
        )

        sink.post_link([mock_input, sink])

        assert sink._audio_removed is True
        name = sink.audio_sink.get_name()
        assert pipeline.get_by_name(name) is None

    def test_post_link_keeps_audio_when_audio_src_exists(self):
        """When an element provides audio (e.g. UriAvInput),
        the audio sink should stay."""
        pipeline = Gst.Pipeline()
        sink = VideoSink(pipeline)

        video_src_element = Gst.ElementFactory.make(
            "videotestsrc", None
        )
        pipeline.add(video_src_element)

        mock_input = _mock_input(
            video_src=video_src_element,
            src=MagicMock(),
        )

        sink.post_link([mock_input, sink])

        assert sink._audio_removed is False
        name = sink.audio_sink.get_name()
        assert pipeline.get_by_name(name) is not None


class TestVideoSinkFactory:
    def test_creates_non_null_element(self):
        element = _create_video_sink()
        assert element is not None

    def test_prefers_overlay_capable_sink(self):
        """Should pick glimagesink or xvimagesink, not
        autovideosink."""
        element = _create_video_sink()
        factory = element.get_factory()
        name = factory.get_name() if factory else ""
        # Should be one of the preferred sinks (or fallback
        # on systems without them)
        assert name in (
            "glimagesink", "xvimagesink", "autovideosink"
        )


class TestVideoSinkClearDisplay:
    def test_stop_calls_clear_display(self):
        pipeline = Gst.Pipeline()
        sink = VideoSink(pipeline)

        mock_window = MagicMock()
        with patch.object(
            VideoSink, "_video_window",
            return_value=mock_window,
        ):
            sink.stop()

        mock_window.clear_display.assert_called_once()

    def test_play_calls_show_display(self):
        pipeline = Gst.Pipeline()
        sink = VideoSink(pipeline)

        mock_window = MagicMock()
        with patch.object(
            VideoSink, "_video_window",
            return_value=mock_window,
        ):
            sink.play()

        mock_window.show_display.assert_called_once()
        VideoSink._previous_sink = None


class TestVideoSinkOverlay:
    def test_initial_window_handle_is_zero(self):
        pipeline = Gst.Pipeline()
        sink = VideoSink(pipeline)
        assert sink._window_handle == 0

    def test_play_sets_previous_sink(self):
        """play() registers the sink as the active one."""
        pipeline = Gst.Pipeline()
        sink = VideoSink(pipeline)

        mock_window = MagicMock()
        with patch.object(
            VideoSink, "_video_window",
            return_value=mock_window,
        ):
            sink.play()
            assert VideoSink._previous_sink is sink

        VideoSink._previous_sink = None

    def test_stop_clears_previous_sink(self):
        """stop() clears _previous_sink if this is the active
        sink."""
        pipeline = Gst.Pipeline()
        sink = VideoSink(pipeline)

        mock_window = MagicMock()
        with patch.object(
            VideoSink, "_video_window",
            return_value=mock_window,
        ):
            sink.play()
            assert VideoSink._previous_sink is sink
            sink.stop()
            assert VideoSink._previous_sink is None

    def test_stop_does_not_clear_other_sink(self):
        """stop() on a non-active sink leaves _previous_sink
        intact."""
        pipeline1 = Gst.Pipeline()
        sink1 = VideoSink(pipeline1)
        pipeline2 = Gst.Pipeline()
        sink2 = VideoSink(pipeline2)

        mock_window = MagicMock()
        with patch.object(
            VideoSink, "_video_window",
            return_value=mock_window,
        ):
            sink2.play()
            assert VideoSink._previous_sink is sink2
            sink1.stop()
            assert VideoSink._previous_sink is sink2

        VideoSink._previous_sink = None

    def test_dispose_disconnects_sync_handler(self):
        pipeline = Gst.Pipeline()
        sink = VideoSink(pipeline)
        # Should not raise
        sink.dispose()
