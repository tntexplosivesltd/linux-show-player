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


class TestTargetResolution:
    def test_missing_target_logs_and_errors(self, mock_app, caplog):
        mock_app.cue_model.get.return_value = None
        cue = ResumeCue(app=mock_app)
        cue.target_id = "does-not-exist"

        error_fired = []

        # Named def so the test frame holds a strong reference — LiSP's
        # Signal.connect stores a weakref, which would GC an inline lambda.
        def on_error(*_):
            error_fired.append(True)

        cue.error.connect(on_error)

        result = cue.__start__()

        assert result is False
        assert error_fired == [True]
        assert any("target" in r.message.lower() for r in caplog.records)

    def test_empty_target_id_logs_and_errors(self, mock_app):
        mock_app.cue_model.get.return_value = None
        cue = ResumeCue(app=mock_app)
        cue.target_id = ""

        error_fired = []

        def on_error(*_):
            error_fired.append(True)

        cue.error.connect(on_error)

        result = cue.__start__()

        assert result is False
        assert error_fired == [True]
