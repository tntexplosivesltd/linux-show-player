# This file is part of Linux Show Player
#
# Copyright 2016 Francesco Ceruti <ceppofrancy@gmail.com>
#
# Linux Show Player is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# Linux Show Player is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Linux Show Player.  If not, see <http://www.gnu.org/licenses/>.

from unittest.mock import MagicMock

import pytest

from lisp.cues.pre_arm_manager import PreArmManager, ArmReason
from lisp.ui.widgets.notification import NotificationLevel


def _config_returner(overrides=None):
    """Build a side_effect for app.conf.get(key, default) that returns
    overrides where provided and falls through to defaults.
    """
    overrides = overrides or {}

    def _get(key, default=None):
        if key in overrides:
            return overrides[key]
        defaults = {
            "preArm.enabled": True,
            "preArm.lookahead": 1,
            "preArm.maxArmed": 16,
            "preArm.failOnCapHit": False,
        }
        return defaults.get(key, default)

    return _get


def _make_cue(cue_id, preload=False, media_type="Audio", is_group=False):
    cue = MagicMock()
    cue.id = cue_id
    cue.preload = preload
    cue.media = MagicMock()
    # MediaType lives on the first pipeline element (UriInput etc.), not on
    # the media object itself — mirror the real GstMedia attribute layout.
    input_element = MagicMock()
    input_element.MediaType = media_type
    cue.media.elements = [input_element]
    cue.media.prearm.return_value = True
    cue.media.disarm = MagicMock()
    cue.media.reseek = MagicMock()
    type(cue).__name__ = "GroupCue" if is_group else "MediaCue"
    return cue


@pytest.fixture
def manager_factory(mock_app):
    """Yields a function that builds a manager with optional config
    overrides."""

    def _build(overrides=None):
        mock_app.conf = MagicMock()
        mock_app.conf.get.side_effect = _config_returner(overrides)
        # Provide signal-shaped attributes for __init__ wiring.
        # Tests that need real Signal behavior can set these later.
        mock_app.session_loaded = MagicMock()
        mock_app.cue_model = MagicMock()
        mock_app.cue_model.item_added = MagicMock()
        mock_app.cue_model.item_removed = MagicMock()
        mock_app.layout = MagicMock()
        mock_app.layout.standby_changed = MagicMock()
        mock_app.layout.cue_executed = MagicMock()
        return PreArmManager(mock_app)

    return _build


@pytest.fixture
def manager(manager_factory):
    return manager_factory()


# --- Basic arm/disarm ---------------------------------------------------

def test_arm_under_cap(manager):
    cue = _make_cue("c1")
    assert manager._try_arm(cue, ArmReason.Auto) is True
    assert "c1" in manager._armed
    cue.media.prearm.assert_called_once()


def test_arm_returns_false_for_ineligible(manager):
    cue = _make_cue("g1", is_group=True)
    assert manager._try_arm(cue, ArmReason.Auto) is False
    assert "g1" not in manager._armed


def test_arm_returns_false_for_av_media(manager):
    cue = _make_cue("v1", media_type="AudioAndVideo")
    assert manager._try_arm(cue, ArmReason.Auto) is False
    assert "v1" not in manager._armed


def test_disarm_clears_state(manager):
    cue = _make_cue("c1")
    manager._try_arm(cue, ArmReason.Auto)
    manager._disarm(cue)
    assert "c1" not in manager._armed
    cue.media.disarm.assert_called_once()


def test_disarm_idempotent_when_not_armed(manager):
    cue = _make_cue("c1")
    manager._disarm(cue)  # no exception
    assert "c1" not in manager._armed
    cue.media.disarm.assert_not_called()


# --- Cap enforcement ---------------------------------------------------

def test_cap_refuses_beyond_limit(manager_factory):
    manager = manager_factory({"preArm.maxArmed": 2})
    cues = [_make_cue(f"c{i}", preload=True) for i in range(3)]
    assert manager._try_arm(cues[0], ArmReason.Preload) is True
    assert manager._try_arm(cues[1], ArmReason.Preload) is True
    assert manager._try_arm(cues[2], ArmReason.Preload) is False
    assert len(manager._armed) == 2


