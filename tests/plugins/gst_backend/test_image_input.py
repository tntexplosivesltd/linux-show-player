"""Tests for ImageInput element."""

import time

import pytest
from unittest.mock import MagicMock

from lisp.backend.media_element import ElementType, MediaType
from lisp.plugins.gst_backend.gi_repository import Gst
from lisp.plugins.gst_backend.elements import image_input
from lisp.plugins.gst_backend.elements.image_input import (
    ImageInput,
    prescale_size,
)


class TestImageInputProperties:
    def test_media_type(self):
        assert ImageInput.MediaType == MediaType.Video

    def test_element_type(self):
        assert ImageInput.ElementType == ElementType.Input

    def test_name(self):
        assert ImageInput.Name == "Image Input"


class TestImageInputConstruction:
    def test_creates_pipeline_elements(self):
        pipeline = Gst.Pipeline()
        element = ImageInput(pipeline)
        assert element.decoder is not None
        assert element.freeze is not None
        assert element.video_convert is not None
        assert element.video_scale is not None

    def test_src_returns_none(self):
        """Images have no audio -- src() must be None."""
        pipeline = Gst.Pipeline()
        element = ImageInput(pipeline)
        assert element.src() is None

    def test_video_src_returns_freeze(self):
        """imagefreeze is last: everything before it runs once per
        image, everything after it on every repeated frame."""
        pipeline = Gst.Pipeline()
        element = ImageInput(pipeline)
        assert element.video_src() is element.freeze

    def test_prescale_uses_lanczos(self):
        """By nick: GstVideoScaleMethod 4 is bilinear2, not lanczos."""
        element = ImageInput(Gst.Pipeline())
        method = element.video_scale.get_property("method")
        assert method.value_nick == "lanczos"

    def test_default_duration_is_5000(self):
        pipeline = Gst.Pipeline()
        element = ImageInput(pipeline)
        assert element.duration == 5000

    def test_initial_linked_false(self):
        pipeline = Gst.Pipeline()
        element = ImageInput(pipeline)
        assert element._linked is False

    def test_dispose_disconnects_handler(self):
        pipeline = Gst.Pipeline()
        element = ImageInput(pipeline)
        # Should not raise
        element.dispose()

    def test_prescale_never_adds_borders(self):
        """Rounding makes the target aspect a hair off the source's;
        the default add-borders would pad that with a black edge."""
        element = ImageInput(Gst.Pipeline())
        assert element.video_scale.get_property("add-borders") is False

    def test_scale_threads_bounded(self):
        element = ImageInput(Gst.Pipeline())
        for elem in (element.decode_convert, element.video_scale,
                     element.video_convert):
            if elem.find_property("n-threads") is not None:
                threads = elem.get_property("n-threads")
                assert threads == image_input.SCALE_THREADS
                assert 1 <= threads <= 4

    def test_threads_skipped_without_property(self):
        """GStreamer < 1.20 has no n-threads: building an image cue
        must not fail on it."""
        elem = MagicMock()
        elem.find_property.return_value = None
        image_input._set_threads(elem, 4)
        elem.set_property.assert_not_called()

    def test_scale_and_convert_run_before_freeze(self):
        """videoconvert -> videoscale -> capsfilter -> videoconvert ->
        imagefreeze: a huge still is scaled and converted once, not
        per frame."""
        pipeline = Gst.Pipeline()
        element = ImageInput(pipeline)

        def peer_element(elem):
            peer = elem.get_static_pad("src").get_peer()
            return peer.get_parent_element() if peer else None

        assert peer_element(element.decode_convert) is element.video_scale
        assert peer_element(element.video_scale) is element.scale_filter
        assert peer_element(element.scale_filter) is element.video_convert
        assert peer_element(element.video_convert) is element.freeze


