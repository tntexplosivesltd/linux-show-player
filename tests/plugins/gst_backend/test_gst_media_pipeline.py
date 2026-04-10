"""Tests for GstMedia pipeline construction with post_link pass."""

import pytest
from unittest.mock import patch

from lisp.plugins.gst_backend import elements as gst_elements
from lisp.plugins.gst_backend.gst_media import GstMedia
from lisp.plugins.gst_backend.gst_element import GstMediaElement


@pytest.fixture(scope="module", autouse=True)
def load_elements():
    """Load GStreamer element classes into the registry."""
    gst_elements.load()


class TestPostLinkPass:
    """Verify that __init_pipeline calls post_link on all elements."""

    def test_post_link_called_on_each_element(self):
        """When a pipeline is built, post_link() should be called
        on every element after the linear chain is assembled."""
        media = GstMedia()

        # Track post_link calls via a wrapper
        post_link_calls = []
        original_post_link = GstMediaElement.post_link

        def tracking_post_link(self, all_elements):
            post_link_calls.append(type(self).__name__)
            return original_post_link(self, all_elements)

        with patch.object(
            GstMediaElement, "post_link", tracking_post_link
        ):
            media.pipe = ("UriInput", "AutoSink")

        assert len(post_link_calls) == 2
        assert "UriInput" in post_link_calls
        assert "AutoSink" in post_link_calls


class TestAudioPipelineUnchanged:
    """Verify existing audio-only pipelines still work."""

    def test_audio_pipeline_creates_elements(self):
        media = GstMedia()
        media.pipe = ("UriInput", "Volume", "AutoSink")
        assert len(media.elements) == 3

    def test_audio_pipeline_source_element(self):
        media = GstMedia()
        media.pipe = ("UriInput", "AutoSink")
        assert media.elements[0] is not None
        assert hasattr(media.elements[0], "duration")


class TestVideoPipelineCreation:
    """Verify video pipelines are constructed correctly."""

    def test_video_pipeline_creates_elements(self):
        media = GstMedia()
        media.pipe = ("UriAvInput", "Volume", "VideoSink")
        assert len(media.elements) == 3

    def test_video_pipeline_source_has_video_src(self):
        media = GstMedia()
        media.pipe = ("UriAvInput", "VideoSink")
        assert media.elements[0].video_src() is not None

    def test_video_pipeline_post_link_wires_video(self):
        media = GstMedia()
        media.pipe = ("UriAvInput", "VideoSink")

        # After pipeline construction, the video source should be
        # linked to the video sink's queue
        video_src = media.elements[0].video_src()
        src_pad = video_src.get_static_pad("src")
        assert src_pad.get_peer() is not None


class TestImagePipelineCreation:
    """Verify image pipelines are constructed correctly."""

    def test_image_pipeline_creates_elements(self):
        media = GstMedia()
        media.pipe = ("ImageInput", "VideoSink")
        assert len(media.elements) == 2

    def test_image_pipeline_video_branch_wired(self):
        """Video branch from ImageInput to VideoSink."""
        media = GstMedia()
        media.pipe = ("ImageInput", "VideoSink")

        video_src = media.elements[0].video_src()
        src_pad = video_src.get_static_pad("src")
        assert src_pad.get_peer() is not None

    def test_image_pipeline_no_audio_src(self):
        """ImageInput has no audio source."""
        media = GstMedia()
        media.pipe = ("ImageInput", "VideoSink")
        assert media.elements[0].src() is None

    def test_image_pipeline_default_duration(self):
        """ImageInput provides a default 5s duration."""
        media = GstMedia()
        media.pipe = ("ImageInput", "VideoSink")
        assert media.duration == 5000


class TestProductionVideoPipeline:
    """Test the full default video pipeline from default.json."""

    def test_full_video_pipeline_creates_all_elements(self):
        """UriAvInput + Volume + DbMeter + VideoSink"""
        media = GstMedia()
        media.pipe = (
            "UriAvInput", "Volume", "DbMeter", "VideoSink"
        )
        assert len(media.elements) == 4

    def test_full_video_pipeline_video_branch_wired(self):
        """Video branch bypasses audio plugins correctly."""
        media = GstMedia()
        media.pipe = (
            "UriAvInput", "Volume", "DbMeter", "VideoSink"
        )

        # Video source should be linked through to VideoSink
        video_src = media.elements[0].video_src()
        src_pad = video_src.get_static_pad("src")
        assert src_pad.get_peer() is not None

    def test_full_video_pipeline_audio_chain_intact(self):
        """Audio chain: UriAvInput -> Volume -> DbMeter -> VideoSink
        audio_sink should all be linked."""
        media = GstMedia()
        media.pipe = (
            "UriAvInput", "Volume", "DbMeter", "VideoSink"
        )

        # UriAvInput.src() (audioconvert) should have a peer
        audio_src = media.elements[0].src()
        src_pad = audio_src.get_static_pad("src")
        assert src_pad.get_peer() is not None

    def test_audio_only_pipeline_still_works(self):
        """Default audio pipeline is unaffected."""
        media = GstMedia()
        media.pipe = (
            "UriInput", "Volume", "Equalizer10",
            "DbMeter", "AutoSink",
        )
        assert len(media.elements) == 5