def test_cap_refusal_silent_by_default(manager_factory):
    """Cap refusal does NOT record a failure unless failOnCapHit=True."""
    manager = manager_factory({"preArm.maxArmed": 1})
    cue1 = _make_cue("c1", preload=True)
    cue2 = _make_cue("c2", preload=True)
    manager._try_arm(cue1, ArmReason.Preload)
    manager._try_arm(cue2, ArmReason.Preload)
    assert "c2" not in manager._failed


def test_cap_refusal_records_failure_when_failOnCapHit(manager_factory):
    manager = manager_factory({
        "preArm.maxArmed": 1, "preArm.failOnCapHit": True,
    })
    cue1 = _make_cue("c1", preload=True)
    cue2 = _make_cue("c2", preload=True)
    manager._try_arm(cue1, ArmReason.Preload)
    manager._try_arm(cue2, ArmReason.Preload)
    assert "c2" in manager._failed
    assert "cap" in manager._failed["c2"].lower()


# --- ArmReason flag composition ----------------------------------------

def test_arm_reason_or_merges(manager):
    cue = _make_cue("c1")
    manager._try_arm(cue, ArmReason.Auto)
    assert manager._armed["c1"] == ArmReason.Auto
    # Adding the same reason is a no-op
    manager._try_arm(cue, ArmReason.Auto)
    assert manager._armed["c1"] == ArmReason.Auto
    # Adding a different reason OR-merges
    manager._add_reason(cue, ArmReason.Preload)
    assert manager._armed["c1"] == ArmReason.Auto | ArmReason.Preload


def test_remove_reason_downgrades(manager):
    cue = _make_cue("c1")
    manager._try_arm(cue, ArmReason.Auto | ArmReason.Preload)
    manager._remove_reason(cue, ArmReason.Auto)
    assert manager._armed["c1"] == ArmReason.Preload
    cue.media.disarm.assert_not_called()


def test_remove_last_reason_disarms(manager):
    cue = _make_cue("c1")
    manager._try_arm(cue, ArmReason.Preload)
    manager._remove_reason(cue, ArmReason.Preload)
    assert "c1" not in manager._armed
    cue.media.disarm.assert_called_once()


# --- Failure recording -------------------------------------------------

def test_failure_recorded_only_for_preload(manager):
    cue_auto = _make_cue("a1", preload=False)
    cue_auto.media.prearm.return_value = False
    cue_preload = _make_cue("p1", preload=True)
    cue_preload.media.prearm.return_value = False

    manager._try_arm(cue_auto, ArmReason.Auto)
    manager._try_arm(cue_preload, ArmReason.Preload)

    assert "a1" not in manager._failed
    assert "p1" in manager._failed


# --- Signal -------------------------------------------------------------

def test_armed_set_changed_emits(manager):
    cue = _make_cue("c1")
    received = []

    def _handler():
        received.append(True)

    manager.armed_set_changed.connect(_handler)
    manager._try_arm(cue, ArmReason.Auto)
    manager._disarm(cue)
    assert len(received) == 2  # one for arm, one for disarm


# --- Disabled ---------------------------------------------------------

def test_disabled_manager_refuses(manager_factory):
    manager = manager_factory({"preArm.enabled": False})
    cue = _make_cue("c1")
    assert manager._try_arm(cue, ArmReason.Auto) is False
    assert "c1" not in manager._armed


# T8 tests --------------------------------------------------------------

def test_session_loaded_arms_preload_cues(manager, mock_app):
    cues = [
        _make_cue("c1", preload=True),
        _make_cue("c2", preload=False),
        _make_cue("c3", preload=True),
    ]
    mock_app.cue_model = MagicMock()
    mock_app.cue_model.__iter__ = lambda self: iter(cues)
    mock_app.layout = MagicMock()
    mock_app.layout.standby_cue.return_value = None

    manager.session_loaded()

    assert "c1" in manager._armed
    assert "c2" not in manager._armed
    assert "c3" in manager._armed
    assert manager._armed["c1"] == ArmReason.Preload


def test_session_loaded_arms_standby(manager, mock_app):
    standby_cue = _make_cue("s1")
    mock_app.cue_model = MagicMock()
    mock_app.cue_model.__iter__ = lambda self: iter([])
    mock_app.layout = MagicMock()
    mock_app.layout.standby_cue.return_value = standby_cue

    manager.session_loaded()

    assert "s1" in manager._armed
    assert manager._armed["s1"] == ArmReason.Auto


