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
