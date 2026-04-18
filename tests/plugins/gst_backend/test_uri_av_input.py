"""Tests for UriAvInput element."""

from unittest.mock import MagicMock

from lisp.backend.media_element import ElementType, MediaType
from lisp.plugins.gst_backend.gi_repository import Gst
from lisp.plugins.gst_backend.elements.uri_av_input import UriAvInput


class TestUriAvInputProperties:
    def test_media_type(self):
        assert UriAvInput.MediaType == MediaType.AudioAndVideo

    def test_element_type(self):
        assert UriAvInput.ElementType == ElementType.Input

    def test_name(self):
        assert UriAvInput.Name == "URI A/V Input"


class TestUriAvInputConstruction:
    def test_creates_pipeline_elements(self):
        pipeline = Gst.Pipeline()
        element = UriAvInput(pipeline)
        assert element.decoder is not None
        assert element.audio_queue is not None
        assert element.audio_convert is not None
        assert element.video_queue is not None
        assert element.video_convert is not None
        assert element.video_scale is not None

    def test_src_returns_audioconvert(self):
        pipeline = Gst.Pipeline()
        element = UriAvInput(pipeline)
        assert element.src() is element.audio_convert

    def test_video_src_returns_videoscale(self):
        pipeline = Gst.Pipeline()
        element = UriAvInput(pipeline)
        assert element.video_src() is element.video_scale

    def test_dispose_disconnects_handlers(self):
        pipeline = Gst.Pipeline()
        element = UriAvInput(pipeline)
        # Should not raise
        element.dispose()

    def test_initial_link_state(self):
        pipeline = Gst.Pipeline()
        element = UriAvInput(pipeline)
        assert element._audio_linked is False
        assert element._video_linked is False


class TestOnPadAdded:
    """Test the __on_pad_added callback logic."""

    def _make_element(self):
        pipeline = Gst.Pipeline()
        return UriAvInput(pipeline)

    def _make_pad(self, media_type):
        """Create a mock pad with caps of the given media type."""
        mock_pad = MagicMock()
        mock_caps = MagicMock()
        mock_struct = MagicMock()
        mock_struct.get_name.return_value = media_type
        mock_caps.get_structure.return_value = mock_struct
        mock_pad.get_current_caps.return_value = mock_caps
        return mock_pad

    def test_audio_pad_links_to_audio_queue(self):
        element = self._make_element()
        pad = self._make_pad("audio/x-raw")

        audio_sink = element.audio_queue.get_static_pad("sink")
        pad.link.return_value = Gst.PadLinkReturn.OK

        # Call the private method directly (name-mangled)
        element._UriAvInput__on_pad_added(element.decoder, pad)

        pad.link.assert_called_once_with(audio_sink)
        assert element._audio_linked is True

    def test_video_pad_links_to_video_queue(self):
        element = self._make_element()
        pad = self._make_pad("video/x-raw")

        video_sink = element.video_queue.get_static_pad("sink")
        pad.link.return_value = Gst.PadLinkReturn.OK

        element._UriAvInput__on_pad_added(element.decoder, pad)

        pad.link.assert_called_once_with(video_sink)
        assert element._video_linked is True

    def test_null_caps_ignored(self):
        element = self._make_element()
        pad = MagicMock()
        pad.get_current_caps.return_value = None

        element._UriAvInput__on_pad_added(element.decoder, pad)

        pad.link.assert_not_called()
        assert element._audio_linked is False
        assert element._video_linked is False

    def test_unknown_media_type_ignored(self):
        element = self._make_element()
        pad = self._make_pad("application/x-id3")

        element._UriAvInput__on_pad_added(element.decoder, pad)

        pad.link.assert_not_called()

    def test_duplicate_audio_pad_ignored(self):
        element = self._make_element()

        # First link succeeds
        first_pad = self._make_pad("audio/x-raw")
        first_pad.link.return_value = Gst.PadLinkReturn.OK
        element._UriAvInput__on_pad_added(
            element.decoder, first_pad
        )
        assert element._audio_linked is True

        # Second audio pad — _audio_linked flag prevents linking
        second_pad = self._make_pad("audio/x-raw")
        element._UriAvInput__on_pad_added(
            element.decoder, second_pad
        )
        second_pad.link.assert_not_called()

    def test_link_failure_logged(self):
        element = self._make_element()
        pad = self._make_pad("audio/x-raw")
        pad.link.return_value = Gst.PadLinkReturn.WRONG_HIERARCHY

        element._UriAvInput__on_pad_added(element.decoder, pad)

        assert element._audio_linked is False


class TestNoMorePads:
    """Test the __on_no_more_pads callback."""

    def _pipeline_has(self, pipeline, element):
        """Check if a GStreamer element is in the pipeline."""
        name = element.get_name()
        return pipeline.get_by_name(name) is not None

    def test_removes_video_branch_when_no_video(self):
        pipeline = Gst.Pipeline()
        element = UriAvInput(pipeline)
        element._audio_linked = True
        element._video_linked = False

        element._UriAvInput__on_no_more_pads(element.decoder)

        assert self._pipeline_has(pipeline, element.audio_queue)
        assert not self._pipeline_has(
            pipeline, element.video_queue
        )

    def test_removes_audio_branch_when_no_audio(self):
        pipeline = Gst.Pipeline()
        element = UriAvInput(pipeline)
        element._audio_linked = False
        element._video_linked = True

        element._UriAvInput__on_no_more_pads(element.decoder)

        assert not self._pipeline_has(
            pipeline, element.audio_queue
        )
        assert self._pipeline_has(pipeline, element.video_queue)

    def test_keeps_both_when_both_linked(self):
        pipeline = Gst.Pipeline()
        element = UriAvInput(pipeline)
        element._audio_linked = True
        element._video_linked = True

        element._UriAvInput__on_no_more_pads(element.decoder)

        assert self._pipeline_has(pipeline, element.audio_queue)
        assert self._pipeline_has(pipeline, element.video_queue)