def test_session_loaded_preload_priority_over_auto(manager_factory, mock_app):
    manager = manager_factory({"preArm.maxArmed": 1})
    preload_cue = _make_cue("p", preload=True)
    standby_cue = _make_cue("s")
    mock_app.cue_model = MagicMock()
    mock_app.cue_model.__iter__ = lambda self: iter([preload_cue])
    mock_app.layout = MagicMock()
    mock_app.layout.standby_cue.return_value = standby_cue

    manager.session_loaded()

    assert "p" in manager._armed
    assert "s" not in manager._armed


def test_session_loaded_disabled_manager_noop(manager_factory, mock_app):
    manager = manager_factory({"preArm.enabled": False})
    preload_cue = _make_cue("p", preload=True)
    mock_app.cue_model = MagicMock()
    mock_app.cue_model.__iter__ = lambda self: iter([preload_cue])
    mock_app.layout = MagicMock()
    mock_app.layout.standby_cue.return_value = None

    manager.session_loaded()

    assert "p" not in manager._armed


# T9 tests --------------------------------------------------------------

def test_standby_changed_arms_new_disarms_old(manager, mock_app):
    cue1 = _make_cue("c1")
    cue2 = _make_cue("c2")
    mock_app.cue_model = MagicMock()
    mock_app.cue_model.get.side_effect = lambda cue_id: {
        "c1": cue1, "c2": cue2,
    }.get(cue_id)

    manager.standby_changed(cue1)
    assert "c1" in manager._armed
    manager.standby_changed(cue2)
    assert "c1" not in manager._armed
    assert "c2" in manager._armed
    assert manager._armed["c2"] == ArmReason.Auto


def test_standby_changed_to_none_disarms_auto(manager, mock_app):
    cue1 = _make_cue("c1")
    mock_app.cue_model = MagicMock()
    mock_app.cue_model.get.side_effect = lambda cue_id: {"c1": cue1}.get(cue_id)
    manager.standby_changed(cue1)
    assert "c1" in manager._armed
    manager.standby_changed(None)
    assert "c1" not in manager._armed


def test_standby_changed_preserves_preload_when_moving_away(manager, mock_app):
    cue1 = _make_cue("c1", preload=True)
    cue2 = _make_cue("c2")
    mock_app.cue_model = MagicMock()
    mock_app.cue_model.get.side_effect = lambda cue_id: {
        "c1": cue1, "c2": cue2,
    }.get(cue_id)

    # Step 1: arm cue1 as preload
    manager._try_arm(cue1, ArmReason.Preload)
    # Step 2: standby moves onto cue1 → should add Auto reason
    manager.standby_changed(cue1)
    assert manager._armed["c1"] == ArmReason.Auto | ArmReason.Preload
    # Step 3: standby moves to cue2 → cue1 keeps Preload, cue2 gets Auto
    manager.standby_changed(cue2)
    assert manager._armed["c1"] == ArmReason.Preload
    assert manager._armed["c2"] == ArmReason.Auto


def test_standby_changed_skips_groupcue(manager, mock_app):
    group = _make_cue("g1", is_group=True)
    mock_app.cue_model = MagicMock()
    mock_app.cue_model.get.side_effect = lambda cue_id: {"g1": group}.get(cue_id)
    manager.standby_changed(group)
    assert "g1" not in manager._armed


# T10 tests -------------------------------------------------------------

def test_cue_executed_removes_from_armed(manager):
    cue = _make_cue("c1")
    manager._try_arm(cue, ArmReason.Auto)
    manager.cue_executed(cue)
    assert "c1" not in manager._armed


def test_cue_executed_does_not_call_media_disarm(manager):
    """Cue is already in Playing state; no need to call media.disarm
    (the play() flow already cleared the arm flag).
    """
    cue = _make_cue("c1")
    manager._try_arm(cue, ArmReason.Auto)
    cue.media.disarm.reset_mock()
    manager.cue_executed(cue)
    cue.media.disarm.assert_not_called()


def test_cue_executed_idempotent_when_not_armed(manager):
    """GO fires on every cue, including those that were never armed
    (ineligible, cap-refused, prearm-failed). cue_executed must be a
    safe no-op in that case — no signal emission, no exceptions.
    """
    cue = _make_cue("c1")
    received = []

    def _handler():
        received.append(True)

    manager.armed_set_changed.connect(_handler)
    manager.cue_executed(cue)
    assert "c1" not in manager._armed
    assert received == []
    cue.media.disarm.assert_not_called()