class TestImageInputPadAdded:
    """Test the __on_pad_added callback logic."""

    def _make_element(self):
        pipeline = Gst.Pipeline()
        return ImageInput(pipeline)

    def _make_pad(self, media_type, size="6000x3375"):
        """Create a mock pad with real caps of the given media type."""
        width, height = size.split("x")
        mock_pad = MagicMock()
        mock_pad.get_current_caps.return_value = Gst.Caps.from_string(
            f"{media_type},width={width},height={height}"
        )
        return mock_pad

    def test_video_pad_links_to_decode_convert(self):
        """Through a videoconvert, so the scaler always negotiates."""
        element = self._make_element()
        pad = self._make_pad("video/x-raw")

        scale_sink = element.decode_convert.get_static_pad("sink")
        pad.link.return_value = Gst.PadLinkReturn.OK

        element._ImageInput__on_pad_added(element.decoder, pad)

        pad.link.assert_called_once_with(scale_sink)
        assert element._linked is True

    def test_large_image_scaled_to_canvas(self, monkeypatch):
        monkeypatch.setattr(image_input, "_canvas_size", lambda _comp: (1920, 1080))
        element = self._make_element()
        pad = self._make_pad("video/x-raw", "8000x5333")
        pad.link.return_value = Gst.PadLinkReturn.OK

        element._ImageInput__on_pad_added(element.decoder, pad)

        s = element.scale_filter.get_property("caps").get_structure(0)
        assert s.get_int("width") == (True, 1620)
        assert s.get_int("height") == (True, 1080)
        assert s.get_fraction("pixel-aspect-ratio") == (True, 1, 1)

    def test_small_image_not_scaled(self, monkeypatch):
        monkeypatch.setattr(image_input, "_canvas_size", lambda _comp: (1920, 1080))
        element = self._make_element()
        pad = self._make_pad("video/x-raw", "736x552")
        pad.link.return_value = Gst.PadLinkReturn.OK

        element._ImageInput__on_pad_added(element.decoder, pad)

        assert element.scale_filter.get_property("caps").is_any()

    def test_missing_size_not_scaled(self, monkeypatch):
        monkeypatch.setattr(image_input, "_canvas_size", lambda _comp: (1920, 1080))
        element = self._make_element()
        pad = MagicMock()
        pad.get_current_caps.return_value = Gst.Caps.from_string(
            "video/x-raw,width=6000"
        )
        pad.link.return_value = Gst.PadLinkReturn.OK

        element._ImageInput__on_pad_added(element.decoder, pad)

        assert element._linked is True
        assert element.scale_filter.get_property("caps").is_any()

    def test_explicit_par_is_honoured(self, monkeypatch):
        """Missing PAR means square; a given one is used: 1000x1000 at
        2/1 displays 2000x1000, too wide for the canvas."""
        monkeypatch.setattr(image_input, "_canvas_size", lambda _comp: (1920, 1080))
        element = self._make_element()
        pad = MagicMock()
        pad.get_current_caps.return_value = Gst.Caps.from_string(
            "video/x-raw,width=1000,height=1000,pixel-aspect-ratio=2/1"
        )
        pad.link.return_value = Gst.PadLinkReturn.OK

        element._ImageInput__on_pad_added(element.decoder, pad)

        s = element.scale_filter.get_property("caps").get_structure(0)
        assert (s.get_int("width")[1], s.get_int("height")[1]) == (1920, 960)

    def test_no_compositor_uses_fallback_canvas(self, monkeypatch):
        """No compositor yet: prescale to UHD, not 1080p, so a 4K
        output is never fed a 1080p frame to upscale."""
        from lisp.plugins.gst_backend.gst_backend import GstBackend

        monkeypatch.setattr(GstBackend, "_video_compositor", None)
        assert image_input._canvas_size(None) == image_input.FALLBACK_CANVAS
        element = self._make_element()
        pad = self._make_pad("video/x-raw", "8000x4500")
        pad.link.return_value = Gst.PadLinkReturn.OK

        element._ImageInput__on_pad_added(element.decoder, pad)

        s = element.scale_filter.get_property("caps").get_structure(0)
        assert (s.get_int("width")[1], s.get_int("height")[1]) == (3840, 2160)

    def test_compositor_canvas_is_used(self, monkeypatch):
        from lisp.plugins.gst_backend.gst_backend import GstBackend

        compositor = MagicMock()
        compositor.canvas_size.return_value = (1280, 720)
        monkeypatch.setattr(GstBackend, "_video_compositor", compositor)
        assert image_input._canvas_size(compositor) == (1280, 720)

    def test_streaming_thread_does_not_look_up_the_compositor(
            self, monkeypatch):
        """pad-added runs on uridecodebin's streaming thread: it must
        only read the compositor cached at construction, never do the
        lazy GstBackend import (docs/threading.md). Cached at
        construction, not in play(): a pre-arm preroll links the
        decoded pad before play() is ever called."""
        from lisp.plugins.gst_backend.gst_backend import GstBackend

        compositor = MagicMock()
        compositor.canvas_size.return_value = (1280, 720)
        monkeypatch.setattr(GstBackend, "_video_compositor", compositor)
        element = self._make_element()

        def no_lookup():
            raise AssertionError("compositor looked up on pad-added")

        monkeypatch.setattr(image_input, "_compositor", no_lookup)
        pad = self._make_pad("video/x-raw", "6000x3375")
        pad.link.return_value = Gst.PadLinkReturn.OK
        element._ImageInput__on_pad_added(element.decoder, pad)

        s = element.scale_filter.get_property("caps").get_structure(0)
        assert (s.get_int("width")[1], s.get_int("height")[1]) == (1280, 720)

    def test_prescale_failure_still_links(self, monkeypatch):
        """Slow beats blank: an error sizing the image must not stop
        it from being shown."""
        def broken(_comp):
            raise RuntimeError("no canvas")

        monkeypatch.setattr(image_input, "_canvas_size", broken)
        element = self._make_element()
        pad = self._make_pad("video/x-raw", "6000x3375")
        pad.link.return_value = Gst.PadLinkReturn.OK

        element._ImageInput__on_pad_added(element.decoder, pad)

        assert element._linked is True
        assert element.scale_filter.get_property("caps").is_any()

    def test_replay_rescales_to_current_canvas(self, monkeypatch):
        """Each play re-decodes (stop() resets _linked): a canvas that
        changed in between (another screen) is picked up."""
        canvas = [(1920, 1080)]
        monkeypatch.setattr(image_input, "_canvas_size", lambda _comp: canvas[0])
        element = self._make_element()
        pad = self._make_pad("video/x-raw", "6000x3375")
        pad.link.return_value = Gst.PadLinkReturn.OK
        element._ImageInput__on_pad_added(element.decoder, pad)
        element.stop()
        canvas[0] = (3840, 2160)
        element._ImageInput__on_pad_added(element.decoder, pad)

        s = element.scale_filter.get_property("caps").get_structure(0)
        assert s.get_int("width") == (True, 3840)

    def test_null_caps_ignored(self):
        element = self._make_element()
        pad = MagicMock()
        pad.get_current_caps.return_value = None

        element._ImageInput__on_pad_added(element.decoder, pad)

        pad.link.assert_not_called()
        assert element._linked is False

    def test_audio_pad_ignored(self):
        """Images should never produce audio pads, but if they
        do (e.g. metadata), they should be ignored."""
        element = self._make_element()
        pad = self._make_pad("audio/x-raw")

        element._ImageInput__on_pad_added(element.decoder, pad)

        pad.link.assert_not_called()

    def test_duplicate_video_pad_ignored(self):
        element = self._make_element()

        first_pad = self._make_pad("video/x-raw")
        first_pad.link.return_value = Gst.PadLinkReturn.OK
        element._ImageInput__on_pad_added(
            element.decoder, first_pad
        )
        assert element._linked is True

        second_pad = self._make_pad("video/x-raw")
        element._ImageInput__on_pad_added(
            element.decoder, second_pad
        )
        second_pad.link.assert_not_called()

    def test_link_failure_logged(self):
        element = self._make_element()
        pad = self._make_pad("video/x-raw")
        pad.link.return_value = Gst.PadLinkReturn.WRONG_HIERARCHY

        element._ImageInput__on_pad_added(element.decoder, pad)

        assert element._linked is False


