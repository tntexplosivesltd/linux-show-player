"""Tests for UriVideoCueFactory, UriImageCueFactory and UriAudioCueFactory.

Factories compose a GstMediaCue with a specific input element, assign
a URI (if given), and tag the cue with the appropriate icon.
"""

import pytest

from lisp.plugins.gst_backend import elements as gst_elements
from lisp.plugins.gst_backend.gst_media_cue import (
    UriAudioCueFactory,
    UriImageCueFactory,
    UriVideoCueFactory,
)


@pytest.fixture(scope="module", autouse=True)
def load_elements():
    gst_elements.load()


BASE_VIDEO_PIPE = ["Volume", "DbMeter", "VideoAlpha", "VideoSink"]
BASE_AUDIO_PIPE = ["Volume", "DbMeter", "AutoSink"]
BASE_IMAGE_PIPE = ["VideoAlpha", "VideoSink"]


class TestUriVideoCueFactory:
    def test_input_is_uri_av_input(self):
        factory = UriVideoCueFactory(BASE_VIDEO_PIPE)
        assert factory.input == "UriAvInput"

    def test_pipeline_prepends_input(self):
        factory = UriVideoCueFactory(BASE_VIDEO_PIPE)
        assert factory.pipeline() == ["UriAvInput"] + BASE_VIDEO_PIPE

    def test_creates_cue_with_uri_av_input(self, mock_app):
        factory = UriVideoCueFactory(BASE_VIDEO_PIPE)
        cue = factory(mock_app)
        assert cue.media.elements.UriAvInput is not None

    def test_creates_cue_with_video_sink(self, mock_app):
        factory = UriVideoCueFactory(BASE_VIDEO_PIPE)
        cue = factory(mock_app)
        assert cue.media.element("VideoSink") is not None

    def test_sets_film_icon(self, mock_app):
        factory = UriVideoCueFactory(BASE_VIDEO_PIPE)
        cue = factory(mock_app)
        assert cue.icon == "film"

    def test_sets_uri_when_given(self, mock_app):
        factory = UriVideoCueFactory(BASE_VIDEO_PIPE)
        uri = "file:///tmp/test.mp4"
        cue = factory(mock_app, uri=uri)
        # Query the underlying GStreamer element to avoid the
        # getter's path_to_relative() Application lookup.
        assert cue.media.elements.UriAvInput.decoder.get_property(
            "uri"
        ) == uri

    def test_uri_none_does_not_crash(self, mock_app):
        factory = UriVideoCueFactory(BASE_VIDEO_PIPE)
        cue = factory(mock_app, uri=None)
        # When no URI is given, the decoder's uri property is unset.
        assert cue.media.elements.UriAvInput.decoder.get_property(
            "uri"
        ) is None


class TestUriImageCueFactory:
    def test_input_is_image_input(self):
        factory = UriImageCueFactory(BASE_IMAGE_PIPE)
        assert factory.input == "ImageInput"

    def test_default_duration_5000(self):
        factory = UriImageCueFactory(BASE_IMAGE_PIPE)
        assert factory._duration == 5000

    def test_custom_duration(self):
        factory = UriImageCueFactory(BASE_IMAGE_PIPE, duration=3000)
        assert factory._duration == 3000

    def test_sets_camera_icon(self, mock_app):
        factory = UriImageCueFactory(BASE_IMAGE_PIPE)
        cue = factory(mock_app)
        assert cue.icon == "camera"

    def test_propagates_duration_to_element(self, mock_app):
        factory = UriImageCueFactory(BASE_IMAGE_PIPE, duration=2500)
        cue = factory(mock_app)
        assert cue.media.elements.ImageInput.duration == 2500

    def test_sets_uri_when_given(self, mock_app):
        factory = UriImageCueFactory(BASE_IMAGE_PIPE)
        uri = "file:///tmp/slide.png"
        cue = factory(mock_app, uri=uri)
        assert cue.media.elements.ImageInput.decoder.get_property(
            "uri"
        ) == uri


class TestUriAudioCueFactory:
    """Regression guard: video/image factories must not disturb
    the existing audio factory's contract."""

    def test_input_is_uri_input(self):
        factory = UriAudioCueFactory(BASE_AUDIO_PIPE)
        assert factory.input == "UriInput"

    def test_creates_cue_with_uri_input(self, mock_app):
        factory = UriAudioCueFactory(BASE_AUDIO_PIPE)
        cue = factory(mock_app)
        assert cue.media.elements.UriInput is not None

    def test_sets_uri_when_given(self, mock_app):
        factory = UriAudioCueFactory(BASE_AUDIO_PIPE)
        uri = "file:///tmp/song.wav"
        cue = factory(mock_app, uri=uri)
        assert cue.media.elements.UriInput.decoder.get_property(
            "uri"
        ) == uri