def test_cue_stopped_rearms_if_preload(manager):
    cue = _make_cue("c1", preload=True)
    manager._try_arm(cue, ArmReason.Preload)
    manager.cue_executed(cue)
    assert "c1" not in manager._armed
    manager.on_cue_stopped(cue)
    assert "c1" in manager._armed
    assert manager._armed["c1"] == ArmReason.Preload


def test_cue_stopped_does_not_rearm_if_not_preload(manager):
    cue = _make_cue("c1", preload=False)
    manager._try_arm(cue, ArmReason.Auto)
    manager.cue_executed(cue)
    manager.on_cue_stopped(cue)
    assert "c1" not in manager._armed


# T11 tests --------------------------------------------------------------

def test_uri_change_rearms_when_armed(manager):
    cue = _make_cue("c1", preload=True)
    manager._try_arm(cue, ArmReason.Preload)
    cue.media.disarm.reset_mock()
    cue.media.prearm.reset_mock()
    manager.on_uri_changed(cue)
    cue.media.disarm.assert_called_once()
    cue.media.prearm.assert_called_once()
    assert "c1" in manager._armed


def test_uri_change_noop_when_not_armed(manager):
    cue = _make_cue("c1")
    manager.on_uri_changed(cue)
    cue.media.disarm.assert_not_called()
    cue.media.prearm.assert_not_called()


def test_start_time_change_reseeks_when_armed(manager):
    cue = _make_cue("c1", preload=True)
    cue.start_time = 1000
    manager._try_arm(cue, ArmReason.Preload)
    cue.start_time = 2000
    manager.on_start_time_changed(cue)
    cue.media.reseek.assert_called_with(2000)


def test_start_time_change_noop_when_not_armed(manager):
    cue = _make_cue("c1")
    cue.start_time = 1000
    manager.on_start_time_changed(cue)
    cue.media.reseek.assert_not_called()


def test_preload_toggled_true_arms(manager):
    cue = _make_cue("c1", preload=False)
    manager.on_preload_changed(cue, True)
    assert "c1" in manager._armed
    assert ArmReason.Preload in manager._armed["c1"]


def test_preload_toggled_false_disarms_preload_only(manager):
    cue = _make_cue("c1", preload=True)
    manager._try_arm(cue, ArmReason.Preload)
    manager.on_preload_changed(cue, False)
    assert "c1" not in manager._armed


def test_preload_toggled_false_downgrades_when_also_auto(manager):
    cue = _make_cue("c1", preload=True)
    manager._try_arm(cue, ArmReason.Preload)
    manager._add_reason(cue, ArmReason.Auto)
    manager.on_preload_changed(cue, False)
    assert "c1" in manager._armed
    assert manager._armed["c1"] == ArmReason.Auto


# T12 tests --------------------------------------------------------------

def test_cue_added_arms_if_preload(manager):
    cue = _make_cue("c1", preload=True)
    manager.cue_added(cue)
    assert "c1" in manager._armed


def test_cue_added_does_not_arm_if_not_preload(manager):
    cue = _make_cue("c1", preload=False)
    manager.cue_added(cue)
    assert "c1" not in manager._armed


def test_cue_added_skips_groupcue(manager):
    group = _make_cue("g1", preload=True, is_group=True)
    manager.cue_added(group)
    assert "g1" not in manager._armed


def test_cue_removed_disarms(manager):
    cue = _make_cue("c1")
    manager._try_arm(cue, ArmReason.Auto)
    manager.cue_removed(cue)
    assert "c1" not in manager._armed
    cue.media.disarm.assert_called_once()


def test_cue_removed_clears_failure_record(manager):
    cue = _make_cue("c1", preload=True)
    cue.media.prearm.return_value = False
    manager._try_arm(cue, ArmReason.Preload)
    assert "c1" in manager._failed
    manager.cue_removed(cue)
    assert "c1" not in manager._failed