def _encode_png(path, width, height):
    pipeline = Gst.parse_launch(
        f"videotestsrc num-buffers=1 pattern=white ! "
        f"video/x-raw,width={width},"
        f"height={height} ! pngenc ! filesink location={path}"
    )
    pipeline.set_state(Gst.State.PLAYING)
    msg = pipeline.get_bus().timed_pop_filtered(
        5 * Gst.SECOND, Gst.MessageType.EOS | Gst.MessageType.ERROR)
    pipeline.set_state(Gst.State.NULL)
    assert msg is not None and msg.type == Gst.MessageType.EOS


_REAL_PIPELINE_PLUGINS = (
    "videotestsrc", "pngenc", "pngdec", "uridecodebin", "videoscale",
    "videoconvert", "imagefreeze", "appsink",
)


@pytest.fixture
def needs_real_pipeline():
    """Skip, not fail, where a plugin is missing. Checked at run time:
    GStreamer is not initialised yet when this module is imported."""
    if not Gst.is_initialized():
        Gst.init([])
    missing = [f for f in _REAL_PIPELINE_PLUGINS
               if Gst.ElementFactory.find(f) is None]
    if missing:
        pytest.skip(f"missing GStreamer plugins: {', '.join(missing)}")


def _pull_frame(tmp_path, monkeypatch, size, canvas, fmt):
    """Encode a white `size` PNG and pull the first frame the real
    ImageInput chain hands on, as `fmt`. Returns the sample."""
    monkeypatch.setattr(image_input, "_canvas_size", lambda _comp: canvas)
    path = tmp_path / "still.png"
    _encode_png(path, *size)

    pipeline = Gst.Pipeline()
    element = ImageInput(pipeline)
    element.uri = path.as_uri()
    appsink = Gst.ElementFactory.make("appsink", None)
    appsink.set_property("sync", False)
    appsink.set_property(
        "caps", Gst.Caps.from_string(f"video/x-raw,format={fmt}")
    )
    pipeline.add(appsink)
    assert element.video_src().link(appsink)
    try:
        pipeline.set_state(Gst.State.PAUSED)
        sample = appsink.emit("try-pull-preroll", 5 * Gst.SECOND)
        assert sample is not None
        return sample
    finally:
        pipeline.set_state(Gst.State.NULL)
        element.dispose()


