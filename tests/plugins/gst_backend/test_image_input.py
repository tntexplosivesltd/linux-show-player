"""Tests for ImageInput element."""

import time
from unittest.mock import MagicMock

from lisp.backend.media_element import ElementType, MediaType
from lisp.plugins.gst_backend.gi_repository import Gst
from lisp.plugins.gst_backend.elements.image_input import ImageInput


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

    def test_video_src_returns_videoscale(self):
        pipeline = Gst.Pipeline()
        element = ImageInput(pipeline)
        assert element.video_src() is element.video_scale

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

    def test_freeze_links_to_videoconvert(self):
        """imagefreeze -> videoconvert should be linked."""
        pipeline = Gst.Pipeline()
        element = ImageInput(pipeline)
        src_pad = element.freeze.get_static_pad("src")
        assert src_pad.get_peer() is not None

    def test_videoconvert_links_to_videoscale(self):
        """videoconvert -> videoscale should be linked."""
        pipeline = Gst.Pipeline()
        element = ImageInput(pipeline)
        src_pad = element.video_convert.get_static_pad("src")
        assert src_pad.get_peer() is not None


class TestImageInputPadAdded:
    """Test the __on_pad_added callback logic."""

    def _make_element(self):
        pipeline = Gst.Pipeline()
        return ImageInput(pipeline)

    def _make_pad(self, media_type):
        """Create a mock pad with caps of the given media type."""
        mock_pad = MagicMock()
        mock_caps = MagicMock()
        mock_struct = MagicMock()
        mock_struct.get_name.return_value = media_type
        mock_caps.get_structure.return_value = mock_struct
        mock_pad.get_current_caps.return_value = mock_caps
        return mock_pad

    def test_video_pad_links_to_freeze(self):
        element = self._make_element()
        pad = self._make_pad("video/x-raw")

        freeze_sink = element.freeze.get_static_pad("sink")
        pad.link.return_value = Gst.PadLinkReturn.OK

        element._ImageInput__on_pad_added(element.decoder, pad)

        pad.link.assert_called_once_with(freeze_sink)
        assert element._linked is True

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