def test_mtime_change_triggers_rearm_on_visit(manager):
    cue = _make_cue("c1", preload=True)
    cue.media.input_uri.return_value = MagicMock(
        is_local=True, absolute_path="/tmp/fake.wav",
    )
    # Stub _cue_mtime: arm captures 100.0, check sees 200.0 (triggers
    # re-arm), re-arm captures 200.0.
    times = iter([100.0, 200.0, 200.0])
    manager._cue_mtime = lambda c: next(times)
    manager._try_arm(cue, ArmReason.Preload)
    cue.media.disarm.reset_mock()
    cue.media.prearm.reset_mock()
    manager.maybe_rearm_for_mtime(cue)
    cue.media.disarm.assert_called_once()
    cue.media.prearm.assert_called_once()


def test_mtime_no_change_does_not_rearm(manager):
    cue = _make_cue("c1", preload=True)
    cue.media.input_uri.return_value = MagicMock(
        is_local=True, absolute_path="/tmp/fake.wav",
    )
    # Same mtime every call
    manager._cue_mtime = lambda c: 100.0
    manager._try_arm(cue, ArmReason.Preload)
    cue.media.disarm.reset_mock()
    cue.media.prearm.reset_mock()
    manager.maybe_rearm_for_mtime(cue)
    cue.media.disarm.assert_not_called()
    cue.media.prearm.assert_not_called()


def test_mtime_check_noop_when_not_armed(manager):
    cue = _make_cue("c1")
    manager._cue_mtime = lambda c: 100.0
    manager.maybe_rearm_for_mtime(cue)  # not in _armed
    cue.media.disarm.assert_not_called()


# T13 tests --------------------------------------------------------------

def test_single_preload_failure_emits_per_cue_toast(manager, mock_app):
    """A single preload failure during session_load emits a per-cue toast."""
    cue = _make_cue("c1", preload=True)
    cue.name = "Opening Music"
    cue.media.prearm.return_value = False
    mock_app.cue_model = MagicMock()
    mock_app.cue_model.__iter__ = lambda self: iter([cue])
    mock_app.layout = MagicMock()
    mock_app.layout.standby_cue.return_value = None

    manager.session_loaded()

    assert mock_app.notify.emit.call_count == 1
    args, _ = mock_app.notify.emit.call_args
    assert "Opening Music" in args[0]
    assert args[1] == NotificationLevel.Warning


def test_multiple_preload_failures_emit_summary(manager, mock_app):
    """>=2 failures during session_load coalesce into one summary toast."""
    cues = [_make_cue(f"c{i}", preload=True) for i in range(3)]
    for c in cues:
        c.name = f"Cue {c.id}"
        c.media.prearm.return_value = False
    mock_app.cue_model = MagicMock()
    mock_app.cue_model.__iter__ = lambda self: iter(cues)
    mock_app.layout = MagicMock()
    mock_app.layout.standby_cue.return_value = None

    manager.session_loaded()

    assert mock_app.notify.emit.call_count == 1
    args, _ = mock_app.notify.emit.call_args
    assert "3" in args[0]
    assert "preload" in args[0].lower()
    assert args[1] == NotificationLevel.Warning


def test_auto_only_failure_emits_no_toast(manager, mock_app):
    """A standby cue that fails to arm does NOT emit a toast."""
    cue = _make_cue("c1", preload=False)
    cue.media.prearm.return_value = False
    mock_app.cue_model = MagicMock()
    mock_app.cue_model.__iter__ = lambda self: iter([])
    mock_app.layout = MagicMock()
    mock_app.layout.standby_cue.return_value = cue

    manager.session_loaded()

    mock_app.notify.emit.assert_not_called()


def test_midshow_preload_failure_emits_direct_toast(manager, mock_app):
    """A failure outside session_load emits a per-cue toast immediately."""
    cue = _make_cue("c1", preload=True)
    cue.name = "Sting 3"
    cue.media.prearm.return_value = False

    # Direct mid-show arm attempt (NOT inside session_loaded)
    manager._try_arm(cue, ArmReason.Preload)

    assert mock_app.notify.emit.call_count == 1
    args, _ = mock_app.notify.emit.call_args
    assert "Sting 3" in args[0]
    assert args[1] == NotificationLevel.Warning


def test_cap_refusal_silent_when_failOnCapHit_false(manager_factory, mock_app):
    """Cap refusal with default failOnCapHit=False: no toast."""
    manager = manager_factory({"preArm.maxArmed": 1})
    cue1 = _make_cue("c1", preload=True)
    cue1.name = "First"
    cue2 = _make_cue("c2", preload=True)
    cue2.name = "Second"

    manager._try_arm(cue1, ArmReason.Preload)  # arms successfully
    mock_app.notify.emit.reset_mock()
    manager._try_arm(cue2, ArmReason.Preload)  # cap-refused

    mock_app.notify.emit.assert_not_called()


