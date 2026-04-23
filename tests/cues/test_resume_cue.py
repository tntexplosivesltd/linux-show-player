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


class TestPausedHappyPath:
    def _build_paused_media(self, mock_app, with_alpha=False):
        """Mock a paused MediaCue with volume (and optionally alpha) faders."""
        volume_fader = MagicMock(name="volume_fader")
        volume_fader.target = MagicMock()
        volume_fader.attribute = "live_volume"

        volume_el = MagicMock(name="volume_el")
        volume_el.get_fader.return_value = volume_fader

        alpha_fader = None
        alpha_el = None
        if with_alpha:
            alpha_fader = MagicMock(name="alpha_fader")
            alpha_fader.target = MagicMock()
            alpha_fader.attribute = "live_alpha"

            alpha_el = MagicMock(name="alpha_el")
            alpha_el.get_fader.return_value = alpha_fader

        target = MagicMock(spec=MediaCue)
        target.id = "t1"
        target.state = CueState.Pause
        target.media = MagicMock()
        target.media.element = lambda n: {
            "Volume": volume_el, "VideoAlpha": alpha_el,
        }.get(n)
        mock_app.cue_model.get.return_value = target

        return target, volume_fader, alpha_fader

    def test_paused_zero_then_resume_then_fade(self, mock_app, monkeypatch):
        """Happy path: zero live_volume, dispatch Resume, start runner."""
        target, vol_fader, _ = self._build_paused_media(mock_app)

        fake_runner = MagicMock()
        fake_runner.run_until_complete.return_value = True
        runner_cls = MagicMock()

        call_order = []

        def fake_rsetattr(obj, attr, value):
            call_order.append(("zero", obj, attr, value))
        monkeypatch.setattr(
            "lisp.plugins.action_cues.resume_cue.rsetattr", fake_rsetattr,
        )

        def fake_execute(action):
            call_order.append(("resume", action))
        target.execute.side_effect = fake_execute

        def fake_runner_init(*args, **kwargs):
            call_order.append(("runner_built",))
            return fake_runner
        runner_cls.side_effect = fake_runner_init
        monkeypatch.setattr(
            "lisp.plugins.action_cues.resume_cue.ParallelFadeRunner",
            runner_cls,
        )
        _patch_async_function_synchronous(monkeypatch)

        cue = ResumeCue(app=mock_app)
        cue.target_id = target.id
        cue.duration = 500

        result = cue.__start__()

        assert result is True
        # Zero was called before resume, resume before runner construction.
        kinds = [c[0] for c in call_order]
        assert kinds == ["zero", "resume", "runner_built"], kinds
        zero_call = call_order[0]
        assert zero_call[1] is vol_fader.target
        assert zero_call[2] == "live_volume"
        assert zero_call[3] == 0.0
        assert call_order[1] == ("resume", CueAction.Resume)
        fake_runner.run_until_complete.assert_called_once()

    def test_paused_zeros_both_volume_and_alpha(self, mock_app, monkeypatch):
        """VideoAlpha and Volume both zeroed when present."""
        target, vol_fader, alpha_fader = self._build_paused_media(
            mock_app, with_alpha=True,
        )

        fake_runner = MagicMock()
        fake_runner.run_until_complete.return_value = True
        monkeypatch.setattr(
            "lisp.plugins.action_cues.resume_cue.ParallelFadeRunner",
            MagicMock(return_value=fake_runner),
        )
        _patch_async_function_synchronous(monkeypatch)

        zero_calls = []

        def record_zero(obj, attr, val):
            zero_calls.append((obj, attr, val))
        monkeypatch.setattr(
            "lisp.plugins.action_cues.resume_cue.rsetattr", record_zero,
        )

        cue = ResumeCue(app=mock_app)
        cue.target_id = target.id
        cue.duration = 500

        cue.__start__()

        assert len(zero_calls) == 2
        targets = [c[0] for c in zero_calls]
        attrs = [c[1] for c in zero_calls]
        vals = [c[2] for c in zero_calls]
        assert vol_fader.target in targets
        assert alpha_fader.target in targets
        assert set(attrs) == {"live_volume", "live_alpha"}
        assert vals == [0.0, 0.0]

    def test_paused_runner_targets_1_0_with_fade_in_curve(self, mock_app,
                                                         monkeypatch):
        """Runner is built with to_value=1.0 and FadeInType from property."""
        target, _, _ = self._build_paused_media(mock_app)

        runner_cls = MagicMock()
        fake_runner = MagicMock()
        fake_runner.run_until_complete.return_value = True
        runner_cls.return_value = fake_runner
        monkeypatch.setattr(
            "lisp.plugins.action_cues.resume_cue.ParallelFadeRunner",
            runner_cls,
        )
        _patch_async_function_synchronous(monkeypatch)

        def noop_rsetattr(*a, **kw):
            pass
        monkeypatch.setattr(
            "lisp.plugins.action_cues.resume_cue.rsetattr", noop_rsetattr,
        )

        cue = ResumeCue(app=mock_app)
        cue.target_id = target.id
        cue.duration = 1500
        cue.fade_type = "Quadratic"

        cue.__start__()

        runner_cls.assert_called_once()
        kwargs = runner_cls.call_args.kwargs
        assert kwargs["to_value"] == 1.0
        assert kwargs["curve"] == FadeInType.Quadratic
        assert kwargs["duration_seconds"] == 1.5

    def test_paused_group_cascade_single_resume_dispatch(self, mock_app,
                                                        monkeypatch):
        """GroupCue target: Resume dispatched once on the group, not per child."""
        from lisp.plugins.action_cues.group_cue import GroupCue

        def _make_child(cid):
            vol_fader = MagicMock()
            vol_fader.target = MagicMock()
            vol_fader.attribute = "live_volume"
            vol_el = MagicMock()
            vol_el.get_fader.return_value = vol_fader
            child = MagicMock(spec=MediaCue)
            child.id = cid
            child.state = CueState.Pause
            child.media = MagicMock()
            child.media.element = lambda n: vol_el if n == "Volume" else None
            return child, vol_fader

        child_a, _ = _make_child("a")
        child_b, _ = _make_child("b")

        group = MagicMock(spec=GroupCue)
        group.id = "g"
        group.state = CueState.Pause
        group._resolve_children.return_value = [child_a, child_b]
        mock_app.cue_model.get.return_value = group

        fake_runner = MagicMock()
        fake_runner.run_until_complete.return_value = True
        monkeypatch.setattr(
            "lisp.plugins.action_cues.resume_cue.ParallelFadeRunner",
            MagicMock(return_value=fake_runner),
        )
        _patch_async_function_synchronous(monkeypatch)

        def noop_rsetattr(*a, **kw):
            pass
        monkeypatch.setattr(
            "lisp.plugins.action_cues.resume_cue.rsetattr", noop_rsetattr,
        )

        cue = ResumeCue(app=mock_app)
        cue.target_id = group.id
        cue.duration = 500

        cue.__start__()

        group.execute.assert_called_once_with(CueAction.Resume)
        child_a.execute.assert_not_called()
        child_b.execute.assert_not_called()

    def test_paused_no_faders_dispatches_resume_without_fade(self, mock_app):
        """Non-media or no-volume paused target: Resume dispatched, no fade."""
        target = MagicMock(spec=MediaCue)
        target.id = "t1"
        target.state = CueState.Pause
        target.media = MagicMock()
        target.media.element.return_value = None
        mock_app.cue_model.get.return_value = target

        cue = ResumeCue(app=mock_app)
        cue.target_id = target.id
        cue.duration = 500

        result = cue.__start__()

        target.execute.assert_called_once_with(CueAction.Resume)
        assert result is False  # no async work scheduled


