"""Tests for VideoSink element."""

from unittest.mock import MagicMock, patch

from lisp.backend.media_element import ElementType, MediaType
from lisp.plugins.gst_backend.gi_repository import Gst
from lisp.plugins.gst_backend.elements.video_sink import (
    LATENCY_REFRESH_BUFFERS,
    PUMP_LEAD,
    VideoSink,
)

# Patch the classmethod on the class itself (canonical location):
# video_sink._compositor() does a lazy `from ... import GstBackend`
# that resolves to this same class object, so the patch applies.
_CM = "lisp.plugins.gst_backend.gst_backend.GstBackend.video_compositor"


class TestVideoSinkProperties:
    def test_media_type(self):
        assert VideoSink.MediaType == MediaType.AudioAndVideo

    def test_element_type(self):
        assert VideoSink.ElementType == ElementType.Output


class TestVideoSinkConstruction:
    def test_creates_audio_sink(self):
        pipeline = Gst.Pipeline()
        sink = VideoSink(pipeline)
        assert sink.audio_sink is not None

    def test_sink_returns_audio_sink(self):
        pipeline = Gst.Pipeline()
        sink = VideoSink(pipeline)
        assert sink.sink() is sink.audio_sink

    def test_creates_appsink_not_glimagesink(self):
        pipeline = Gst.Pipeline()
        sink = VideoSink(pipeline)
        assert sink.video_appsink is not None
        assert sink.video_appsink.get_factory().get_name() == "appsink"
        # No projection/monitor sink or tee any more.
        assert not hasattr(sink, "video_tee")
        assert not hasattr(sink, "monitor_sink")

    def test_appsink_is_bounded_drop_oldest(self):
        pipeline = Gst.Pipeline()
        sink = VideoSink(pipeline)
        assert sink.video_appsink.get_property("drop") is True
        assert sink.video_appsink.get_property("max-buffers") <= 4
        assert sink.video_appsink.get_property("emit-signals") is True

    def test_appsink_is_clock_synced_with_bounded_lead(self):
        # Pump contract 1: sync=False runs seconds ahead and video
        # keeps playing through a pause (Phase 1 spike).
        pipeline = Gst.Pipeline()
        sink = VideoSink(pipeline)
        assert sink.video_appsink.get_property("sync") is True
        assert sink.video_appsink.get_property("ts-offset") == -PUMP_LEAD
        assert 0 < PUMP_LEAD <= 200 * Gst.MSECOND


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


class TestVideoSinkRegistration:
    def _sink_with_compositor(self):
        pipeline = Gst.Pipeline()
        sink = VideoSink(pipeline)
        comp = MagicMock()
        reg = MagicMock()
        reg.appsrc = MagicMock()
        reg.caps_set = False
        comp.register.return_value = reg
        return sink, comp, reg

    def test_play_registers_with_compositor(self):
        sink, comp, reg = self._sink_with_compositor()
        with patch(_CM, return_value=comp):
            sink.play()
        comp.register.assert_called_once_with(sink)
        assert sink._registration is reg

    def test_stop_unregisters(self):
        sink, comp, reg = self._sink_with_compositor()
        with patch(_CM, return_value=comp):
            sink.play()
            sink.stop()
        comp.unregister.assert_called_once_with(sink)
        assert sink._registration is None

    def test_eos_unregisters(self):
        sink, comp, reg = self._sink_with_compositor()
        with patch(_CM, return_value=comp):
            sink.play()
            sink.eos()
        comp.unregister.assert_called_once_with(sink)

    def test_dispose_unregisters(self):
        sink, comp, reg = self._sink_with_compositor()
        with patch(_CM, return_value=comp):
            sink.play()
            sink.dispose()
        comp.unregister.assert_called_once_with(sink)
        assert sink._registration is None

    def test_play_no_compositor_is_safe(self):
        pipeline = Gst.Pipeline()
        sink = VideoSink(pipeline)
        with patch(_CM, return_value=None):
            sink.play()  # must not raise
        assert sink._registration is None


