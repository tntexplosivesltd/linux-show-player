"""Unit tests for StopCue (Fade & Stop) action cue."""
import pytest
from unittest.mock import MagicMock

from lisp.core.fade_functions import FadeOutType
from lisp.cues.cue import CueAction
from lisp.plugins.action_cues.stop_cue import StopCue


class TestStopCueDefaults:
    def test_class_display_name(self):
        assert StopCue.Name == "Fade & Stop"

    def test_class_category(self):
        assert StopCue.Category == "Action cues"

    def test_class_supported_actions(self):
        assert CueAction.Default in StopCue.CueActions
        assert CueAction.Start in StopCue.CueActions
        assert CueAction.Stop in StopCue.CueActions
        assert CueAction.Interrupt in StopCue.CueActions

    def test_default_target_id(self, mock_app):
        cue = StopCue(app=mock_app)
        assert cue.target_id is None or cue.target_id == ""

    def test_default_action(self, mock_app):
        cue = StopCue(app=mock_app)
        assert cue.action == CueAction.Stop.value

    def test_default_fade_type(self, mock_app):
        cue = StopCue(app=mock_app)
        assert cue.fade_type == FadeOutType.Linear.name

    def test_default_duration_zero(self, mock_app):
        cue = StopCue(app=mock_app)
        assert cue.duration == 0

    def test_default_icon(self, mock_app):
        cue = StopCue(app=mock_app)
        assert cue.icon == "action-stop"
