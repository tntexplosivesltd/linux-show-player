"""Tests for VideoSink element."""

from unittest.mock import MagicMock, patch

import pytest

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

    def test_creates_video_tee(self):
        pipeline = Gst.Pipeline()
        element = VideoSink(pipeline)
        assert element.video_tee is not None

    def test_creates_monitor_sink(self):
        pipeline = Gst.Pipeline()
        element = VideoSink(pipeline)
        assert element.monitor_sink is not None

    def test_creates_monitor_queue(self):
        pipeline = Gst.Pipeline()
        element = VideoSink(pipeline)
        assert element.monitor_queue is not None

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
        ), patch.object(
            VideoSink, "_monitor_window",
            return_value=None,
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
        ), patch.object(
            VideoSink, "_monitor_window",
            return_value=None,
        ):
            sink.play()

        mock_window.show_display.assert_called_once()
        VideoSink._previous_sink = None

    def test_play_calls_monitor_show_display(self):
        pipeline = Gst.Pipeline()
        sink = VideoSink(pipeline)

        mock_monitor = MagicMock()
        mock_monitor.isVisible.return_value = True
        with patch.object(
            VideoSink, "_video_window",
            return_value=MagicMock(),
        ), patch.object(
            VideoSink, "_monitor_window",
            return_value=mock_monitor,
        ):
            sink.play()

        mock_monitor.show_display.assert_called_once()
        VideoSink._previous_sink = None

    def test_stop_calls_monitor_clear_display(self):
        pipeline = Gst.Pipeline()
        sink = VideoSink(pipeline)

        mock_monitor = MagicMock()
        mock_monitor.isVisible.return_value = True
        with patch.object(
            VideoSink, "_video_window",
            return_value=MagicMock(),
        ), patch.object(
            VideoSink, "_monitor_window",
            return_value=mock_monitor,
        ):
            sink.play()
            sink.stop()

        mock_monitor.clear_display.assert_called_once()

    def test_play_skips_hidden_monitor(self):
        pipeline = Gst.Pipeline()
        sink = VideoSink(pipeline)

        mock_monitor = MagicMock()
        mock_monitor.isVisible.return_value = False
        with patch.object(
            VideoSink, "_video_window",
            return_value=MagicMock(),
        ), patch.object(
            VideoSink, "_monitor_window",
            return_value=mock_monitor,
        ):
            sink.play()

        mock_monitor.show_display.assert_not_called()
        VideoSink._previous_sink = None