@pytest.mark.usefixtures("needs_real_pipeline")
@pytest.mark.parametrize(
    "size, canvas, expected",
    [
        # Larger than the canvas: fitted inside it, once.
        ((400, 300), (160, 90), (120, 90)),
        # Smaller: delivered as decoded.
        ((64, 48), (160, 90), (64, 48)),
        # Odd source, awkward aspect: still even (I420 needs it).
        ((401, 301), (160, 90), (120, 90)),
    ],
)
def test_real_pipeline_delivers_prescaled_frames(
    tmp_path, monkeypatch, size, canvas, expected
):
    """A real still through the real ImageInput chain: the frames
    imagefreeze repeats are already canvas-sized, square pixels."""
    sample = _pull_frame(tmp_path, monkeypatch, size, canvas, "I420")
    s = sample.get_caps().get_structure(0)
    assert (s.get_int("width")[1], s.get_int("height")[1]) == expected
    ok, par_n, par_d = s.get_fraction("pixel-aspect-ratio")
    assert not ok or (par_n, par_d) == (1, 1)


@pytest.mark.usefixtures("needs_real_pipeline")
def test_real_pipeline_no_black_edge(tmp_path, monkeypatch):
    """403x300 -> 120x90 (120.9 floored to even) is a hair narrower
    than the source aspect: the scaler must stretch it, not pad a
    black row (add-borders, the default, does)."""
    sample = _pull_frame(
        tmp_path, monkeypatch, (403, 300), (160, 90), "GRAY8"
    )
    s = sample.get_caps().get_structure(0)
    width, height = s.get_int("width")[1], s.get_int("height")[1]
    assert (width, height) == (120, 90)
    buf = sample.get_buffer()
    ok, info = buf.map(Gst.MapFlags.READ)
    assert ok
    try:
        data = bytes(info.data)
    finally:
        buf.unmap(info)
    stride = len(data) // height
    rows = [data[r * stride:r * stride + width] for r in range(height)]
    edges = [rows[0], rows[-1], bytes(r[0] for r in rows),
             bytes(r[-1] for r in rows)]
    for edge in edges:
        assert min(edge) > 128, "black edge on a white still"