def test_cap_refusal_emits_toast_when_failOnCapHit_true(
    manager_factory, mock_app
):
    """Cap refusal with failOnCapHit=True AND preload=True: toast fires."""
    manager = manager_factory({
        "preArm.maxArmed": 1, "preArm.failOnCapHit": True,
    })
    cue1 = _make_cue("c1", preload=True)
    cue2 = _make_cue("c2", preload=True)
    cue2.name = "Cap Hit Cue"

    manager._try_arm(cue1, ArmReason.Preload)
    mock_app.notify.emit.reset_mock()
    manager._try_arm(cue2, ArmReason.Preload)

    assert mock_app.notify.emit.call_count == 1
    args, _ = mock_app.notify.emit.call_args
    assert "Cap Hit Cue" in args[0]
    assert args[1] == NotificationLevel.Warning


def test_midshow_preload_failure_uses_id_when_name_missing(manager, mock_app):
    """If a cue lacks a meaningful name (or has empty string),
    the toast falls back to the cue id rather than producing
    "Failed to preload \"\": ...".
    """
    cue = _make_cue("c1", preload=True)
    cue.name = ""  # falsy
    cue.media.prearm.return_value = False
    manager._try_arm(cue, ArmReason.Preload)
    assert mock_app.notify.emit.call_count == 1
    args, _ = mock_app.notify.emit.call_args
    assert '"c1"' in args[0]


def test_safe_decorator_swallows_exceptions(manager, mock_app, caplog):
    """Public method decorated with @_safe must not propagate
    exceptions. Per spec design rule 4: 'No exception leaks out
    of the manager.'
    """
    import logging

    # Force standby_changed to raise by giving it a cue whose
    # _eligible() check explodes (simulate a corrupted cue).
    bad_cue = MagicMock()
    bad_cue.id = "bad"
    # Accessing .media raises
    type(bad_cue).media = property(
        lambda self: (_ for _ in ()).throw(RuntimeError("boom"))
    )
    with caplog.at_level(logging.ERROR, logger="lisp.cues.pre_arm_manager"):
        # Should NOT raise
        manager.standby_changed(bad_cue)
    assert any(
        "standby_changed" in r.message for r in caplog.records
    )


def test_no_failures_no_toast(manager, mock_app):
    """Empty session_load with no failures: zero toasts."""
    mock_app.cue_model = MagicMock()
    mock_app.cue_model.__iter__ = lambda self: iter([])
    mock_app.layout = MagicMock()
    mock_app.layout.standby_cue.return_value = None

    manager.session_loaded()

    mock_app.notify.emit.assert_not_called()


# T14 tests --------------------------------------------------------------

def test_subscribes_to_app_signals_on_init(manager_factory, mock_app):
    """Constructor wires app + cue_model + layout signals."""
    manager_factory()
    mock_app.session_loaded.connect.assert_called()
    mock_app.cue_model.item_added.connect.assert_called()
    mock_app.cue_model.item_removed.connect.assert_called()
    mock_app.layout.standby_changed.connect.assert_called()
    mock_app.layout.cue_executed.connect.assert_called()


def test_init_tolerates_missing_layout(mock_app):
    """If app.layout is not yet set when manager is constructed,
    no crash. (Layouts can be wired later via _wire_layout.)
    """
    mock_app.conf = MagicMock()
    mock_app.conf.get.side_effect = _config_returner()
    mock_app.session_loaded = MagicMock()
    mock_app.cue_model = MagicMock()
    mock_app.cue_model.item_added = MagicMock()
    mock_app.cue_model.item_removed = MagicMock()
    mock_app.layout = None
    PreArmManager(mock_app)  # should not raise


