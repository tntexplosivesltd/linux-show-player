"""Tests for GstBackend.add_cue_from_urls file type routing."""

from unittest.mock import MagicMock, patch, call

from lisp.plugins.gst_backend.gst_backend import GstBackend


class TestAddCueFromUrlsRouting:
    """Test that add_cue_from_urls routes files to the correct factory."""

    def _make_url(self, filename):
        url = MagicMock()
        url.fileName.return_value = filename
        url.path.return_value = f"/tmp/{filename}"
        return url

    def _make_backend(self):
        backend = object.__new__(GstBackend)
        backend.supported_extensions = MagicMock(return_value={
            "audio": ["wav", "mp3", "flac", "ogg"],
            "video": ["mp4", "mkv", "webm", "avi"],
            "image": ["jpg", "jpeg", "png", "bmp", "svg"],
        })
        backend.add_cue_from_files = MagicMock()
        backend.add_video_cue_from_files = MagicMock()
        backend.add_image_cue_from_files = MagicMock()
        return backend

    def test_wav_routed_to_audio(self):
        backend = self._make_backend()
        backend.add_cue_from_urls([self._make_url("track.wav")])

        backend.add_cue_from_files.assert_called_once_with(
            ["/tmp/track.wav"]
        )
        backend.add_video_cue_from_files.assert_not_called()
        backend.add_image_cue_from_files.assert_not_called()

    def test_mp4_routed_to_video(self):
        backend = self._make_backend()
        backend.add_cue_from_urls([self._make_url("clip.mp4")])

        backend.add_video_cue_from_files.assert_called_once_with(
            ["/tmp/clip.mp4"]
        )
        backend.add_cue_from_files.assert_not_called()
        backend.add_image_cue_from_files.assert_not_called()

    def test_jpg_routed_to_image(self):
        backend = self._make_backend()
        backend.add_cue_from_urls([self._make_url("photo.jpg")])

        backend.add_image_cue_from_files.assert_called_once_with(
            ["/tmp/photo.jpg"]
        )
        backend.add_cue_from_files.assert_not_called()
        backend.add_video_cue_from_files.assert_not_called()

    def test_png_routed_to_image(self):
        backend = self._make_backend()
        backend.add_cue_from_urls([self._make_url("slide.png")])

        backend.add_image_cue_from_files.assert_called_once_with(
            ["/tmp/slide.png"]
        )

    def test_mixed_files_routed_correctly(self):
        backend = self._make_backend()
        backend.add_cue_from_urls([
            self._make_url("song.mp3"),
            self._make_url("clip.mkv"),
            self._make_url("bg.png"),
            self._make_url("effect.wav"),
            self._make_url("title.jpg"),
        ])

        backend.add_cue_from_files.assert_called_once_with(
            ["/tmp/song.mp3", "/tmp/effect.wav"]
        )
        backend.add_video_cue_from_files.assert_called_once_with(
            ["/tmp/clip.mkv"]
        )
        backend.add_image_cue_from_files.assert_called_once_with(
            ["/tmp/bg.png", "/tmp/title.jpg"]
        )

    def test_unsupported_extension_ignored(self):
        backend = self._make_backend()
        backend.add_cue_from_urls([self._make_url("doc.pdf")])

        backend.add_cue_from_files.assert_not_called()
        backend.add_video_cue_from_files.assert_not_called()
        backend.add_image_cue_from_files.assert_not_called()

    def test_empty_urls_no_calls(self):
        backend = self._make_backend()
        backend.add_cue_from_urls([])

        backend.add_cue_from_files.assert_not_called()
        backend.add_video_cue_from_files.assert_not_called()
        backend.add_image_cue_from_files.assert_not_called()

    def test_uppercase_extension_routed_correctly(self):
        backend = self._make_backend()
        backend.add_cue_from_urls([
            self._make_url("PHOTO.JPG"),
            self._make_url("VIDEO.MP4"),
            self._make_url("TRACK.WAV"),
        ])

        backend.add_cue_from_files.assert_called_once_with(
            ["/tmp/TRACK.WAV"]
        )
        backend.add_video_cue_from_files.assert_called_once_with(
            ["/tmp/VIDEO.MP4"]
        )
        backend.add_image_cue_from_files.assert_called_once_with(
            ["/tmp/PHOTO.JPG"]
        )

    def test_mixed_case_extension_routed(self):
        backend = self._make_backend()
        backend.add_cue_from_urls([
            self._make_url("photo.Png"),
        ])

        backend.add_image_cue_from_files.assert_called_once_with(
            ["/tmp/photo.Png"]
        )
