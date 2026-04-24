"""Tests for the per-cue `disabled` flag and `effective_disabled`
cascade accessor."""

from unittest.mock import MagicMock

import pytest

from lisp.cues.cue import Cue


def _cue(mock_app, group_id=""):
    cue = Cue(app=mock_app)
    cue.group_id = group_id
    return cue


class TestDisabledProperty:
    def test_default_is_false(self, mock_app):
        cue = _cue(mock_app)
        assert cue.disabled is False

    def test_setting_emits_changed_signal(self, mock_app):
        cue = _cue(mock_app)
        seen = []

        def on_disabled_changed(value):
            seen.append(value)

        cue.changed("disabled").connect(on_disabled_changed)

        cue.disabled = True

        assert seen == [True]

    def test_persists_through_properties_dict(self, mock_app):
        cue = _cue(mock_app)
        cue.disabled = True
        assert cue.properties().get("disabled") is True


class TestEffectiveDisabledCascade:
    def test_own_flag_false_no_parent(self, mock_app):
        mock_app.cue_model = MagicMock()
        mock_app.cue_model.get.return_value = None
        cue = _cue(mock_app)

        assert cue.effective_disabled is False

    def test_own_flag_true(self, mock_app):
        mock_app.cue_model = MagicMock()
        mock_app.cue_model.get.return_value = None
        cue = _cue(mock_app)
        cue.disabled = True

        assert cue.effective_disabled is True

    def test_parent_disabled_child_not(self, mock_app):
        parent = _cue(mock_app)
        parent.disabled = True
        child = _cue(mock_app, group_id=parent.id)

        mock_app.cue_model = MagicMock()
        mock_app.cue_model.get.side_effect = (
            lambda id: parent if id == parent.id else None
        )

        assert child.effective_disabled is True
        assert parent.effective_disabled is True

    def test_grandparent_disabled(self, mock_app):
        grand = _cue(mock_app)
        grand.disabled = True
        parent = _cue(mock_app, group_id=grand.id)
        child = _cue(mock_app, group_id=parent.id)

        lookups = {grand.id: grand, parent.id: parent}
        mock_app.cue_model = MagicMock()
        mock_app.cue_model.get.side_effect = lookups.get

        assert child.effective_disabled is True

    def test_missing_parent_falls_back_to_own_flag(self, mock_app):
        # group_id points at a cue that no longer exists.
        mock_app.cue_model = MagicMock()
        mock_app.cue_model.get.return_value = None
        child = _cue(mock_app, group_id="stale-parent-id")

        assert child.effective_disabled is False
        child.disabled = True
        assert child.effective_disabled is True

    def test_re_enabling_group_preserves_child_flag(self, mock_app):
        parent = _cue(mock_app)
        child = _cue(mock_app, group_id=parent.id)
        child.disabled = True

        mock_app.cue_model = MagicMock()
        mock_app.cue_model.get.side_effect = (
            lambda id: parent if id == parent.id else None
        )

        # Toggle the group on and off; child stays individually disabled.
        parent.disabled = True
        assert child.effective_disabled is True
        parent.disabled = False
        assert child.effective_disabled is True  # own flag still set


from lisp.cues.cue import CueAction, CueState


def _cue_with_mocked_exec(mock_app):
    """Cue with app managers set up so execute won't trip on them."""
    mock_app.exclusive_manager = MagicMock()
    mock_app.exclusive_manager.is_start_blocked.return_value = False
    mock_app.video_exclusive_manager = MagicMock()
    mock_app.video_exclusive_manager.is_start_blocked.return_value = False
    mock_app.cue_model = MagicMock()
    mock_app.cue_model.get.return_value = None

    cue = Cue(app=mock_app)
    # Give the cue every action so the test isn't rejected by
    # `if action in self.CueActions` — we only want to verify the
    # disable gate, not the action-support matrix.
    cue.CueActions = tuple(CueAction)
    return cue


class TestDisabledExecuteGate:
    @pytest.mark.parametrize("action", [
        CueAction.Start,
        CueAction.FadeInStart,
        CueAction.Resume,
        CueAction.FadeInResume,
    ])
    def test_start_actions_return_false_when_disabled(
        self, mock_app, action,
    ):
        cue = _cue_with_mocked_exec(mock_app)
        cue.disabled = True
        if action in (CueAction.Resume, CueAction.FadeInResume):
            cue._state = CueState.Pause  # so `would_transition` is True

        # Spy on start/resume so we can assert they never ran.
        cue.start = MagicMock()
        cue.resume = MagicMock()

        result = cue.execute(action)

        assert result is False
        cue.start.assert_not_called()
        cue.resume.assert_not_called()

    @pytest.mark.parametrize("action", [
        CueAction.Stop,
        CueAction.FadeOutStop,
        CueAction.Pause,
        CueAction.FadeOutPause,
        CueAction.Interrupt,
        CueAction.FadeOutInterrupt,
    ])
    def test_stop_actions_proceed_when_disabled(
        self, mock_app, action,
    ):
        cue = _cue_with_mocked_exec(mock_app)
        cue.disabled = True
        cue._state = CueState.Running  # stop/pause not a no-op here

        cue.stop = MagicMock()
        cue.pause = MagicMock()
        cue.interrupt = MagicMock()

        cue.execute(action)

        calls = (
            cue.stop.called + cue.pause.called + cue.interrupt.called
        )
        assert calls == 1

    def test_default_action_blocked_when_disabled_and_stopped(
        self, mock_app,
    ):
        # Default on a stopped cue -> default_start_action -> Start.
        cue = _cue_with_mocked_exec(mock_app)
        cue.disabled = True
        cue.start = MagicMock()

        result = cue.execute(CueAction.Default)

        assert result is False
        cue.start.assert_not_called()

    def test_default_action_allowed_when_disabled_and_running(
        self, mock_app,
    ):
        # Default on a running cue -> default_stop_action -> Stop.
        cue = _cue_with_mocked_exec(mock_app)
        cue.disabled = True
        cue._state = CueState.Running
        cue.stop = MagicMock()

        cue.execute(CueAction.Default)

        cue.stop.assert_called_once()

    def test_child_of_disabled_group_blocked(self, mock_app):
        parent = Cue(app=mock_app)
        parent.disabled = True
        child = _cue_with_mocked_exec(mock_app)
        child.group_id = parent.id
        mock_app.cue_model.get.side_effect = (
            lambda id: parent if id == parent.id else None
        )
        child.start = MagicMock()

        result = child.execute(CueAction.Start)

        assert result is False
        child.start.assert_not_called()