class TestPrescaleSize:
    """The size a still is scaled to, once, before imagefreeze."""

    def test_larger_than_canvas_fits_inside(self):
        assert prescale_size(6000, 3375, 1, 1, 1920, 1080) == (1920, 1080)

    def test_other_aspect_fits_inside(self):
        assert prescale_size(8000, 5333, 1, 1, 1920, 1080) == (1620, 1080)

    def test_portrait_fits_inside(self):
        assert prescale_size(1000, 3000, 1, 1, 1920, 1080) == (360, 1080)

    def test_canvas_sized_not_scaled(self):
        assert prescale_size(1920, 1080, 1, 1, 1920, 1080) is None

    def test_smaller_never_upscaled(self):
        """The GPU mixer upscales; a CPU upscale would only make every
        frame bigger."""
        assert prescale_size(736, 552, 1, 1, 1920, 1080) is None

    def test_one_dimension_over_is_scaled(self):
        assert prescale_size(2000, 500, 1, 1, 1920, 1080) == (1920, 480)

    def test_rounded_down_to_even(self):
        """Odd sizes break chroma-subsampled formats (I420)."""
        w, h = prescale_size(5000, 3001, 1, 1, 1920, 1080)
        assert (w % 2, h % 2) == (0, 0)
        assert w <= 1920 and h <= 1080

    def test_anamorphic_scaled_to_square_pixels(self):
        # 1000x1000 at PAR 2/1 displays 2000x1000: too wide.
        assert prescale_size(1000, 1000, 2, 1, 1920, 1080) == (1920, 960)

    def test_anamorphic_that_fits_left_alone(self):
        # 720x576 PAR 16/15 displays 768x576: the mixer handles PAR.
        assert prescale_size(720, 576, 16, 15, 1920, 1080) is None

    def test_degenerate_input_not_scaled(self):
        assert prescale_size(0, 0, 1, 1, 1920, 1080) is None

    @pytest.mark.parametrize(
        "src, expected",
        [
            # 10000x10 fits as 1920x1.92: clamped to 2, never 0.
            ((10000, 10), (1920, 2)),
            ((10, 10000), (2, 1080)),
        ],
    )
    def test_extreme_aspect_clamped_to_two(self, src, expected):
        assert prescale_size(*src, 1, 1, 1920, 1080) == expected


class TestImageInputTimer:
    """Test the EOS timer for duration enforcement."""

    def test_play_starts_timer(self):
        pipeline = Gst.Pipeline()
        element = ImageInput(pipeline)
        element.play()
        assert element._eos_timer is not None
        element.stop()

    def test_stop_cancels_timer(self):
        pipeline = Gst.Pipeline()
        element = ImageInput(pipeline)
        element.play()
        element.stop()
        assert element._eos_timer is None

    def test_stop_resets_remaining(self):
        pipeline = Gst.Pipeline()
        element = ImageInput(pipeline)
        element.play()
        element.stop()
        assert element._remaining_ms == 0

    def test_pause_cancels_timer_and_records_remaining(self):
        pipeline = Gst.Pipeline()
        element = ImageInput(pipeline)
        element.play()
        time.sleep(0.05)
        element.pause()
        assert element._eos_timer is None
        assert 0 < element._remaining_ms < element.duration

    def test_resume_uses_remaining_time(self):
        pipeline = Gst.Pipeline()
        element = ImageInput(pipeline)
        element.duration = 1000

        element.play()
        time.sleep(0.1)
        element.pause()
        remaining_after_pause = element._remaining_ms

        # Resume: play() should use remaining, not full duration
        element.play()
        assert element._remaining_ms == remaining_after_pause
        element.stop()

    def test_dispose_cancels_timer(self):
        pipeline = Gst.Pipeline()
        element = ImageInput(pipeline)
        element.play()
        element.dispose()
        assert element._eos_timer is None
