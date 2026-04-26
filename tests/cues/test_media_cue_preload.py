"""Tests for MediaCue.preload property."""

from unittest.mock import MagicMock

from lisp.cues.media_cue import MediaCue


def _make_cue(mock_app):
    """Construct a MediaCue with a mock media instance."""
    media = MagicMock()
    cue = MediaCue(mock_app, media)
    return cue


def test_preload_default_false(mock_app):
    cue = _make_cue(mock_app)
    assert cue.preload is False


def test_preload_settable(mock_app):
    cue = _make_cue(mock_app)
    cue.preload = True
    assert cue.preload is True


def test_preload_emits_changed(mock_app):
    cue = _make_cue(mock_app)
    received = []

    def _handler(value):
        received.append(value)

    cue.changed("preload").connect(_handler)
    cue.preload = True
    assert received == [True]


def test_preload_serialization_roundtrip(mock_app):
    cue = _make_cue(mock_app)
    cue.preload = True
    state = cue.properties()
    assert state["preload"] is True

    cue2 = _make_cue(mock_app)
    cue2.update_properties(state)
    assert cue2.preload is True
