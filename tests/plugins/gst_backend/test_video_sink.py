"""Tests for VideoSink element."""

from unittest.mock import MagicMock, patch

from lisp.backend.media_element import ElementType, MediaType
from lisp.plugins.gst_backend.gi_repository import Gst
from lisp.plugins.gst_backend import video_compositor as vc
from lisp.plugins.gst_backend.elements.video_sink import (
    LATENCY_REFRESH_BUFFERS,
    LATENCY_WARMUP_BUFFERS,
    PUMP_LEAD,
    VideoSink,
    cue_latency_due,
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


def _vcaps(width=320, height=240):
    return Gst.Caps.from_string(
        f"video/x-raw,format=I420,width={width},height={height},"
        "pixel-aspect-ratio=1/1,framerate=30/1")


class TestVideoSinkPump:
    """Pump contract 3: PTS = rt + base diff + (L_cue − L_proj). L_cue
    is re-queried per buffer while the cue settles, then periodically;
    L_proj comes from the compositor's shared cache."""

    _QL = "lisp.plugins.gst_backend.elements.video_sink.query_min_latency"

    def _setup(self, caps=None):
        pipeline = MagicMock()
        pipeline.get_base_time.return_value = 11500 * Gst.MSECOND
        with patch("lisp.plugins.gst_backend.elements.video_sink."
                   "Gst.ElementFactory"):
            sink = VideoSink(pipeline)
        comp = MagicMock()
        comp.pipeline.get_base_time.return_value = 10000 * Gst.MSECOND
        comp.latency.return_value = 86 * Gst.MSECOND
        comp.clock.return_value.get_time.return_value = (
            10750 * Gst.MSECOND)

        def fit(reg, new_caps):
            reg.caps = new_caps

        comp.fit_registration.side_effect = fit
        reg = vc.Registration()
        reg.appsrc = MagicMock()
        reg.appsrc.push_buffer.return_value = Gst.FlowReturn.OK
        comp.register.return_value = reg
        with patch(_CM, return_value=comp):
            sink.play()

        buf = MagicMock()
        buf.pts = 2000 * Gst.MSECOND
        sample = MagicMock()
        sample.get_buffer.return_value = buf
        sample.get_caps.return_value = caps or _vcaps()
        sample.get_segment.return_value.to_running_time.return_value = (
            2000 * Gst.MSECOND)
        appsink = MagicMock()
        appsink.pull_sample.return_value = sample
        appsink.pull_preroll.return_value = sample
        return sink, comp, reg, buf, sample, appsink

    def _run(self, sink, appsink, n=1, preroll=False, ql=0):
        fn = (sink._VideoSink__on_new_preroll if preroll
              else sink._VideoSink__on_new_sample)
        with patch(self._QL, return_value=ql) as query:
            rets = [fn(appsink) for _ in range(n)]
        return rets, query

    def test_pushed_pts_includes_latency_offset(self):
        sink, comp, reg, buf, _, appsink = self._setup()
        rets, _ = self._run(sink, appsink)
        out = buf.copy.return_value
        assert out.pts == (2000 + 1500 - 86) * Gst.MSECOND
        reg.appsrc.push_buffer.assert_called_once_with(out)
        assert rets == [Gst.FlowReturn.OK]

    def test_projection_latency_comes_from_compositor_cache(self):
        sink, comp, reg, buf, _, appsink = self._setup()
        _, query = self._run(sink, appsink, n=3)
        assert comp.latency.call_count == 3
        for call in query.call_args_list:
            assert call.args[0] is sink.pipeline  # never the projection

    def test_cue_latency_due_policy(self):
        due = [cue_latency_due(i) for i in range(LATENCY_WARMUP_BUFFERS)]
        assert all(due)  # every buffer while the cue settles
        later = range(LATENCY_WARMUP_BUFFERS,
                      LATENCY_WARMUP_BUFFERS + 3 * LATENCY_REFRESH_BUFFERS)
        assert [i for i in later if cue_latency_due(i)] == [
            i for i in later if i % LATENCY_REFRESH_BUFFERS == 0]

    def test_cue_latency_change_during_warmup_applies_next_buffer(self):
        # The first-second A/V offset: a latency that settles after the
        # first buffer must be picked up straight away, not ~1s later.
        sink, comp, reg, buf, _, appsink = self._setup()
        self._run(sink, appsink, ql=0)
        self._run(sink, appsink, ql=50 * Gst.MSECOND)
        out = buf.copy.return_value
        assert out.pts == (2000 + 1500 + 50 - 86) * Gst.MSECOND

    def test_first_sample_sets_caps_fits_and_signals_frame(self):
        sink, comp, reg, buf, sample, appsink = self._setup()
        self._run(sink, appsink, n=3)
        caps = sample.get_caps.return_value
        reg.appsrc.set_property.assert_called_once_with("caps", caps)
        comp.fit_registration.assert_called_once_with(reg, caps)
        comp.frame_ready.assert_called_once_with(reg)

    def test_mid_stream_caps_change_refits(self):
        sink, comp, reg, buf, sample, appsink = self._setup()
        self._run(sink, appsink)
        wide = _vcaps(640, 240)
        sample.get_caps.return_value = wide
        self._run(sink, appsink)
        reg.appsrc.set_property.assert_called_with("caps", wide)
        assert comp.fit_registration.call_count == 2
        assert reg.caps is wide

    def test_none_running_time_is_skipped(self):
        sink, comp, reg, buf, sample, appsink = self._setup()
        sample.get_segment.return_value.to_running_time.return_value = (
            Gst.CLOCK_TIME_NONE)
        rets, _ = self._run(sink, appsink)
        reg.appsrc.push_buffer.assert_not_called()
        assert rets == [Gst.FlowReturn.OK]

    def test_unregistered_sample_is_dropped(self):
        sink, comp, reg, buf, _, appsink = self._setup()
        sink._registration = None
        rets, _ = self._run(sink, appsink)
        reg.appsrc.push_buffer.assert_not_called()
        assert rets == [Gst.FlowReturn.OK]

    def test_compositor_shut_down_drops(self):
        sink, comp, reg, buf, _, appsink = self._setup()
        comp.pipeline = None
        self._run(sink, appsink)
        reg.appsrc.push_buffer.assert_not_called()

    def test_failed_push_is_logged_once(self, caplog):
        sink, comp, reg, buf, _, appsink = self._setup()
        reg.appsrc.push_buffer.return_value = Gst.FlowReturn.FLUSHING
        self._run(sink, appsink, n=5)
        warnings = [r for r in caplog.records
                    if "projection push" in r.getMessage()]
        assert len(warnings) == 1

    def test_pump_does_not_look_up_compositor(self):
        # play() caches it; the streaming thread must not do the lazy
        # GstBackend import.
        sink, comp, reg, buf, _, appsink = self._setup()
        with patch(_CM) as lookup:
            self._run(sink, appsink)
        lookup.assert_not_called()


class TestVideoSinkPreroll:
    """Tier 2 #10: a paused seek re-prerolls the cue; that frame must
    reach the projection (the old glimagesink showed it)."""

    _setup = TestVideoSinkPump._setup
    _run = TestVideoSinkPump._run
    _QL = TestVideoSinkPump._QL

    def test_preroll_frame_is_stamped_now(self):
        sink, comp, reg, buf, _, appsink = self._setup()
        rets, _ = self._run(sink, appsink, preroll=True)
        out = buf.copy.return_value
        # clock 10.75s − projection base 10s = 750ms running time.
        assert out.pts == 750 * Gst.MSECOND
        reg.appsrc.push_buffer.assert_called_once_with(out)
        comp.frame_ready.assert_called_once_with(reg)
        assert rets == [Gst.FlowReturn.OK]

    def test_first_preroll_does_not_flush(self):
        sink, comp, reg, buf, _, appsink = self._setup()
        self._run(sink, appsink, preroll=True)
        reg.appsrc.send_event.assert_not_called()

    def test_re_preroll_flushes_stale_frames_first(self):
        sink, comp, reg, buf, _, appsink = self._setup()
        self._run(sink, appsink)  # playing
        calls = MagicMock()
        calls.attach_mock(reg.appsrc.send_event, "event")
        calls.attach_mock(reg.appsrc.push_buffer, "push")
        self._run(sink, appsink, preroll=True)  # seek while paused
        names = [c[0] for c in calls.mock_calls]
        assert names == ["event", "event", "push"]
        start, stop = (c.args[0] for c in reg.appsrc.send_event.call_args_list)
        assert start.type == Gst.EventType.FLUSH_START
        assert stop.type == Gst.EventType.FLUSH_STOP

    def test_preroll_when_not_registered_is_dropped(self):
        # A prearmed (not yet playing) cue prerolls without a
        # registration: nothing may reach the projection.
        sink, comp, reg, buf, _, appsink = self._setup()
        sink._registration = None
        self._run(sink, appsink, preroll=True)
        reg.appsrc.push_buffer.assert_not_called()

    def test_preroll_handler_disconnected_on_dispose(self):
        pipeline = Gst.Pipeline()
        sink = VideoSink(pipeline)
        with patch(_CM, return_value=None):
            sink.dispose()
        assert sink._preroll_handler is None


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