class TestPausedDurationZero:
    def test_paused_duration_zero_skips_zero_step(self, mock_app, monkeypatch):
        """duration=0 on a paused target: no zero step (otherwise silent cue)."""
        volume_fader = MagicMock()
        volume_fader.target = MagicMock()
        volume_fader.attribute = "live_volume"

        volume_el = MagicMock()
        volume_el.get_fader.return_value = volume_fader

        target = MagicMock(spec=MediaCue)
        target.id = "t1"
        target.state = CueState.Pause
        target.media = MagicMock()
        target.media.element = lambda n: volume_el if n == "Volume" else None
        mock_app.cue_model.get.return_value = target

        zero_calls = []

        def record_zero(obj, attr, val):
            zero_calls.append((obj, attr, val))
        monkeypatch.setattr(
            "lisp.plugins.action_cues.resume_cue.rsetattr", record_zero,
        )

        cue = ResumeCue(app=mock_app)
        cue.target_id = target.id
        cue.duration = 0

        result = cue.__start__()

        # Zero step skipped — target resumes at its existing live_volume.
        assert zero_calls == []
        # Resume still dispatched.
        target.execute.assert_called_once_with(CueAction.Resume)
        # No async work.
        assert result is False


class TestAbort:
    def test_stop_aborts_runner_when_present(self, mock_app):
        cue = ResumeCue(app=mock_app)
        cue._runner = MagicMock()

        result = cue.__stop__()

        cue._runner.abort.assert_called_once()
        assert result is True

    def test_interrupt_aborts_runner_when_present(self, mock_app):
        cue = ResumeCue(app=mock_app)
        runner = MagicMock()
        cue._runner = runner

        cue.__interrupt__()

        runner.abort.assert_called_once()

    def test_stop_without_runner_is_safe(self, mock_app):
        """No in-flight fade: __stop__ must not crash."""
        cue = ResumeCue(app=mock_app)
        assert cue._runner is None
        assert cue.__stop__() is True


