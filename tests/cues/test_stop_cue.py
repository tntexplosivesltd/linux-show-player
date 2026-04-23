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


class TestTargetResolution:
    def test_missing_target_logs_and_errors(self, mock_app, caplog):
        mock_app.cue_model.get.return_value = None
        cue = StopCue(app=mock_app)
        cue.target_id = "does-not-exist"

        error_fired = []

        def on_error(*_):
            error_fired.append(True)

        cue.error.connect(on_error)

        result = cue.__start__()

        assert result is False
        assert error_fired == [True]
        assert any("target" in r.message.lower() for r in caplog.records)

    def test_empty_target_id_logs_and_errors(self, mock_app):
        mock_app.cue_model.get.return_value = None
        cue = StopCue(app=mock_app)
        cue.target_id = ""

        error_fired = []

        def on_error(*_):
            error_fired.append(True)

        cue.error.connect(on_error)

        result = cue.__start__()

        assert result is False
        assert error_fired == [True]


class TestFadeThenAction:
    def _setup(self, mock_app, target_id="t1"):
        from lisp.cues.cue import CueState
        from lisp.cues.media_cue import MediaCue

        target = MagicMock(spec=MediaCue)
        target.id = target_id
        target.state = CueState.Running
        target.media = MagicMock()
        target.media.element.return_value = None  # no faders
        mock_app.cue_model.get.return_value = target

        cue = StopCue(app=mock_app)
        cue.target_id = target_id
        return cue, target

    def test_instant_action_when_duration_zero(self, mock_app):
        """duration=0 + no faders -> action fires synchronously."""
        cue, target = self._setup(mock_app)
        cue.duration = 0
        cue.action = CueAction.Stop.value

        cue.__start__()

        target.execute.assert_called_once_with(CueAction.Stop)

    def test_no_faders_with_duration_still_fires_action(self, mock_app):
        """duration>0 but no faders collected -> action fires immediately."""
        cue, target = self._setup(mock_app)
        cue.duration = 1000
        cue.action = CueAction.Pause.value

        cue.__start__()
        target.execute.assert_called_once_with(CueAction.Pause)

    def test_fade_then_action_uses_runner_and_dispatches(self, mock_app,
                                                         monkeypatch):
        """duration>0 with faders -> ParallelFadeRunner runs, then dispatch."""
        from lisp.cues.cue import CueState
        from lisp.cues.media_cue import MediaCue

        fake_runner = MagicMock()
        fake_runner.run_until_complete.return_value = True
        runner_cls = MagicMock(return_value=fake_runner)
        monkeypatch.setattr(
            "lisp.plugins.action_cues.stop_cue.ParallelFadeRunner",
            runner_cls,
        )

        volume_fader = MagicMock()
        volume_el = MagicMock()
        volume_el.get_fader.return_value = volume_fader

        target = MagicMock(spec=MediaCue)
        target.state = CueState.Running
        target.media = MagicMock()
        target.media.element = lambda n: volume_el if n == "Volume" else None
        mock_app.cue_model.get.return_value = target

        # Patch @async_function's Thread so the coordinator runs sync.
        class _FakeThread:
            def __init__(self, target=None, args=(), kwargs=None,
                         daemon=False, name=None):
                self._target = target
                self._args = args
                self._kwargs = kwargs or {}

            def start(self):
                self._target(*self._args, **self._kwargs)
        monkeypatch.setattr("lisp.core.decorators.Thread", _FakeThread)

        cue = StopCue(app=mock_app)
        cue.target_id = "t1"
        cue.duration = 500
        cue.action = CueAction.Interrupt.value

        cue.__start__()

        runner_cls.assert_called_once()
        fake_runner.run_until_complete.assert_called_once()
        target.execute.assert_called_once_with(CueAction.Interrupt)

    def test_action_is_non_fading_variant(self, mock_app):
        """action=Stop should dispatch the plain non-fading variant."""
        cue, target = self._setup(mock_app)
        cue.duration = 0

        for action_enum in (
            CueAction.Stop, CueAction.Pause, CueAction.Interrupt,
        ):
            target.reset_mock()
            cue.action = action_enum.value
            cue.__start__()
            target.execute.assert_called_once_with(action_enum)
            assert target.execute.call_args[0][0] not in (
                CueAction.FadeOutStop,
                CueAction.FadeOutPause,
                CueAction.FadeOutInterrupt,
            )

    def test_ended_signal_fires_on_clean_completion(self, mock_app,
                                                     monkeypatch):
        """After the fade + dispatch land, the StopCue itself must
        signal end so its state machine transitions out of Running.
        Without _ended(), the list layout would show the StopCue as
        permanently running."""
        from lisp.cues.cue import CueState
        from lisp.cues.media_cue import MediaCue

        fake_runner = MagicMock()
        fake_runner.run_until_complete.return_value = True
        monkeypatch.setattr(
            "lisp.plugins.action_cues.stop_cue.ParallelFadeRunner",
            MagicMock(return_value=fake_runner),
        )

        class _FakeThread:
            def __init__(self, target=None, args=(), kwargs=None,
                         daemon=False, name=None):
                self._target = target
                self._args = args
                self._kwargs = kwargs or {}

            def start(self):
                self._target(*self._args, **self._kwargs)
        monkeypatch.setattr("lisp.core.decorators.Thread", _FakeThread)

        volume_el = MagicMock()
        volume_el.get_fader.return_value = MagicMock()
        target = MagicMock(spec=MediaCue)
        target.state = CueState.Running
        target.media = MagicMock()
        target.media.element = lambda n: volume_el if n == "Volume" else None
        mock_app.cue_model.get.return_value = target

        cue = StopCue(app=mock_app)
        cue.target_id = "t1"
        cue.duration = 500
        cue.action = CueAction.Stop.value

        end_fired = []

        def on_end(*_):
            end_fired.append(True)

        cue.end.connect(on_end)

        cue.__start__()

        assert end_fired == [True]
        assert cue._runner is None  # cleaned up in finally

    def test_runner_abort_skips_action_dispatch(self, mock_app, monkeypatch):
        """If the runner returns False (aborted), action is NOT dispatched."""
        from lisp.cues.cue import CueState
        from lisp.cues.media_cue import MediaCue

        fake_runner = MagicMock()
        fake_runner.run_until_complete.return_value = False
        monkeypatch.setattr(
            "lisp.plugins.action_cues.stop_cue.ParallelFadeRunner",
            MagicMock(return_value=fake_runner),
        )

        class _FakeThread:
            def __init__(self, target=None, args=(), kwargs=None,
                         daemon=False, name=None):
                self._target = target
                self._args = args
                self._kwargs = kwargs or {}

            def start(self):
                self._target(*self._args, **self._kwargs)
        monkeypatch.setattr("lisp.core.decorators.Thread", _FakeThread)

        volume_el = MagicMock()
        volume_el.get_fader.return_value = MagicMock()
        target = MagicMock(spec=MediaCue)
        target.state = CueState.Running
        target.media = MagicMock()
        target.media.element = lambda n: volume_el if n == "Volume" else None
        mock_app.cue_model.get.return_value = target

        cue = StopCue(app=mock_app)
        cue.target_id = "t1"
        cue.duration = 500
        cue.action = CueAction.Stop.value

        cue.__start__()

        target.execute.assert_not_called()


