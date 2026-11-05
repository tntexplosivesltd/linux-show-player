"""The inspector's commit engine on real `GstMediaCue` objects.

The engine's own tests (`tests/ui/inspector/test_commit.py`) use fake
cues. Real media differs in two ways that matter to `_cue_update`:
element names on `GstMedia.elements` are instance properties added
when the pipe is set, and `GstMedia.update_properties` is overridden.
"""

import copy
import json
from unittest.mock import MagicMock, patch

import pytest

from lisp.command.cue import UpdateCueCommand, UpdateCuesCommand
from lisp.core.properties import Property
from lisp.plugins.gst_backend import elements as gst_elements
from lisp.plugins.gst_backend.gst_media import GstMedia
from lisp.plugins.gst_backend.gst_media_cue import GstMediaCue
from lisp.ui.inspector.commit import InspectorCommitEngine
from lisp.ui.settings.pages import SettingsPage

WITH_VOLUME = ("UriInput", "Volume", "AutoSink")
WITHOUT_VOLUME = ("UriInput", "AutoSink")


@pytest.fixture(scope="module", autouse=True)
def load_elements():
    gst_elements.load()


@pytest.fixture(autouse=True)
def session_paths():
    """Undo restores every property, `UriInput.uri` included, and
    `SessionURI` resolves paths through `Application().session`.
    Stand in for it (never the real singleton) with identity paths."""
    app = MagicMock()
    app.session.abs_path.side_effect = lambda path: path
    app.session.rel_path.side_effect = lambda path: path
    with patch("lisp.application.Application", return_value=app):
        yield


class _ControlledMediaCue(GstMediaCue):
    """A real `GstMediaCue` with the plain dict property the controller
    plugin registers on `Cue` (`Cue.controller`)."""

    controller = Property(default={})


class _Page(SettingsPage):
    """Emits whatever `settings` holds, the way real pages emit plain
    data built from their widgets (rows as tuples)."""

    Name = "Probe"

    def __init__(self, settings):
        super().__init__()
        self.settings = settings

    def getSettings(self):
        return copy.deepcopy(self.settings)


def _cue(app, pipe, keyboard):
    cue = _ControlledMediaCue(app, GstMedia(), pipeline=pipe)
    # A local file that doesn't exist: an empty uri resolves to the
    # working directory, whose mtime `UriInput` would stamp on every
    # uri set (undo included), and a real file would start a
    # background duration probe.
    cue.media.elements.UriInput.uri = "file:///nonexistent/probe.wav"
    # As a saved show holds it: `json.load` gives rows as lists.
    cue.controller = json.loads(
        json.dumps(
            {"midi": [["note_on 1", "Start"]], "keyboard": [[keyboard, "Stop"]]}
        )
    )
    return cue


def _page_for(cue):
    """The page a Volume edit and a MIDI edit flush from together."""
    return _Page(
        {
            "media": {"elements": {"Volume": {"volume": 1.0}}},
            "controller": {
                "midi": [("note_on 1", "Start")],
                "keyboard": [tuple(r) for r in cue.controller["keyboard"]],
            },
        }
    )


@pytest.fixture
def engine(qtbot):
    stack = MagicMock()
    engine = InspectorCommitEngine(commands_stack=stack)
    yield engine, stack
    engine.unbind()


def _media_without_volume(cue):
    props = cue.media.properties()
    props["elements"].pop("Volume", None)
    return props


def test_volume_and_midi_edit_in_one_flush(engine, qtbot, mock_app):
    engine, stack = engine
    cue = _cue(mock_app, WITH_VOLUME, "a")
    volume = cue.media.element("Volume")
    volume.mute = True
    volume.normal_volume = 0.8
    page = _page_for(cue)
    qtbot.addWidget(page)
    media_before = _media_without_volume(cue)
    original = copy.deepcopy(cue.properties())

    engine.bind(page, [cue])
    page.settings["media"]["elements"]["Volume"]["volume"] = 0.5
    page.settings["controller"]["midi"] = [("note_on 2", "Start")]
    engine.flush()

    command = stack.do.call_args.args[0]
    assert isinstance(command, UpdateCueCommand)
    command.do()

    # The media edit stayed partial: only `volume` changed.
    assert volume.volume == 0.5
    assert (volume.mute, volume.normal_volume) == (True, 0.8)
    assert _media_without_volume(cue) == media_before
    # The MIDI edit kept the keyboard mapping (the original bug).
    assert cue.controller == {
        "midi": [("note_on 2", "Start")],
        "keyboard": [["a", "Stop"]],
    }

    command.undo()
    assert cue.properties() == original

    command.redo()
    assert volume.volume == 0.5
    assert cue.controller["midi"] == [("note_on 2", "Start")]


def test_multi_select_cue_without_the_element_is_left_alone(
    engine, qtbot, mock_app
):
    engine, stack = engine
    bare = _cue(mock_app, WITHOUT_VOLUME, "b")
    with_volume = _cue(mock_app, WITH_VOLUME, "a")
    # The page shows the last-loaded cue, which has a Volume element.
    page = _page_for(with_volume)
    qtbot.addWidget(page)
    bare_before = copy.deepcopy(bare.properties())
    with_volume_before = copy.deepcopy(with_volume.properties())

    engine.bind(page, [bare, with_volume])
    page.settings["media"]["elements"]["Volume"]["volume"] = 0.5
    engine.flush()

    command = stack.do.call_args.args[0]
    assert isinstance(command, UpdateCuesCommand)
    command.do()

    assert with_volume.media.element("Volume").volume == 0.5
    # No Volume element: nothing is added, and the untouched
    # controller keeps this cue's own keyboard mapping.
    assert bare.media.element("Volume") is None
    assert bare.properties() == bare_before

    command.undo()
    assert with_volume.properties() == with_volume_before
    assert bare.properties() == bare_before
