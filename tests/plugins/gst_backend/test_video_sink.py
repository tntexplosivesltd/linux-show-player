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
    def teardown_method(self):
        # Don't leak the class-level pending-clear flag into the
        # next test.
        VideoSink._pending_clear = False

    def test_stop_does_not_clear_immediately(self):
        """stop() defers the clear so playlist auto-advance has a
        chance to cancel it.  The clear only fires after the defer
        timer expires (see _maybe_do_clear)."""
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

        mock_window.clear_display.assert_not_called()

    def test_stop_marks_pending_clear(self):
        pipeline = Gst.Pipeline()
        sink = VideoSink(pipeline)
        assert VideoSink._pending_clear is False
        sink.stop()
        assert VideoSink._pending_clear is True

    def test_show_displays_calls_show_on_window(self):
        """_show_displays is the deferred-show entry point.

        Invoked from the first-buffer pad probe (cold-start) or
        directly from play() when the pipeline already holds a
        prerolled buffer (Armed / Paused resume)."""
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
            sink._show_displays()

        mock_window.show_display.assert_called_once()

    def test_show_displays_calls_show_on_visible_monitor(self):
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
            sink._show_displays()

        mock_monitor.show_display.assert_called_once()

    def test_show_displays_skips_hidden_monitor(self):
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
            sink._show_displays()

        mock_monitor.show_display.assert_not_called()

    def test_maybe_do_clear_calls_clear_when_pending(self):
        """The QTimer callback path: when _pending_clear is True
        (set by a prior stop()), invoking _maybe_do_clear performs
        the clear and resets the flag."""
        pipeline = Gst.Pipeline()
        sink = VideoSink(pipeline)

        VideoSink._pending_clear = True

        mock_window = MagicMock()
        mock_monitor = MagicMock()
        mock_monitor.isVisible.return_value = True

        # _maybe_do_clear does a lazy import of GstBackend; patch the
        # class methods it calls.
        with patch(
            "lisp.plugins.gst_backend.gst_backend"
            ".GstBackend.video_window",
            return_value=mock_window,
        ), patch(
            "lisp.plugins.gst_backend.gst_backend"
            ".GstBackend.monitor_window",
            return_value=mock_monitor,
        ):
            VideoSink._maybe_do_clear()

        mock_window.clear_display.assert_called_once()
        mock_monitor.clear_display.assert_called_once()
        assert VideoSink._pending_clear is False
        del sink

    def test_maybe_do_clear_noop_when_not_pending(self):
        """If a play() cancelled the pending clear, _maybe_do_clear
        (firing later from the original timer) must not clear."""
        pipeline = Gst.Pipeline()
        sink = VideoSink(pipeline)

        VideoSink._pending_clear = False

        mock_window = MagicMock()
        with patch(
            "lisp.plugins.gst_backend.gst_backend"
            ".GstBackend.video_window",
            return_value=mock_window,
        ), patch(
            "lisp.plugins.gst_backend.gst_backend"
            ".GstBackend.monitor_window",
            return_value=None,
        ):
            VideoSink._maybe_do_clear()

        mock_window.clear_display.assert_not_called()
        del sink


class TestVideoSinkDeferredClear:
    """Verify the deferred-clear cancellation that produces seamless
    transitions in playlist GroupCues.

    Reasoning: QLab/SCS default behaviour is "clear the projection
    when a video cue stops" (a black gap appears between cues).
    Playlist mode in SCS is seamless because it's one cue, not many.
    Our playlist GroupCue chains independent cues, so we approximate
    seamlessness by deferring the clear briefly and cancelling it on
    the next cue's play().  See
    docs/bugs/2026-05-23-video-sink-stale-frame-bleedthrough.md."""

    def teardown_method(self):
        VideoSink._previous_sink = None
        VideoSink._pending_clear = False

    def test_play_cancels_pending_clear(self):
        """stop() schedules a clear; an immediate play() (as happens
        in playlist auto-advance) must clear the pending flag so the
        timer fires harmlessly."""
        pipeline = Gst.Pipeline()
        sink_a = VideoSink(pipeline)
        pipeline_b = Gst.Pipeline()
        sink_b = VideoSink(pipeline_b)

        mock_window = MagicMock()
        with patch.object(
            VideoSink, "_video_window",
            return_value=mock_window,
        ), patch.object(
            VideoSink, "_monitor_window",
            return_value=None,
        ):
            sink_a.stop()
            assert VideoSink._pending_clear is True
            sink_b.play()
            assert VideoSink._pending_clear is False

    def test_playlist_handoff_keeps_surface_alive(self):
        """End-to-end: stop A, immediately play B, then fire the
        deferred-clear timer.  The clear must NOT execute because B
        cancelled it.  This is the property that makes a playlist of
        videos in a GroupCue flow seamlessly."""
        pipeline_a = Gst.Pipeline()
        sink_a = VideoSink(pipeline_a)
        pipeline_b = Gst.Pipeline()
        sink_b = VideoSink(pipeline_b)

        mock_window = MagicMock()
        with patch.object(
            VideoSink, "_video_window",
            return_value=mock_window,
        ), patch.object(
            VideoSink, "_monitor_window",
            return_value=None,
        ), patch(
            "lisp.plugins.gst_backend.gst_backend"
            ".GstBackend.video_window",
            return_value=mock_window,
        ), patch(
            "lisp.plugins.gst_backend.gst_backend"
            ".GstBackend.monitor_window",
            return_value=None,
        ):
            sink_a.stop()
            sink_b.play()
            # Simulate the deferred timer firing now.
            VideoSink._maybe_do_clear()

        mock_window.clear_display.assert_not_called()

    def test_standalone_stop_eventually_clears(self):
        """The counter-test: when no follow-up play() happens, the
        timer firing actually performs the clear.  This is the
        QLab/SCS "clear on stop" default behaviour for cues that
        aren't part of a chain."""
        pipeline = Gst.Pipeline()
        sink = VideoSink(pipeline)

        mock_window = MagicMock()
        with patch.object(
            VideoSink, "_video_window",
            return_value=mock_window,
        ), patch.object(
            VideoSink, "_monitor_window",
            return_value=None,
        ), patch(
            "lisp.plugins.gst_backend.gst_backend"
            ".GstBackend.video_window",
            return_value=mock_window,
        ), patch(
            "lisp.plugins.gst_backend.gst_backend"
            ".GstBackend.monitor_window",
            return_value=None,
        ):
            sink.stop()
            # Timer fires — no intervening play().
            VideoSink._maybe_do_clear()

        mock_window.clear_display.assert_called_once()