class TestAbort:
    def test_stop_aborts_runner_when_present(self, mock_app):
        cue = StopCue(app=mock_app)
        cue._runner = MagicMock()

        result = cue.__stop__()

        cue._runner.abort.assert_called_once()
        assert result is True

    def test_interrupt_aborts_runner_when_present(self, mock_app):
        cue = StopCue(app=mock_app)
        runner = MagicMock()
        cue._runner = runner

        cue.__interrupt__()

        runner.abort.assert_called_once()

    def test_stop_without_runner_is_safe(self, mock_app):
        """No in-flight fade: __stop__ must not crash."""
        cue = StopCue(app=mock_app)
        assert cue._runner is None
        assert cue.__stop__() is True  # no exception raised


class TestSessionRoundTrip:
    """All configured properties must survive a session save/load cycle —
    what lands on disk (via `properties()`) must load back (via
    `update_properties()`) into a cue whose __start__ still works."""

    def test_round_trip_preserves_all_configured_properties(self, mock_app):
        cue = StopCue(app=mock_app)
        cue.target_id = "abc-123"
        cue.action = CueAction.Pause.value
        cue.duration = 2500
        cue.fade_type = "Quadratic"

        dumped = cue.properties()

        assert dumped["target_id"] == "abc-123"
        assert dumped["action"] == CueAction.Pause.value
        assert dumped["duration"] == 2500
        assert dumped["fade_type"] == "Quadratic"

        # Reload into a fresh cue
        restored = StopCue(app=mock_app)
        restored.update_properties(dumped)

        assert restored.target_id == "abc-123"
        assert restored.action == CueAction.Pause.value
        assert restored.duration == 2500
        assert restored.fade_type == "Quadratic"


