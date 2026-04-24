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


class TestAutoName:
    """The cue's `name` auto-updates when target_id or action changes
    so the user sees meaningful labels in the cue list without having
    to manually edit the name per-cue."""

    def _setup_target(self, mock_app, name="Sound1"):
        target = MagicMock()
        target.name = name
        mock_app.cue_model.get = lambda cid: (
            target if cid == "t1" else None
        )
        return target

    def test_default_name_before_target_set(self, mock_app):
        """No target → untouched default translation of the class Name."""
        cue = StopCue(app=mock_app)
        assert cue.name == "Fade & Stop"

    def test_name_updates_when_target_set(self, mock_app):
        self._setup_target(mock_app, "Sound1")
        cue = StopCue(app=mock_app)
        cue.target_id = "t1"
        assert cue.name == "Fade and Stop 'Sound1'"

    def test_name_updates_when_action_changed(self, mock_app):
        self._setup_target(mock_app, "Sound1")
        cue = StopCue(app=mock_app)
        cue.target_id = "t1"

        cue.action = CueAction.Pause.value
        assert cue.name == "Fade and Pause 'Sound1'"

        cue.action = CueAction.Interrupt.value
        assert cue.name == "Fade and Interrupt 'Sound1'"

    def test_name_reverts_when_target_cleared(self, mock_app):
        self._setup_target(mock_app, "Sound1")
        cue = StopCue(app=mock_app)
        cue.target_id = "t1"
        assert cue.name.startswith("Fade and Stop")

        cue.target_id = ""
        assert cue.name == "Fade & Stop"

    def test_name_reverts_when_target_missing(self, mock_app):
        """cue_model.get returns None for an unknown target → fallback."""
        mock_app.cue_model.get = lambda _cid: None
        cue = StopCue(app=mock_app)
        cue.target_id = "does-not-exist"
        assert cue.name == "Fade & Stop"

    def test_setting_name_directly_does_not_recurse(self, mock_app):
        """The auto-rename handler must not trigger on its own name
        write — otherwise property_changed → handler → set name →
        property_changed → ... blows the stack."""
        self._setup_target(mock_app, "Sound1")
        cue = StopCue(app=mock_app)
        cue.target_id = "t1"
        # If recursion happened, this would hit the recursion limit.
        cue.name = "manual override"
        assert cue.name == "manual override"

    def test_custom_name_preserved_after_action_change(self, mock_app):
        """Once the user customises the name, further target/action
        changes must not overwrite it."""
        self._setup_target(mock_app, "Sound1")
        cue = StopCue(app=mock_app)
        cue.target_id = "t1"
        cue.name = "My Custom Label"

        cue.action = CueAction.Pause.value

        assert cue.name == "My Custom Label"

    def test_custom_name_survives_session_round_trip(self, mock_app):
        """A saved cue with a user-customised name must reload with
        that name intact — `update_properties` sets target_id and
        action, which would otherwise overwrite the loaded name via
        the auto-derive handler."""
        self._setup_target(mock_app, "Sound1")

        saved = {
            "name": "My Custom Label",
            "target_id": "t1",
            "action": CueAction.Pause.value,
            "duration": 2500,
            "fade_type": "Linear",
        }

        restored = StopCue(app=mock_app)
        restored.update_properties(saved)

        assert restored.name == "My Custom Label"

    def test_auto_name_survives_session_round_trip(self, mock_app):
        """A saved cue whose name IS the auto-derived value must
        reload with auto-management still active — further action
        changes after load should continue to re-derive."""
        self._setup_target(mock_app, "Sound1")

        saved = {
            "name": "Fade and Stop 'Sound1'",
            "target_id": "t1",
            "action": CueAction.Stop.value,
            "duration": 1000,
            "fade_type": "Linear",
        }

        restored = StopCue(app=mock_app)
        restored.update_properties(saved)

        assert restored.name == "Fade and Stop 'Sound1'"

        # Changing action after load should re-derive (auto still on).
        restored.action = CueAction.Pause.value
        assert restored.name == "Fade and Pause 'Sound1'"


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