def _make_wired_cue(cue_id, preload=False, media_type="Audio"):
    """Like _make_cue but with per-property signal mocks on both the cue
    and cue.media that match the real property layout after the fix:
    - cue.changed("preload") → signal
    - cue.media.changed("start_time") → signal
    - cue.media.changed("pipe") → signal
    The old cue.changed("uri") and cue.changed("start_time") are gone.
    """
    cue = _make_cue(cue_id, preload=preload, media_type=media_type)
    cue.stopped = MagicMock()
    cue.interrupted = MagicMock()
    cue.end = MagicMock()
    cue.error = MagicMock()

    preload_signal = MagicMock()
    cue.changed = lambda prop: (
        preload_signal if prop == "preload"
        else (_ for _ in ()).throw(ValueError(f'no property "{prop}" found'))
    )
    cue._preload_signal = preload_signal

    pipe_signal = MagicMock()
    start_time_signal = MagicMock()

    def _media_changed(name):
        if name == "pipe":
            return pipe_signal
        if name == "start_time":
            return start_time_signal
        raise ValueError(f'no property "{name}" found')

    cue.media.changed = _media_changed
    cue.media._pipe_signal = pipe_signal
    cue.media._start_time_signal = start_time_signal

    return cue


def test_per_cue_signals_connected_on_arm(manager):
    """First successful arm of a cue connects per-cue signals.

    After the fix: preload wires via cue.changed('preload'), start_time
    and pipe (URI proxy) wire via cue.media.changed(). cue.changed('uri')
    is no longer called — uri is not a cue property.
    """
    cue = _make_wired_cue("c1")
    manager._try_arm(cue, ArmReason.Auto)
    cue.stopped.connect.assert_called()
    cue.interrupted.connect.assert_called()
    cue.end.connect.assert_called()
    cue.error.connect.assert_called()
    assert cue._preload_signal.connect.called
    assert cue.media._pipe_signal.connect.called
    assert cue.media._start_time_signal.connect.called


def test_per_cue_signals_idempotent_across_rearm(manager):
    """Re-arming the same cue does NOT re-connect its signals."""
    cue = _make_wired_cue("c1")

    manager._try_arm(cue, ArmReason.Auto)
    initial_count = cue.stopped.connect.call_count
    manager._disarm(cue)
    manager._try_arm(cue, ArmReason.Auto)
    assert cue.stopped.connect.call_count == initial_count


def test_cue_removed_clears_handler_refs(manager):
    """cue_removed drops the per-cue handler references."""
    cue = _make_wired_cue("c1")
    manager._try_arm(cue, ArmReason.Auto)
    assert "c1" in manager._cue_handlers
    manager.cue_removed(cue)
    assert "c1" not in manager._cue_handlers


# T16 tests — _wire_layout idempotence ----------------------------------------

def test_wire_layout_idempotent_for_same_instance(manager_factory, mock_app):
    """Calling _wire_layout twice with the same instance does NOT
    re-connect signals (used by Application.__wire_layout_for_pre_arm
    which fires on every session_created)."""
    manager = manager_factory()
    layout = MagicMock()
    layout.standby_changed = MagicMock()
    layout.cue_executed = MagicMock()
    manager._wire_layout(layout)
    initial_calls = layout.standby_changed.connect.call_count
    manager._wire_layout(layout)
    assert layout.standby_changed.connect.call_count == initial_calls


def test_wire_layout_two_distinct_layouts(manager_factory, mock_app):
    """Two different layout instances both get wired."""
    manager = manager_factory()
    layout_a = MagicMock()
    layout_a.standby_changed = MagicMock()
    layout_a.cue_executed = MagicMock()
    layout_b = MagicMock()
    layout_b.standby_changed = MagicMock()
    layout_b.cue_executed = MagicMock()
    manager._wire_layout(layout_a)
    manager._wire_layout(layout_b)
    assert layout_a.standby_changed.connect.called
    assert layout_b.standby_changed.connect.called


def test_wire_layout_none_is_safe_noop(manager_factory):
    """Application can construct the manager before a session
    exists; _wire_layout(None) must be silent."""
    manager = manager_factory()
    manager._wire_layout(None)  # no exception, nothing wired


# Regression tests — _eligible reads MediaType from input element ----------