class TestCurrentTime:
    def test_no_runner_returns_zero(self, mock_app):
        cue = StopCue(app=mock_app)
        assert cue._runner is None
        assert cue.current_time() == 0

    def test_delegates_to_runner(self, mock_app):
        cue = StopCue(app=mock_app)
        cue._runner = MagicMock()
        cue._runner.current_time.return_value = 1250

        assert cue.current_time() == 1250


class TestStopCueSettings:
    """Settings-page round-trip. Requires QApplication via qapp fixture."""

    @pytest.fixture(autouse=True)
    def _icon_theme(self):
        """FadeEdit → FadeComboBox looks up icons via IconTheme.get; init a
        theme so _GlobalTheme isn't None when the settings page is built."""
        from lisp.ui.icons import IconTheme
        if IconTheme._GlobalTheme is None:
            IconTheme.set_theme_name("lisp")
        yield

    def test_get_settings_empty_when_checkable_and_unchecked(
        self, qapp, monkeypatch,
    ):
        """enableCheck(True) makes groups checkable and leaves them
        unchecked; getSettings should skip every group in that state.
        This mirrors the 'apply to group of cues' dialog flow.

        Note: StopCueSettings.__init__ calls Application() to populate
        the CueSelectDialog; monkeypatching avoids creating the real
        singleton (which would register the base General/Timing pages
        into the shared CueSettingsRegistry and pollute other tests).
        """
        from lisp.plugins.action_cues.stop_cue import StopCueSettings

        monkeypatch.setattr(
            "lisp.plugins.action_cues.stop_cue.Application",
            lambda: MagicMock(cue_model=MagicMock(
                get=lambda _id: None, filter=lambda *_: [],
            )),
        )

        page = StopCueSettings()
        page.enableCheck(True)
        assert page.getSettings() == {}

    def test_load_then_get_round_trip(self, qapp, monkeypatch):
        from lisp.plugins.action_cues.stop_cue import StopCueSettings

        fake_target = MagicMock()
        fake_target.name = "Target Cue"
        monkeypatch.setattr(
            "lisp.plugins.action_cues.stop_cue.Application",
            lambda: MagicMock(cue_model=MagicMock(
                get=lambda _id: fake_target, filter=lambda *_: [],
            )),
        )

        page = StopCueSettings()
        # Default state: groups are NOT checkable → isGroupEnabled() is True,
        # so getSettings() reads every group. This matches the single-cue
        # dialog flow.
        page.loadSettings({
            "target_id": "abc",
            "action": CueAction.Pause.value,
            "duration": 2500,
            "fade_type": "Linear",
        })

        settings = page.getSettings()
        assert settings["target_id"] == "abc"
        assert settings["action"] == CueAction.Pause.value
        assert settings["duration"] == 2500
        assert settings["fade_type"] == "Linear"

    def test_target_picker_excludes_sfr_cues(self, qapp, monkeypatch):
        """The target picker must not list StopCue or ResumeCue instances
        — targeting another SFR-cue has no useful semantics: they aren't
        MediaCues, so the fader set would be empty, and the instant path
        would just re-fire the action on a non-playing target."""
        from lisp.plugins.action_cues.stop_cue import StopCue, StopCueSettings
        from lisp.plugins.action_cues.resume_cue import ResumeCue

        # Mix of StopCue + ResumeCue + non-SFR in the model
        other_stop = MagicMock(spec=StopCue)
        other_resume = MagicMock(spec=ResumeCue)
        non_sfr = MagicMock()

        captured = {}

        class _FakeDialog:
            def __init__(self, cues=None, parent=None):
                captured["cues"] = list(cues)

        monkeypatch.setattr(
            "lisp.plugins.action_cues.stop_cue.CueSelectDialog",
            _FakeDialog,
        )
        monkeypatch.setattr(
            "lisp.plugins.action_cues.stop_cue.Application",
            lambda: MagicMock(cue_model=MagicMock(
                filter=lambda _cls: [other_stop, other_resume, non_sfr],
                get=lambda _id: None,
            )),
        )

        StopCueSettings()

        assert other_stop not in captured["cues"]
        assert other_resume not in captured["cues"]
        assert non_sfr in captured["cues"]

    def test_registry_association(self):
        from lisp.ui.settings.cue_settings import CueSettingsRegistry
        from lisp.plugins.action_cues.stop_cue import (
            StopCue, StopCueSettings,
        )

        pages = list(CueSettingsRegistry().filter(StopCue))
        assert StopCueSettings in pages, \
            "StopCueSettings not registered for StopCue"
