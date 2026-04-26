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
    cue.media.MediaType = media_type
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
