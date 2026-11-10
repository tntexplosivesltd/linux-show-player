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

    def test_scale_and_convert_run_before_freeze(self):
        """videoscale -> capsfilter -> videoconvert -> imagefreeze:
        a huge still is scaled and converted once, not per frame."""
        pipeline = Gst.Pipeline()
        element = ImageInput(pipeline)

        def peer_element(elem):
            peer = elem.get_static_pad("src").get_peer()
            return peer.get_parent_element() if peer else None

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

    def test_video_pad_links_to_videoscale(self):
        element = self._make_element()
        pad = self._make_pad("video/x-raw")

        scale_sink = element.video_scale.get_static_pad("sink")
        pad.link.return_value = Gst.PadLinkReturn.OK

        element._ImageInput__on_pad_added(element.decoder, pad)

        pad.link.assert_called_once_with(scale_sink)
        assert element._linked is True

    def test_large_image_scaled_to_canvas(self, monkeypatch):
        monkeypatch.setattr(image_input, "_canvas_size", lambda: (1920, 1080))
        element = self._make_element()
        pad = self._make_pad("video/x-raw", "8000x5333")
        pad.link.return_value = Gst.PadLinkReturn.OK

        element._ImageInput__on_pad_added(element.decoder, pad)

        s = element.scale_filter.get_property("caps").get_structure(0)
        assert s.get_int("width") == (True, 1620)
        assert s.get_int("height") == (True, 1080)
        assert s.get_fraction("pixel-aspect-ratio") == (True, 1, 1)

    def test_small_image_not_scaled(self, monkeypatch):
        monkeypatch.setattr(image_input, "_canvas_size", lambda: (1920, 1080))
        element = self._make_element()
        pad = self._make_pad("video/x-raw", "736x552")
        pad.link.return_value = Gst.PadLinkReturn.OK

        element._ImageInput__on_pad_added(element.decoder, pad)

        assert element.scale_filter.get_property("caps").is_any()

    def test_prescale_failure_still_links(self, monkeypatch):
        """Slow beats blank: an error sizing the image must not stop
        it from being shown."""
        def broken():
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
        monkeypatch.setattr(image_input, "_canvas_size", lambda: canvas[0])
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
        f"videotestsrc num-buffers=1 ! video/x-raw,width={width},"
        f"height={height} ! pngenc ! filesink location={path}"
    )
    pipeline.set_state(Gst.State.PLAYING)
    msg = pipeline.get_bus().timed_pop_filtered(
        5 * Gst.SECOND, Gst.MessageType.EOS | Gst.MessageType.ERROR)
    pipeline.set_state(Gst.State.NULL)
    assert msg is not None and msg.type == Gst.MessageType.EOS


@pytest.mark.parametrize(
    "size, canvas, expected",
    [
        # Larger than the canvas: fitted inside it, once.
        ((400, 300), (160, 90), (120, 90)),
        # Smaller: delivered as decoded.
        ((64, 48), (160, 90), (64, 48)),
    ],
)
def test_real_pipeline_delivers_prescaled_frames(
    tmp_path, monkeypatch, size, canvas, expected
):
    """A real still through the real ImageInput chain: the frames
    imagefreeze repeats are already canvas-sized, square pixels."""
    monkeypatch.setattr(image_input, "_canvas_size", lambda: canvas)
    path = tmp_path / "still.png"
    _encode_png(path, *size)

    pipeline = Gst.Pipeline()
    element = ImageInput(pipeline)
    element.uri = path.as_uri()
    appsink = Gst.ElementFactory.make("appsink", None)
    appsink.set_property("sync", False)
    pipeline.add(appsink)
    assert element.video_src().link(appsink)
    try:
        pipeline.set_state(Gst.State.PAUSED)
        sample = appsink.emit("try-pull-preroll", 5 * Gst.SECOND)
        assert sample is not None
        s = sample.get_caps().get_structure(0)
        assert (s.get_int("width")[1], s.get_int("height")[1]) == expected
        ok, par_n, par_d = s.get_fraction("pixel-aspect-ratio")
        assert not ok or (par_n, par_d) == (1, 1)
    finally:
        pipeline.set_state(Gst.State.NULL)
        element.dispose()


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