class TestHibernateAction:
    """Hibernate as a third UI option alongside Stop and Pause."""

    def test_hibernate_sentinel_exists_in_supported_actions(self):
        from lisp.plugins.action_cues.stop_cue import (
            HIBERNATE_ACTION, StopCueSettings,
        )
        assert HIBERNATE_ACTION in StopCueSettings.SupportedActions

    def test_hibernate_sentinel_has_duck_typed_name_value(self):
        from lisp.plugins.action_cues.stop_cue import HIBERNATE_ACTION
        assert HIBERNATE_ACTION.name == "Hibernate"
        assert HIBERNATE_ACTION.value == "Hibernate"

    def test_action_property_accepts_hibernate_value(self, mock_app):
        cue = StopCue(app=mock_app)
        cue.action = "Hibernate"
        assert cue.action == "Hibernate"

    def _setup_target(self, mock_app, name="Sound1"):
        target = MagicMock()
        target.name = name
        mock_app.cue_model.get = lambda cid: (
            target if cid == "t1" else None
        )
        return target

    def test_auto_name_uses_hibernate_verb(self, mock_app):
        self._setup_target(mock_app, "Sound1")
        cue = StopCue(app=mock_app)
        cue.target_id = "t1"
        cue.action = "Hibernate"
        assert cue.name == "Fade and Hibernate 'Sound1'"

    def test_auto_name_switches_between_actions(self, mock_app):
        self._setup_target(mock_app, "Sound1")
        cue = StopCue(app=mock_app)
        cue.target_id = "t1"

        cue.action = CueAction.Pause.value
        assert cue.name == "Fade and Pause 'Sound1'"

        cue.action = "Hibernate"
        assert cue.name == "Fade and Hibernate 'Sound1'"

        cue.action = CueAction.Stop.value
        assert cue.name == "Fade and Stop 'Sound1'"

    def test_hibernate_property_survives_round_trip(self, mock_app):
        cue = StopCue(app=mock_app)
        cue.target_id = "t1"
        cue.action = "Hibernate"
        props = cue.properties()
        assert props["action"] == "Hibernate"


class TestHibernateRuntimeDispatch:
    """StopCue with action=Hibernate fades, then pauses target, then
    flips the Hibernating bit via target._set_hibernated."""

    def _make_target(self, mock_app, state=None):
        from lisp.cues.cue import Cue, CueState
        target = Cue(app=mock_app)
        target.name = "Target"
        target._state = (
            state if state is not None else CueState.Running
        )

        def pause_emit():
            target._state = CueState.Pause
            target.paused.emit(target)

        def routed_execute(action):
            if action == CueAction.Pause:
                pause_emit()
        target.execute = routed_execute

        mock_app.cue_model.get = lambda cid: (
            target if cid == "t1" else None
        )
        # StopCue iterates the model for group children — single-target
        # test: model has just the target itself.
        mock_app.cue_model.__iter__ = lambda self=None: iter([target])
        return target

    def test_hibernate_duration_zero_flips_bit(self, mock_app):
        from lisp.cues.cue import CueState
        target = self._make_target(mock_app)

        cue = StopCue(app=mock_app)
        cue.target_id = "t1"
        cue.action = "Hibernate"
        cue.duration = 0

        cue.__start__()

        assert target._state & CueState.Pause
        assert target._state & CueState.Hibernating

    def test_hibernate_bit_not_set_if_target_already_paused(
        self, mock_app,
    ):
        """Target already Pause → dispatched Pause is a no-op → paused
        never fires → bit stays clear."""
        from lisp.cues.cue import CueState
        target = self._make_target(
            mock_app, state=CueState.Pause,
        )
        target.execute = lambda action: None

        cue = StopCue(app=mock_app)
        cue.target_id = "t1"
        cue.action = "Hibernate"
        cue.duration = 0

        cue.__start__()

        assert not (target._state & CueState.Hibernating)

    def test_hibernate_with_stop_action_does_not_flip_bit(
        self, mock_app,
    ):
        from lisp.cues.cue import CueState
        target = self._make_target(mock_app)

        def stop_emit():
            target._state = CueState.Stop
            target.stopped.emit(target)

        def routed(action):
            if action == CueAction.Stop:
                stop_emit()
        target.execute = routed

        cue = StopCue(app=mock_app)
        cue.target_id = "t1"
        cue.action = CueAction.Stop.value
        cue.duration = 0

        cue.__start__()

        assert not (target._state & CueState.Hibernating)


