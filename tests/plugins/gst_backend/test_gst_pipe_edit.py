"""Tests for GstPipeEdit MediaType filtering."""

import pytest
from unittest.mock import patch

from PyQt5.QtGui import QIcon

from lisp.backend.media_element import MediaType
from lisp.plugins.gst_backend.gst_pipe_edit import (
    _media_type_compatible,
    GstPipeEdit,
)
from lisp.plugins.gst_backend import elements


class TestMediaTypeCompatible:
    """Test the _media_type_compatible filter function."""

    def test_none_pipeline_allows_everything(self):
        assert _media_type_compatible(MediaType.Audio, None)
        assert _media_type_compatible(MediaType.Video, None)
        assert _media_type_compatible(
            MediaType.AudioAndVideo, None
        )

    def test_audio_pipeline_allows_audio(self):
        assert _media_type_compatible(
            MediaType.Audio, MediaType.Audio
        )

    def test_audio_pipeline_blocks_video(self):
        assert not _media_type_compatible(
            MediaType.Video, MediaType.Audio
        )

    def test_audio_pipeline_allows_audio_and_video(self):
        assert _media_type_compatible(
            MediaType.AudioAndVideo, MediaType.Audio
        )

    def test_video_pipeline_allows_video(self):
        assert _media_type_compatible(
            MediaType.Video, MediaType.Video
        )

    def test_video_pipeline_blocks_audio(self):
        assert not _media_type_compatible(
            MediaType.Audio, MediaType.Video
        )

    def test_video_pipeline_allows_audio_and_video(self):
        assert _media_type_compatible(
            MediaType.AudioAndVideo, MediaType.Video
        )

    def test_av_pipeline_allows_audio(self):
        assert _media_type_compatible(
            MediaType.Audio, MediaType.AudioAndVideo
        )

    def test_av_pipeline_allows_video(self):
        assert _media_type_compatible(
            MediaType.Video, MediaType.AudioAndVideo
        )

    def test_av_pipeline_allows_av(self):
        assert _media_type_compatible(
            MediaType.AudioAndVideo, MediaType.AudioAndVideo
        )


class TestGstPipeEditFiltering:
    """Test that GstPipeEdit filters elements by media type."""

    @pytest.fixture(autouse=True)
    def _load_elements(self):
        elements.load()

    @pytest.fixture(autouse=True)
    def _mock_icons(self):
        with patch(
            "lisp.ui.icons.IconTheme.get",
            return_value=QIcon(),
        ):
            yield

    def _available_plugins(self, edit):
        """Get class names of available plugins from the list."""
        from PyQt5.QtCore import Qt

        return [
            edit.availableList.item(i).data(Qt.UserRole)
            for i in range(edit.availableList.count())
        ]

    def _input_names(self, edit):
        return [
            edit.inputBox.itemData(i)
            for i in range(edit.inputBox.count())
        ]

    def _output_names(self, edit):
        return [
            edit.outputBox.itemData(i)
            for i in range(edit.outputBox.count())
        ]

    def test_audio_pipe_hides_video_plugins(self):
        edit = GstPipeEdit(
            ("UriInput", "Volume", "AutoSink"),
            media_type=MediaType.Audio,
        )
        assert "VideoAlpha" not in self._available_plugins(edit)

    def test_audio_pipe_shows_audio_plugins(self):
        edit = GstPipeEdit(
            ("UriInput", "AutoSink"),
            media_type=MediaType.Audio,
        )
        assert "Volume" in self._available_plugins(edit)

    def test_video_pipe_shows_video_alpha(self):
        edit = GstPipeEdit(
            ("UriAvInput", "Volume", "VideoSink"),
            media_type=MediaType.AudioAndVideo,
        )
        assert "VideoAlpha" in self._available_plugins(edit)

    def test_video_pipe_shows_audio_plugins(self):
        edit = GstPipeEdit(
            ("UriAvInput", "VideoSink"),
            media_type=MediaType.AudioAndVideo,
        )
        assert "Volume" in self._available_plugins(edit)

    def test_image_pipe_shows_video_alpha(self):
        edit = GstPipeEdit(
            ("ImageInput", "VideoSink"),
            media_type=MediaType.Video,
        )
        assert "VideoAlpha" in self._available_plugins(edit)

    def test_image_pipe_hides_audio_plugins(self):
        edit = GstPipeEdit(
            ("ImageInput", "VideoSink"),
            media_type=MediaType.Video,
        )
        available = self._available_plugins(edit)
        assert "Volume" not in available
        assert "Pitch" not in available

    def test_no_media_type_shows_everything(self):
        edit = GstPipeEdit(
            ("UriInput", "AutoSink"),
            media_type=None,
        )
        available = self._available_plugins(edit)
        assert "Volume" in available
        assert "VideoAlpha" in available

    def test_audio_pipe_input_list_filtered(self):
        edit = GstPipeEdit(
            ("UriInput", "AutoSink"),
            media_type=MediaType.Audio,
        )
        inputs = self._input_names(edit)
        assert "UriInput" in inputs
        assert "ImageInput" not in inputs

    def test_audio_pipe_output_includes_av_outputs(self):
        """AudioAndVideo outputs (VideoSink) are compatible with
        audio pipelines at the MediaType level."""
        edit = GstPipeEdit(
            ("UriInput", "AutoSink"),
            media_type=MediaType.Audio,
        )
        outputs = self._output_names(edit)
        assert "AutoSink" in outputs
        assert "VideoSink" in outputs

    def test_video_pipe_output_list_includes_video_sink(self):
        edit = GstPipeEdit(
            ("UriAvInput", "VideoSink"),
            media_type=MediaType.AudioAndVideo,
        )
        assert "VideoSink" in self._output_names(edit)