class TestEligibleRealisticMedia:
    """Regression: _eligible must read MediaType from the input element
    (cue.media.elements[0].MediaType), not from cue.media.MediaType
    directly. The latter does not exist on real GstMedia.
    """

    def test_eligible_reads_mediatype_from_input_element(self, manager):
        """Real GstMedia has no MediaType attribute; it lives on the
        first element of the pipeline (e.g. UriInput.MediaType = MediaType.Audio).
        """
        cue = MagicMock()
        cue.id = "test-cue"
        type(cue).__name__ = "MediaCue"  # not GroupCue

        # CRITICAL: real GstMedia has no MediaType attribute. Configure
        # the mock to mirror that — spec=["elements"] strips magic auto-attrs
        # so getattr(media, "MediaType", None) returns None, just like on
        # a real GstMedia instance.
        media = MagicMock(spec=["elements"])
        input_element = MagicMock()
        input_element.MediaType = "Audio"
        media.elements = [input_element]
        cue.media = media

        assert manager._eligible(cue) is True

    def test_not_eligible_when_input_element_is_video(self, manager):
        cue = MagicMock()
        cue.id = "vid-cue"
        type(cue).__name__ = "MediaCue"
        media = MagicMock(spec=["elements"])
        input_element = MagicMock()
        input_element.MediaType = "Video"
        media.elements = [input_element]
        cue.media = media

        assert manager._eligible(cue) is False

    def test_not_eligible_when_pipeline_not_built(self, manager):
        """A freshly-created cue with no input elements yet is not eligible."""
        cue = MagicMock()
        cue.id = "blank-cue"
        type(cue).__name__ = "MediaCue"
        media = MagicMock(spec=["elements"])
        media.elements = []  # empty pipeline
        cue.media = media

        assert manager._eligible(cue) is False


# Regression tests — _wire_cue_signals uses cue.media for uri/start_time ----


class TestWireCueSignalsRealisticShape:
    """Regression: _wire_cue_signals tried cue.changed('uri') and
    cue.changed('start_time'), but those properties live on cue.media,
    not on the cue. ValueError from HasProperties.changed() also
    wasn't caught. Exercising _wire_cue_signals on a realistic mock
    must not raise.
    """

    def test_wire_cue_signals_does_not_crash_on_real_property_layout(
        self, manager
    ):
        # Cue: spec strips magic auto-attrs so changed("uri") raises
        # ValueError (matching real HasProperties behaviour) for properties
        # that don't exist on the cue.
        cue = MagicMock(
            spec=["id", "preload", "media", "changed",
                  "stopped", "interrupted", "end", "error"]
        )
        cue.id = "cue-1"
        cue.preload = True

        def _cue_changed(name):
            if name == "preload":
                return MagicMock()
            raise ValueError(f'no property "{name}" found')

        cue.changed.side_effect = _cue_changed

        # Media holds start_time and pipe
        media = MagicMock(spec=["changed", "elements"])

        def _media_changed(name):
            if name in ("start_time", "pipe"):
                return MagicMock()
            raise ValueError(f'no property "{name}" found')

        media.changed.side_effect = _media_changed
        cue.media = media

        # Should not raise
        manager._wire_cue_signals(cue)

    def test_wire_cue_signals_connects_pipe_for_uri_change(self, manager):
        """The URI-change handler is wired through cue.media.changed('pipe')
        (URI lives on the input element; pipe rebuild is the proxy)."""
        cue = MagicMock(
            spec=["id", "preload", "media", "changed",
                  "stopped", "interrupted", "end", "error"]
        )
        cue.id = "cue-2"

        pipe_signal = MagicMock()
        start_time_signal = MagicMock()
        preload_signal = MagicMock()

        def _media_changed(name):
            if name == "pipe":
                return pipe_signal
            if name == "start_time":
                return start_time_signal
            raise ValueError(f'no property "{name}" found')

        media = MagicMock(spec=["changed", "elements"])
        media.changed.side_effect = _media_changed
        cue.media = media

        def _cue_changed(name):
            if name == "preload":
                return preload_signal
            raise ValueError(f'no property "{name}" found')

        cue.changed.side_effect = _cue_changed

        manager._wire_cue_signals(cue)

        pipe_signal.connect.assert_called_once()
        start_time_signal.connect.assert_called_once()
        preload_signal.connect.assert_called_once()

    def test_wire_cue_signals_skips_missing_media(self, manager):
        """A cue without media attribute should not crash wire (defensive)."""
        cue = MagicMock(
            spec=["id", "preload", "changed",
                  "stopped", "interrupted", "end", "error"]
        )
        cue.id = "cue-3"

        preload_signal = MagicMock()
        cue.changed.side_effect = lambda name: (
            preload_signal if name == "preload"
            else (_ for _ in ()).throw(ValueError())
        )

        manager._wire_cue_signals(cue)
        preload_signal.connect.assert_called_once()