class TestHibernateGroupCascade:
    """Hibernate on a GroupCue cascades the bit to each child that
    transitions to Pause as part of the cascade."""

    def _make_group_with_children(self, mock_app):
        from lisp.cues.cue import Cue, CueState
        from lisp.plugins.action_cues.group_cue import GroupCue

        # Cue.id is WriteOnceProperty — must be passed to constructor.
        child_a = Cue(app=mock_app, id="a")
        child_a.group_id = "g"
        child_a._state = CueState.Running

        child_b = Cue(app=mock_app, id="b")
        child_b.group_id = "g"
        child_b._state = CueState.Running

        def make_child_exec(cue):
            def routed(action):
                if action == CueAction.Pause:
                    cue._state = CueState.Pause
                    cue.paused.emit(cue)
            return routed

        child_a.execute = make_child_exec(child_a)
        child_b.execute = make_child_exec(child_b)

        group = GroupCue(app=mock_app, id="g")

        def group_exec(action):
            if action == CueAction.Pause:
                for child in (child_a, child_b):
                    child.execute(CueAction.Pause)
                group._state = CueState.Pause
                group.paused.emit(group)
        group.execute = group_exec

        by_id = {"g": group, "a": child_a, "b": child_b}
        mock_app.cue_model.get = lambda cid: by_id.get(cid)
        # StopCue iterates the model to find children via group_id.
        mock_app.cue_model.__iter__ = lambda self=None: iter(
            by_id.values()
        )
        return group, child_a, child_b

    def test_hibernate_group_cascades_bit_to_children(self, mock_app):
        from lisp.cues.cue import CueState
        group, child_a, child_b = self._make_group_with_children(
            mock_app,
        )

        cue = StopCue(app=mock_app)
        cue.target_id = "g"
        cue.action = "Hibernate"
        cue.duration = 0

        cue.__start__()

        assert group._state & CueState.Hibernating
        assert child_a._state & CueState.Hibernating
        assert child_b._state & CueState.Hibernating

    def test_resume_one_child_only_clears_its_own_bit(self, mock_app):
        import threading
        import time
        from lisp.cues.cue import CueState
        group, child_a, child_b = self._make_group_with_children(
            mock_app,
        )

        cue = StopCue(app=mock_app)
        cue.target_id = "g"
        cue.action = "Hibernate"
        cue.duration = 0
        cue.__start__()

        done = threading.Event()

        def on_started(c):
            done.set()
        child_a.started.connect(on_started)

        child_a.resume()
        done.wait(timeout=2.0)
        time.sleep(0.02)

        assert not (child_a._state & CueState.Hibernating)
        assert child_b._state & CueState.Hibernating


class TestHibernateMidFadeAbort:
    """Mid-fade abort with action=Hibernate: the paused-listener
    must be disarmed so the bit is NOT set later, and the target
    cue must be released cleanly from subsequent unrelated pauses."""

    def test_abort_mid_fade_disarms_listener(self, mock_app):
        """Set up a StopCue with action=Hibernate and a real runner;
        abort before the runner completes; assert _hib_handlers is
        cleared."""
        from lisp.cues.cue import Cue, CueState
        target = Cue(app=mock_app, id="t1")
        target._state = CueState.Running
        mock_app.cue_model.get = lambda cid: (
            target if cid == "t1" else None
        )
        mock_app.cue_model.__iter__ = lambda self=None: iter([target])

        cue = StopCue(app=mock_app)
        cue.target_id = "t1"
        cue.action = "Hibernate"
        cue.duration = 500

        # Monkey-patch the runner so _run_fade_then_action sees an
        # aborted fade. This avoids spinning up a real thread.
        class _StubRunner:
            def run_until_complete(self_):
                return False  # aborted

            def abort(self_):
                pass

            def current_time(self_):
                return 0

        # Arm the listener the way __start__ would, then call the
        # fade loop with a stub runner to simulate abort.
        cue._arm_hibernate_listener(target)
        assert cue._hib_handlers is not None

        cue._runner = _StubRunner()
        # _run_fade_then_action is @async_function; drive the body
        # inline by calling the underlying function.
        cue._run_fade_then_action.__wrapped__(cue, target)

        assert cue._hib_handlers is None
        # An unrelated subsequent pause on the target must NOT set
        # the bit.
        target._state = CueState.Pause
        target.paused.emit(target)
        assert not (target._state & CueState.Hibernating)

    def test_rearm_rebuilds_handlers(self, mock_app):
        """Re-arming (e.g. reusing the same StopCue for a second
        hibernate) must disarm any stale handlers with fired=True
        and rebuild from scratch."""
        from lisp.cues.cue import Cue, CueState
        target = Cue(app=mock_app, id="t1")
        mock_app.cue_model.get = lambda cid: (
            target if cid == "t1" else None
        )
        mock_app.cue_model.__iter__ = lambda self=None: iter([target])

        cue = StopCue(app=mock_app)
        cue.target_id = "t1"
        cue.action = "Hibernate"

        # First arm: capture the handler and fire it to set fired=True.
        cue._arm_hibernate_listener(target)
        _old_target, old_handler = cue._hib_handlers[0]
        target._state = CueState.Pause
        target.paused.emit(target)  # handler fires, flips bit
        assert target._state & CueState.Hibernating

        # Clear the bit (simulates the cue having been resumed).
        target._state = CueState.Running

        # Re-arm: must discard the stale handler and build a new one.
        cue._arm_hibernate_listener(target)
        _new_target, new_handler = cue._hib_handlers[0]
        assert new_handler is not old_handler

        # The new handler must fire fresh (fired=[False]).
        target._state = CueState.Pause
        target.paused.emit(target)
        assert target._state & CueState.Hibernating