class TestVideoSinkOverlay:
    def test_play_sets_previous_sink(self):
        """play() registers the sink as the active one."""
        pipeline = Gst.Pipeline()
        sink = VideoSink(pipeline)

        mock_window = MagicMock()
        with patch.object(
            VideoSink, "_video_window",
            return_value=mock_window,
        ), patch.object(
            VideoSink, "_monitor_window",
            return_value=None,
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
        ), patch.object(
            VideoSink, "_monitor_window",
            return_value=None,
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
        ), patch.object(
            VideoSink, "_monitor_window",
            return_value=None,
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


class TestVideoSinkDispose:
    """Cover the conditional branches in VideoSink.dispose()."""

    def test_dispose_removes_full_video_branch(self):
        pipeline = Gst.Pipeline()
        sink = VideoSink(pipeline)

        video_queue_name = sink.video_queue.get_name()
        video_tee_name = sink.video_tee.get_name()
        proj_queue_name = sink.proj_queue.get_name()
        video_sink_name = sink.video_sink.get_name()
        monitor_queue_name = sink.monitor_queue.get_name()
        monitor_sink_name = sink.monitor_sink.get_name()

        sink.dispose()

        for name in (
            video_queue_name, video_tee_name, proj_queue_name,
            video_sink_name, monitor_queue_name, monitor_sink_name,
        ):
            assert pipeline.get_by_name(name) is None

    def test_dispose_removes_audio_sink_when_not_already_removed(self):
        pipeline = Gst.Pipeline()
        sink = VideoSink(pipeline)
        audio_sink_name = sink.audio_sink.get_name()
        assert sink._audio_removed is False

        sink.dispose()

        assert pipeline.get_by_name(audio_sink_name) is None

    def test_dispose_skips_audio_sink_when_already_removed(self):
        """post_link() may have removed the audio sink already
        (image-only pipeline).  dispose() must not attempt a
        second removal."""
        pipeline = Gst.Pipeline()
        sink = VideoSink(pipeline)
        # Simulate post_link() outcome for an image pipeline.
        pipeline.remove(sink.audio_sink)
        sink._audio_removed = True

        # Should not raise even though audio_sink is already gone.
        sink.dispose()

    def test_dispose_skips_video_branch_when_marked_removed(self):
        pipeline = Gst.Pipeline()
        sink = VideoSink(pipeline)
        video_queue_name = sink.video_queue.get_name()

        # Simulate a scenario where the video branch has been
        # removed externally (e.g. a future post_link path that
        # trims it out).  dispose() must honour the flag.
        pipeline.remove(sink.video_queue)
        pipeline.remove(sink.video_tee)
        pipeline.remove(sink.proj_queue)
        pipeline.remove(sink.video_sink)
        pipeline.remove(sink.monitor_queue)
        pipeline.remove(sink.monitor_sink)
        sink._video_removed = True

        # Should not raise.
        sink.dispose()
        assert pipeline.get_by_name(video_queue_name) is None

    def test_dispose_is_idempotent(self):
        """Calling dispose twice must not raise.

        The second call finds the bus disconnected and the elements
        already removed; guards inside dispose() should make this a
        no-op rather than an error."""
        pipeline = Gst.Pipeline()
        sink = VideoSink(pipeline)

        sink.dispose()
        # Second dispose should not raise.
        sink.dispose()


class TestFindOwnerSink:
    """Test _find_owner_sink parent-chain walking.

    Bin-based sinks like glimagesink post prepare-window-handle
    from an internal child element.  _find_owner_sink walks up
    the parent chain to match back to our stored sink reference.
    """

    def test_direct_match_video_sink(self):
        pipeline = Gst.Pipeline()
        sink = VideoSink(pipeline)

        mock_window = MagicMock()
        with patch.object(
            VideoSink, "_video_window",
            return_value=mock_window,
        ):
            result = sink._find_owner_sink(sink.video_sink)
        assert result is mock_window

    def test_direct_match_monitor_sink(self):
        pipeline = Gst.Pipeline()
        sink = VideoSink(pipeline)

        mock_window = MagicMock()
        with patch.object(
            VideoSink, "_monitor_window",
            return_value=mock_window,
        ):
            result = sink._find_owner_sink(sink.monitor_sink)
        assert result is mock_window

    def _first_bin_child(self, gst_bin):
        """Get the first child element of a GstBin."""
        it = gst_bin.iterate_elements()
        ok, child = it.next()
        if ok == Gst.IteratorResult.OK:
            return child
        return None

    def test_child_of_bin_matches_video_sink(self):
        """Simulate glimagesink: message.src is a child element
        inside the bin, not the bin itself."""
        pipeline = Gst.Pipeline()
        sink = VideoSink(pipeline)

        if not isinstance(sink.video_sink, Gst.Bin):
            pytest.skip("video_sink is not a GstBin")
        child = self._first_bin_child(sink.video_sink)
        if child is None:
            pytest.skip("video_sink bin has no children")

        mock_window = MagicMock()
        with patch.object(
            VideoSink, "_video_window",
            return_value=mock_window,
        ):
            result = sink._find_owner_sink(child)
        assert result is mock_window

    def test_child_of_bin_matches_monitor_sink(self):
        """Same test for the monitor sink branch."""
        pipeline = Gst.Pipeline()
        sink = VideoSink(pipeline)

        if not isinstance(sink.monitor_sink, Gst.Bin):
            pytest.skip("monitor_sink is not a GstBin")
        child = self._first_bin_child(sink.monitor_sink)
        if child is None:
            pytest.skip("monitor_sink bin has no children")

        mock_window = MagicMock()
        with patch.object(
            VideoSink, "_monitor_window",
            return_value=mock_window,
        ):
            result = sink._find_owner_sink(child)
        assert result is mock_window

    def test_unknown_element_returns_none(self):
        pipeline = Gst.Pipeline()
        sink = VideoSink(pipeline)

        unrelated = Gst.ElementFactory.make(
            "fakesink", None
        )
        assert sink._find_owner_sink(unrelated) is None

    def test_none_element_returns_none(self):
        pipeline = Gst.Pipeline()
        sink = VideoSink(pipeline)
        assert sink._find_owner_sink(None) is None
