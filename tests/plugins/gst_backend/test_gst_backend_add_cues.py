"""Tests for GstBackend.add_{video,image,audio}_cue_from_files.

Each of these methods:
  1. Creates the appropriate factory with the configured pipeline
  2. Instantiates a cue per file, using the filename (no extension)
     as the cue's name
  3. Pushes a LayoutAutoInsertCuesCommand to the commands stack
"""

import os
import pytest
from unittest.mock import MagicMock, patch

from lisp.core.session_uri import SessionURI
from lisp.plugins.gst_backend import elements as gst_elements
from lisp.plugins.gst_backend.gst_backend import GstBackend


@pytest.fixture(scope="module", autouse=True)
def load_elements():
    gst_elements.load()


@pytest.fixture(autouse=True)
def _bypass_session_paths():
    """Stop SessionURI from trying to resolve paths through the
    Application singleton during URI assignment.

    The production backend passes raw filesystem paths (no scheme)
    to the factory; SessionURI would normally call
    Application().session.abs_path(...) to resolve them.
    """
    with patch.object(
        SessionURI, "path_to_absolute",
        staticmethod(lambda p: p),
    ), patch.object(
        SessionURI, "path_to_relative",
        staticmethod(lambda p: p),
    ):
        yield


def _make_backend():
    """Construct a GstBackend stub with just the attributes our
    code under test uses. Bypasses the real __init__ to avoid
    creating windows, loading plugins, etc.

    `app` is a read-only property on Plugin, so we set the private
    backing attribute directly.
    """
    backend = object.__new__(GstBackend)
    app = MagicMock()
    app.commands_stack = MagicMock()
    app.session.layout = MagicMock()
    # Plugin.__init__ sets self.__app, name-mangled to _Plugin__app.
    backend._Plugin__app = app
    return backend


class TestAddVideoCueFromFiles:
    def setup_method(self):
        self.config_patch = patch.object(
            GstBackend, "Config",
            {
                "video_pipeline": [
                    "Volume", "DbMeter", "VideoAlpha", "VideoSink"
                ],
                "image_pipeline": ["VideoAlpha", "VideoSink"],
                "pipeline": ["Volume", "DbMeter", "AutoSink"],
            },
        )
        self.config_patch.start()

    def teardown_method(self):
        self.config_patch.stop()

    def test_creates_one_cue_per_file(self):
        backend = _make_backend()
        backend.add_video_cue_from_files([
            "/tmp/a.mp4", "/tmp/b.mkv",
        ])

        # commands_stack.do was called once with a command wrapping
        # two cues (the layout insert command).
        assert backend.app.commands_stack.do.call_count == 1
        cmd = backend.app.commands_stack.do.call_args.args[0]
        assert len(_command_cues(cmd)) == 2

    def test_cue_name_is_filename_without_extension(self):
        backend = _make_backend()
        backend.add_video_cue_from_files(["/tmp/opening_clip.mp4"])

        cmd = backend.app.commands_stack.do.call_args.args[0]
        cue = _first_cue_in_command(cmd)
        assert cue.name == "opening_clip"

    def test_uses_video_factory_input(self):
        backend = _make_backend()
        backend.add_video_cue_from_files(["/tmp/clip.mp4"])

        cmd = backend.app.commands_stack.do.call_args.args[0]
        cue = _first_cue_in_command(cmd)
        assert cue.media.elements.UriAvInput is not None
        assert cue.icon == "film"

    def test_uri_propagates_to_element(self):
        backend = _make_backend()
        backend.add_video_cue_from_files(["/tmp/clip.mp4"])

        cmd = backend.app.commands_stack.do.call_args.args[0]
        cue = _first_cue_in_command(cmd)
        # SessionURI wraps bare paths in a file:// URI before the
        # adapter hands the raw string to GStreamer.
        assert cue.media.elements.UriAvInput.decoder.get_property(
            "uri"
        ) == "file:///tmp/clip.mp4"

    def test_empty_files_list_still_submits_command(self):
        # The behaviour mirrors add_cue_from_files: an empty list
        # creates no cues but still pushes the (empty) insert command.
        backend = _make_backend()
        backend.add_video_cue_from_files([])
        assert backend.app.commands_stack.do.call_count == 1


class TestAddImageCueFromFiles:
    def setup_method(self):
        self.config_patch = patch.object(
            GstBackend, "Config",
            {
                "video_pipeline": ["Volume", "DbMeter", "VideoSink"],
                "image_pipeline": ["VideoAlpha", "VideoSink"],
                "pipeline": ["Volume", "DbMeter", "AutoSink"],
            },
        )
        self.config_patch.start()

    def teardown_method(self):
        self.config_patch.stop()

    def test_uses_image_factory_input(self):
        backend = _make_backend()
        backend.add_image_cue_from_files(["/tmp/slide.png"])

        cmd = backend.app.commands_stack.do.call_args.args[0]
        cue = _first_cue_in_command(cmd)
        assert cue.media.elements.ImageInput is not None
        assert cue.icon == "camera"

    def test_cue_name_is_filename_without_extension(self):
        backend = _make_backend()
        backend.add_image_cue_from_files(["/tmp/stage_photo.jpg"])

        cmd = backend.app.commands_stack.do.call_args.args[0]
        cue = _first_cue_in_command(cmd)
        assert cue.name == "stage_photo"

    def test_custom_duration_propagates(self):
        backend = _make_backend()
        backend.add_image_cue_from_files(
            ["/tmp/slide.png"], duration=2500
        )

        cmd = backend.app.commands_stack.do.call_args.args[0]
        cue = _first_cue_in_command(cmd)
        assert cue.media.elements.ImageInput.duration == 2500

    def test_default_duration_is_5000(self):
        backend = _make_backend()
        backend.add_image_cue_from_files(["/tmp/slide.png"])

        cmd = backend.app.commands_stack.do.call_args.args[0]
        cue = _first_cue_in_command(cmd)
        assert cue.media.elements.ImageInput.duration == 5000


def _command_cues(cmd):
    """Extract the cues passed to LayoutAutoInsertCuesCommand.

    The command chain (ModelItemsCommand) stores them on the
    ``_items`` slot.
    """
    return list(cmd._items)


def _first_cue_in_command(cmd):
    cues = _command_cues(cmd)
    assert cues, "Expected at least one cue in the insert command"
    return cues[0]