class TestVideoSinkDeferredShow:
    """Verify the stale-frame bleed-through fix: play() must not show
    the projection surface synchronously when the pipeline is in READY
    (cold start), or the previous cue's last frame remains composited
    until the new sink prerolls its first buffer.

    See docs/bugs/2026-05-23-video-sink-stale-frame-bleedthrough.md"""

    def teardown_method(self):
        VideoSink._previous_sink = None

    def test_play_defers_show_display_in_ready_state(self):
        """Cold-start path: pipeline is in READY when play() runs.
        show_display must wait for the first-buffer probe."""
        pipeline = Gst.Pipeline()
        sink = VideoSink(pipeline)
        # Pipeline starts in NULL by default; that's fine — we just
        # need it to not be in PAUSED so the deferred path is taken.

        mock_window = MagicMock()
        mock_monitor = MagicMock()
        mock_monitor.isVisible.return_value = True
        with patch.object(
            VideoSink, "_video_window",
            return_value=mock_window,
        ), patch.object(
            VideoSink, "_monitor_window",
            return_value=mock_monitor,
        ):
            sink.play()

        mock_window.show_display.assert_not_called()
        mock_monitor.show_display.assert_not_called()

    def test_play_installs_first_buffer_probe_in_ready_state(self):
        """Cold-start path must register a buffer probe on
        proj_queue.src so the deferred show fires on first buffer."""
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

        assert sink._first_buffer_probe is not None

    def test_play_calls_show_display_when_pipeline_already_paused(self):
        """Pre-armed / resume-from-pause path: the sink already holds
        a prerolled buffer when play() runs, so showing immediately is
        safe and avoids adding latency.

        Real preroll requires a working video sink which CI can't
        guarantee, so we stub pipeline.get_state to report PAUSED
        directly — what matters here is the decision branch."""
        pipeline = Gst.Pipeline()
        sink = VideoSink(pipeline)

        mock_window = MagicMock()
        with patch.object(
            VideoSink, "_video_window",
            return_value=mock_window,
        ), patch.object(
            VideoSink, "_monitor_window",
            return_value=None,
        ), patch.object(
            sink.pipeline, "get_state",
            return_value=(Gst.StateChangeReturn.SUCCESS,
                          Gst.State.PAUSED, Gst.State.PAUSED),
        ):
            sink.play()

        mock_window.show_display.assert_called_once()
        # Fast path must not also install a probe.
        assert sink._first_buffer_probe is None

    def test_stop_removes_pending_first_buffer_probe(self):
        """A cue stopped before its first buffer arrives must clean
        up the installed probe, or the probe leaks past pipeline
        teardown."""
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
            assert sink._first_buffer_probe is not None
            sink.stop()
            assert sink._first_buffer_probe is None

    def test_dispose_removes_pending_first_buffer_probe(self):
        """dispose() may run without a preceding stop() (e.g. cue
        removed mid-play); it must clean up the probe too."""
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
            assert sink._first_buffer_probe is not None
            sink.dispose()
            assert sink._first_buffer_probe is None

    def test_first_buffer_callback_clears_probe_handle(self):
        """When the probe fires once it is consumed; subsequent
        buffers must not retrigger show_display."""
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
            assert sink._first_buffer_probe is not None
            # Simulate the probe firing without needing the streaming
            # thread to push a real buffer.
            sink._consume_first_buffer_probe()
            assert sink._first_buffer_probe is None


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
