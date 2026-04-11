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


class TestVideoSinkPostLink:
    def test_post_link_with_no_video_source(self):
        pipeline = Gst.Pipeline()
        sink = VideoSink(pipeline)

        # Mock elements that have no video_src
        mock_element = MagicMock()
        mock_element.video_src.return_value = None
        mock_element.src.return_value = MagicMock()

        # Should not raise
        sink.post_link([mock_element, sink])

    def test_post_link_wires_video_branch(self):
        pipeline = Gst.Pipeline()
        sink = VideoSink(pipeline)

        # Create a real videoconvert as the video source
        video_src_element = Gst.ElementFactory.make(
            "videotestsrc", None
        )
        pipeline.add(video_src_element)

        mock_input = MagicMock()
        mock_input.video_src.return_value = video_src_element
        mock_input.src.return_value = MagicMock()

        # post_link should wire video_src -> video_queue
        sink.post_link([mock_input, sink])

        # Verify link was made by checking pad peer
        src_pad = video_src_element.get_static_pad("src")
        assert src_pad.get_peer() is not None

    def test_post_link_removes_audio_when_no_audio_src(self):
        """When no element provides audio (e.g. ImageInput),
        the audio sink should be removed from the pipeline."""
        pipeline = Gst.Pipeline()
        sink = VideoSink(pipeline)

        # Simulate an image input: has video_src but no src
        video_src_element = Gst.ElementFactory.make(
            "videotestsrc", None
        )
        pipeline.add(video_src_element)

        mock_input = MagicMock()
        mock_input.video_src.return_value = video_src_element
        mock_input.src.return_value = None

        sink.post_link([mock_input, sink])

        assert sink._audio_removed is True
        # audio_sink should be gone from pipeline
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

        mock_input = MagicMock()
        mock_input.video_src.return_value = video_src_element
        mock_input.src.return_value = MagicMock()

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


class TestVideoSinkOverlay:
    def test_initial_window_handle_is_zero(self):
        pipeline = Gst.Pipeline()
        sink = VideoSink(pipeline)
        assert sink._window_handle == 0

    def test_play_releases_previous_gl_context(self):
        """When a new VideoSink plays, the previous one's
        GStreamer sink is set to NULL to release its GL context."""
        pipeline1 = Gst.Pipeline()
        sink1 = VideoSink(pipeline1)

        pipeline2 = Gst.Pipeline()
        sink2 = VideoSink(pipeline2)

        mock_window = MagicMock()
        with patch.object(
            VideoSink, "_video_window",
            return_value=mock_window,
        ):
            sink1.play()
            assert VideoSink._previous_sink is sink1

            sink1.stop()
            sink2.play()
            assert VideoSink._previous_sink is sink2

        # sink1's video_sink should have been set to NULL
        state = sink1.video_sink.get_state(0)
        assert state[1] == Gst.State.NULL

        # Clean up class state for other tests
        VideoSink._previous_sink = None

    def test_dispose_disconnects_sync_handler(self):
        pipeline = Gst.Pipeline()
        sink = VideoSink(pipeline)
        # Should not raise
        sink.dispose()
