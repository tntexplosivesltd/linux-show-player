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


from lisp.cues.cue import CueState
from lisp.cues.media_cue import MediaCue


def _make_media_target(state, mock_app, cue_id="t1"):
    """Build a mock MediaCue target in the given state and wire into mock_app."""
    target = MagicMock(spec=MediaCue)
    target.id = cue_id
    target.state = state
    target.media = MagicMock()
    target.media.element.return_value = None
    mock_app.cue_model.get.return_value = target
    return target


class TestStoppedOrErrorTarget:
    def test_stopped_target_errors(self, mock_app, caplog):
        target = _make_media_target(CueState.Stop, mock_app)

        cue = ResumeCue(app=mock_app)
        cue.target_id = target.id

        error_fired = []

        def on_error(*_):
            error_fired.append(True)

        cue.error.connect(on_error)

        result = cue.__start__()

        assert result is False
        assert error_fired == [True]
        target.execute.assert_not_called()

    def test_error_target_errors(self, mock_app):
        target = _make_media_target(CueState.Error, mock_app)

        cue = ResumeCue(app=mock_app)
        cue.target_id = target.id

        error_fired = []

        def on_error(*_):
            error_fired.append(True)

        cue.error.connect(on_error)

        result = cue.__start__()

        assert result is False
        assert error_fired == [True]
        target.execute.assert_not_called()


def _patch_async_function_synchronous(monkeypatch):
    """Make @async_function run its wrapped target synchronously.

    `async_function` wraps a call in `Thread(target=..., daemon=True).start()`.
    Substituting Thread with a class that calls the target immediately on
    `start()` makes assertions deterministic.
    """
    class _SyncThread:
        def __init__(self, target=None, args=(), kwargs=None, daemon=False,
                     name=None):
            self._target = target
            self._args = args
            self._kwargs = kwargs or {}

        def start(self):
            self._target(*self._args, **self._kwargs)
    monkeypatch.setattr("lisp.core.decorators.Thread", _SyncThread)


class TestRunningFallback:
    def test_running_no_resume_dispatched(self, mock_app, monkeypatch):
        """Running target: Resume is NOT dispatched (already running)."""
        target = _make_media_target(CueState.Running, mock_app)

        # Substitute a fake runner so we don't actually run threads.
        fake_runner = MagicMock()
        fake_runner.run_until_complete.return_value = True
        monkeypatch.setattr(
            "lisp.plugins.action_cues.resume_cue.ParallelFadeRunner",
            MagicMock(return_value=fake_runner),
        )
        _patch_async_function_synchronous(monkeypatch)

        # Give the target a volume fader so `will_fade` is True.
        volume_fader = MagicMock()
        volume_el = MagicMock()
        volume_el.get_fader.return_value = volume_fader
        target.media.element = lambda n: volume_el if n == "Volume" else None

        cue = ResumeCue(app=mock_app)
        cue.target_id = target.id
        cue.duration = 500

        result = cue.__start__()

        assert result is True
        target.execute.assert_not_called()  # no Resume dispatched
        fake_runner.run_until_complete.assert_called_once()

    def test_running_no_faders_is_noop(self, mock_app):
        """Running target with no faders: no-op, returns False."""
        target = _make_media_target(CueState.Running, mock_app)

        cue = ResumeCue(app=mock_app)
        cue.target_id = target.id
        cue.duration = 500

        result = cue.__start__()

        assert result is False
        target.execute.assert_not_called()

    def test_running_duration_zero_is_noop(self, mock_app):
        """Running target with duration=0: no-op (no fade needed)."""
        target = _make_media_target(CueState.Running, mock_app)
        volume_el = MagicMock()
        volume_el.get_fader.return_value = MagicMock()
        target.media.element = lambda n: volume_el if n == "Volume" else None

        cue = ResumeCue(app=mock_app)
        cue.target_id = target.id
        cue.duration = 0

        result = cue.__start__()

        assert result is False
        target.execute.assert_not_called()

    def test_prewait_treated_as_running(self, mock_app, monkeypatch):
        """PreWait/PostWait map to the Running fallback."""
        target = _make_media_target(CueState.PreWait, mock_app)

        fake_runner = MagicMock()
        fake_runner.run_until_complete.return_value = True
        monkeypatch.setattr(
            "lisp.plugins.action_cues.resume_cue.ParallelFadeRunner",
            MagicMock(return_value=fake_runner),
        )
        _patch_async_function_synchronous(monkeypatch)

        volume_el = MagicMock()
        volume_el.get_fader.return_value = MagicMock()
        target.media.element = lambda n: volume_el if n == "Volume" else None

        cue = ResumeCue(app=mock_app)
        cue.target_id = target.id
        cue.duration = 500

        cue.__start__()

        target.execute.assert_not_called()