class TestVideoSinkPump:
    """Pump contract 3: PTS = rt + base diff + (L_cue − L_proj), with
    the latency term cached and periodically re-queried."""

    _QL = "lisp.plugins.gst_backend.elements.video_sink.query_min_latency"

    def _setup(self):
        pipeline = MagicMock()
        pipeline.get_base_time.return_value = 11500 * Gst.MSECOND
        with patch("lisp.plugins.gst_backend.elements.video_sink."
                   "Gst.ElementFactory"):
            sink = VideoSink(pipeline)
        comp = MagicMock()
        comp.pipeline.get_base_time.return_value = 10000 * Gst.MSECOND
        self._proj = comp.pipeline
        reg = MagicMock()
        reg.caps_set = True
        reg.latency_offset = 0
        reg.latency_countdown = 0
        sink._registration = reg

        buf = MagicMock()
        buf.pts = 2000 * Gst.MSECOND
        sample = MagicMock()
        sample.get_buffer.return_value = buf
        sample.get_segment.return_value.to_running_time.return_value = (
            2000 * Gst.MSECOND)
        appsink = MagicMock()
        appsink.emit.return_value = sample
        return sink, comp, reg, buf, appsink

    def _latency(self, pipeline):
        # Cue pipelines report 0; the live projection reports 86ms.
        return 86 * Gst.MSECOND if pipeline is self._proj else 0

    def test_pushed_pts_includes_latency_offset(self):
        sink, comp, reg, buf, appsink = self._setup()
        with patch(_CM, return_value=comp), \
                patch(self._QL, side_effect=self._latency):
            ret = sink._VideoSink__on_new_sample(appsink)
        out = buf.copy.return_value
        assert out.pts == (2000 + 1500 - 86) * Gst.MSECOND
        reg.appsrc.emit.assert_called_once_with("push-buffer", out)
        assert ret == Gst.FlowReturn.OK

    def test_latency_cached_between_refreshes(self):
        sink, comp, reg, buf, appsink = self._setup()
        with patch(_CM, return_value=comp), \
                patch(self._QL, side_effect=self._latency) as ql:
            for _ in range(LATENCY_REFRESH_BUFFERS):
                sink._VideoSink__on_new_sample(appsink)
        # One refresh = two queries (cue + projection), then cached.
        assert ql.call_count == 2

    def test_first_sample_sets_appsrc_caps(self):
        sink, comp, reg, buf, appsink = self._setup()
        reg.caps_set = False
        with patch(_CM, return_value=comp), \
                patch(self._QL, return_value=0):
            sink._VideoSink__on_new_sample(appsink)
        caps = appsink.emit.return_value.get_caps.return_value
        reg.appsrc.set_property.assert_called_once_with("caps", caps)
        # Scale-to-fit the canvas, as the per-cue glimagesink used to.
        comp.fit_registration.assert_called_once_with(reg, caps)
        assert reg.caps_set is True

    def test_unregistered_sample_is_dropped(self):
        sink, comp, reg, buf, appsink = self._setup()
        sink._registration = None
        with patch(_CM, return_value=comp):
            ret = sink._VideoSink__on_new_sample(appsink)
        reg.appsrc.emit.assert_not_called()
        assert ret == Gst.FlowReturn.OK


class TestVideoSinkDispose:
    """Cover the conditional branches in VideoSink.dispose()."""

    def test_dispose_removes_video_branch(self):
        pipeline = Gst.Pipeline()
        sink = VideoSink(pipeline)
        names = (sink.video_queue.get_name(),
                 sink.video_appsink.get_name())
        with patch(_CM, return_value=None):
            sink.dispose()
        for name in names:
            assert pipeline.get_by_name(name) is None

    def test_dispose_removes_audio_sink_when_not_already_removed(self):
        pipeline = Gst.Pipeline()
        sink = VideoSink(pipeline)
        audio_sink_name = sink.audio_sink.get_name()
        assert sink._audio_removed is False
        with patch(_CM, return_value=None):
            sink.dispose()
        assert pipeline.get_by_name(audio_sink_name) is None

    def test_dispose_skips_audio_sink_when_already_removed(self):
        """post_link() may have removed the audio sink already
        (image-only pipeline).  dispose() must not attempt a
        second removal."""
        pipeline = Gst.Pipeline()
        sink = VideoSink(pipeline)
        pipeline.remove(sink.audio_sink)
        sink._audio_removed = True
        with patch(_CM, return_value=None):
            sink.dispose()  # must not raise

    def test_dispose_is_idempotent(self):
        pipeline = Gst.Pipeline()
        sink = VideoSink(pipeline)
        with patch(_CM, return_value=None):
            sink.dispose()
            sink.dispose()  # must not raise