import pytest


class TestResumeCueSettings:
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

        Monkeypatching Application is critical: the real singleton
        registers base General/Timing pages in CueSettingsRegistry as
        a side-effect of construction, polluting other tests (bit me
        in Part 1)."""
        from lisp.plugins.action_cues.resume_cue import ResumeCueSettings

        monkeypatch.setattr(
            "lisp.plugins.action_cues.resume_cue.Application",
            lambda: MagicMock(cue_model=MagicMock(
                get=lambda _id: None, filter=lambda *_: [],
            )),
        )

        page = ResumeCueSettings()
        page.enableCheck(True)
        assert page.getSettings() == {}

    def test_load_then_get_round_trip(self, qapp, monkeypatch):
        from lisp.plugins.action_cues.resume_cue import ResumeCueSettings

        fake_target = MagicMock()
        fake_target.name = "Target Cue"
        monkeypatch.setattr(
            "lisp.plugins.action_cues.resume_cue.Application",
            lambda: MagicMock(cue_model=MagicMock(
                get=lambda _id: fake_target, filter=lambda *_: [],
            )),
        )

        page = ResumeCueSettings()
        # Default state: groups NOT checkable → isGroupEnabled returns True,
        # so getSettings reads every group. Single-cue dialog flow.
        page.loadSettings({
            "target_id": "abc",
            "duration": 2500,
            "fade_type": "Linear",
        })

        settings = page.getSettings()
        assert settings["target_id"] == "abc"
        assert settings["duration"] == 2500
        assert settings["fade_type"] == "Linear"

    def test_no_action_key_in_settings(self, qapp, monkeypatch):
        """ResumeCueSettings never stores an `action` key — verb is fixed."""
        from lisp.plugins.action_cues.resume_cue import ResumeCueSettings

        monkeypatch.setattr(
            "lisp.plugins.action_cues.resume_cue.Application",
            lambda: MagicMock(cue_model=MagicMock(
                get=lambda _id: None, filter=lambda *_: [],
            )),
        )

        page = ResumeCueSettings()
        settings = page.getSettings()
        assert "action" not in settings

    def test_registry_association(self):
        from lisp.ui.settings.cue_settings import CueSettingsRegistry
        from lisp.plugins.action_cues.resume_cue import (
            ResumeCue, ResumeCueSettings,
        )

        pages = list(CueSettingsRegistry().filter(ResumeCue))
        assert ResumeCueSettings in pages, (
            "ResumeCueSettings not registered for ResumeCue"
        )
