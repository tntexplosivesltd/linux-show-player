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

import logging
from enum import Flag, auto

from lisp.core.signal import Signal

logger = logging.getLogger(__name__)


class ArmReason(Flag):
    """Why a cue is currently in the armed set."""

    Auto = auto()     # Standby look-ahead
    Preload = auto()  # User explicitly marked preload=True


class PreArmManager:
    """Owns the set of pre-armed cues and translates intent into
    Media.prearm() / disarm() calls. Enforces the resource cap.

    This task (T7) implements the core arm/disarm/cap logic. Signal
    subscriptions and lifecycle hooks are added in subsequent tasks.
    """

    def __init__(self, app):
        self._app = app
        self._armed: dict = {}       # cue_id -> ArmReason
        self._failed: dict = {}      # cue_id -> reason text
        self._mtime_at_arm: dict = {}

        self._cap = app.conf.get("preArm.maxArmed", 16)
        self._lookahead = app.conf.get("preArm.lookahead", 1)
        self._enabled = app.conf.get("preArm.enabled", True)
        self._fail_on_cap_hit = app.conf.get(
            "preArm.failOnCapHit", False
        )

        self.armed_set_changed = Signal()

    # --- Eligibility --------------------------------------------------

    def _eligible(self, cue) -> bool:
        if not self._enabled:
            return False
        # GroupCue is not pre-arm-eligible per spec
        if type(cue).__name__ == "GroupCue":
            return False
        if not hasattr(cue, "media"):
            return False
        media_type = getattr(cue.media, "MediaType", None)
        # Accept the enum value or the string "Audio" for tests
        try:
            from lisp.backend.media_element import MediaType
            audio_enum = MediaType.Audio
        except Exception:
            audio_enum = None
        if media_type not in (audio_enum, "Audio"):
            return False
        return True

    # --- Core arm/disarm ----------------------------------------------

    def _try_arm(self, cue, reason: ArmReason) -> bool:
        """Arm a cue with the given reason. Returns True on success.

        If the cue is already armed, OR-merges the reason and returns
        True. If not eligible or cap-blocked, returns False.
        """
        if cue.id in self._armed:
            self._armed[cue.id] |= reason
            self.armed_set_changed.emit()
            return True
        if not self._eligible(cue):
            return False
        if len(self._armed) >= self._cap:
            logger.info(
                "PreArmManager: cap reached (%d), refusing arm of %s",
                self._cap, cue.id,
            )
            self._record_failure(cue, "cap reached", from_cap=True)
            return False
        try:
            ok = cue.media.prearm()
        except Exception as exc:
            logger.error(
                "PreArmManager: prearm raised for %s: %s", cue.id, exc
            )
            ok = False
        if not ok:
            logger.warning(
                "PreArmManager: prearm failed for %s", cue.id
            )
            self._record_failure(cue, "preload failed")
            return False
        self._armed[cue.id] = reason
        self._failed.pop(cue.id, None)
        self.armed_set_changed.emit()
        return True

    def _disarm(self, cue) -> None:
        """Disarm a cue (full removal, regardless of reason).
        Idempotent: silent no-op if not in the armed set.
        """
        if cue.id not in self._armed:
            return
        try:
            cue.media.disarm()
        except Exception as exc:
            logger.error(
                "PreArmManager: disarm raised for %s: %s", cue.id, exc
            )
        self._armed.pop(cue.id, None)
        self._mtime_at_arm.pop(cue.id, None)
        self.armed_set_changed.emit()

    def _add_reason(self, cue, reason: ArmReason) -> None:
        """Add a reason to an already-armed cue. If not armed, attempt
        to arm with the new reason.
        """
        if cue.id not in self._armed:
            self._try_arm(cue, reason)
            return
        self._armed[cue.id] |= reason
        self.armed_set_changed.emit()

    def _remove_reason(self, cue, reason: ArmReason) -> None:
        """Remove a reason from an armed cue. If no reasons remain,
        fully disarm.
        """
        if cue.id not in self._armed:
            return
        new_reason = self._armed[cue.id] & ~reason
        if not new_reason:
            self._disarm(cue)
        else:
            self._armed[cue.id] = new_reason
            self.armed_set_changed.emit()

    # --- Failure tracking ---------------------------------------------

    def _record_failure(
        self, cue, reason_text: str, from_cap: bool = False,
    ) -> None:
        """Record a failure if the cue is preload-marked.

        Auto-arm failures are silent (no indicator, no toast). Cap
        refusals are silent unless ``failOnCapHit=True`` AND the cue
        is preload-marked.
        """
        if not getattr(cue, "preload", False):
            return
        if from_cap and not self._fail_on_cap_hit:
            return
        self._failed[cue.id] = reason_text
        self.armed_set_changed.emit()
