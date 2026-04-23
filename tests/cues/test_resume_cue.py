"""Unit tests for ResumeCue (Fade & Resume) action cue."""
from unittest.mock import MagicMock

from lisp.core.fade_functions import FadeInType
from lisp.cues.cue import CueAction
from lisp.plugins.action_cues.resume_cue import ResumeCue


class TestResumeCueDefaults:
    def test_class_display_name(self):
        assert ResumeCue.Name == "Fade & Resume"

    def test_class_category(self):
        assert ResumeCue.Category == "Action cues"

    def test_class_supported_actions(self):
        assert CueAction.Default in ResumeCue.CueActions
        assert CueAction.Start in ResumeCue.CueActions
        assert CueAction.Stop in ResumeCue.CueActions
        assert CueAction.Interrupt in ResumeCue.CueActions

    def test_default_target_id(self, mock_app):
        cue = ResumeCue(app=mock_app)
        assert cue.target_id is None or cue.target_id == ""

    def test_default_fade_type(self, mock_app):
        cue = ResumeCue(app=mock_app)
        assert cue.fade_type == FadeInType.Linear.name

    def test_default_duration_zero(self, mock_app):
        cue = ResumeCue(app=mock_app)
        assert cue.duration == 0

    def test_no_action_property(self, mock_app):
        """ResumeCue has no `action` property — verb is fixed to Resume."""
        cue = ResumeCue(app=mock_app)
        assert not hasattr(type(cue), "action") or \
            "action" not in type(cue).__dict__
