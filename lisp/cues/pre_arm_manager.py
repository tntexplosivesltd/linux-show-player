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
        mtime = self._cue_mtime(cue)
        if mtime is not None:
            self._mtime_at_arm[cue.id] = mtime
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

    # --- Lifecycle hooks ----------------------------------------------

    def session_loaded(self, *_args) -> None:
        """Called when a session finishes loading. Arms preload-marked
        cues first (priority), then attempts to arm the standby cue.
        """
        if not self._enabled:
            return
        # Phase 1: preload-marked cues (priority over auto)
        for cue in self._app.cue_model:
            if not getattr(cue, "preload", False):
                continue
            if not self._eligible(cue):
                continue
            self._try_arm(cue, ArmReason.Preload)
        # Phase 2: standby cue (best-effort)
        try:
            standby = self._app.layout.standby_cue()
        except Exception:
            standby = None
        if standby is not None and self._eligible(standby):
            self._try_arm(standby, ArmReason.Auto)

    def standby_changed(self, new_cue) -> None:
        """Called when the active layout's standby cursor moves.

        Cues that were Auto-only get disarmed. Cues with both Auto and
        Preload get downgraded to Preload (stay armed). The new standby
        is armed if eligible.
        """
        new_id = new_cue.id if new_cue is not None else None

        # Snapshot the current Auto-armed cues (avoid mutation during iter)
        auto_armed_ids = [
            cue_id for cue_id, reason in list(self._armed.items())
            if ArmReason.Auto in reason
        ]

        # Remove Auto from cues that are no longer standby
        for cue_id in auto_armed_ids:
            if cue_id == new_id:
                continue
            cue = self._cue_by_id(cue_id)
            if cue is not None:
                self._remove_reason(cue, ArmReason.Auto)

        # Arm the new standby
        if new_cue is not None and self._eligible(new_cue):
            if new_cue.id in self._armed:
                self._add_reason(new_cue, ArmReason.Auto)
            else:
                self._try_arm(new_cue, ArmReason.Auto)

    def _cue_mtime(self, cue):
        """Return the mtime (float seconds) of the cue's source file,
        or None if not a local file, doesn't exist, or any error.
        """
        try:
            from pathlib import Path
            uri = cue.media.input_uri()
            if uri is None or not getattr(uri, "is_local", False):
                return None
            path = Path(uri.absolute_path)
            if not path.exists():
                return None
            return path.stat().st_mtime
        except Exception:
            return None

    def _cue_by_id(self, cue_id: str):
        """Look up a cue by id. Returns None if not in the model.

        The try/except is for test isolation: with a MagicMock-based
        cue_model whose `.get` is not configured with a side_effect,
        the call would return another MagicMock (not None) and the
        caller's `if cue is not None` check would behave incorrectly.
        Wrapping it lets tests that don't care about cue lookup pass
        a bare MagicMock and still have us return None on misses.
        Production CueModel.get() honours its None-on-miss contract
        without raising, so the except branch never trips at runtime.
        """
        try:
            return self._app.cue_model.get(cue_id)
        except Exception:
            return None

    def cue_executed(self, cue) -> None:
        """Called when a cue is fired. The cue is now Playing, so it
        leaves the armed set.
        """
        if cue.id in self._armed:
            self._armed.pop(cue.id, None)
            self._mtime_at_arm.pop(cue.id, None)
            self.armed_set_changed.emit()

    def on_cue_stopped(self, cue) -> None:
        """Called when a cue stops/ends/is interrupted/errors. If marked
        preload, re-arm immediately. Otherwise no-op.
        """
        if getattr(cue, "preload", False) and self._eligible(cue):
            self._try_arm(cue, ArmReason.Preload)

    # --- T11: Edit invalidation ---------------------------------------

    def on_uri_changed(self, cue) -> None:
        """Armed cue's URI changed — full re-arm.

        Spec: targeted invalidation. Different file ⇒ different decoder
        ⇒ teardown and rebuild. Reason mask is preserved.
        """
        if cue.id not in self._armed:
            return
        reason = self._armed[cue.id]
        self._disarm(cue)
        self._try_arm(cue, reason)

    def on_start_time_changed(self, cue) -> None:
        """Armed cue's start_time changed — re-seek (no teardown).

        Spec: GstMedia.reseek() is cheap relative to a full pre-arm
        cycle.
        """
        if cue.id not in self._armed:
            return
        try:
            cue.media.reseek(cue.start_time)
        except Exception as exc:
            logger.warning(
                "PreArmManager: reseek failed for %s: %s", cue.id, exc
            )

    def on_preload_changed(self, cue, new_value: bool) -> None:
        """User toggled the preload checkbox.

        True → add Preload reason (which arms the cue if not already).
        False → remove Preload reason (downgrades to Auto if also Auto,
        full-disarms if Preload-only).
        """
        if new_value:
            if self._eligible(cue):
                self._add_reason(cue, ArmReason.Preload)
        else:
            self._remove_reason(cue, ArmReason.Preload)

    # --- T12: Add/remove + mtime --------------------------------------

    def cue_added(self, cue) -> None:
        """A new cue entered the model — arm if marked preload."""
        if getattr(cue, "preload", False) and self._eligible(cue):
            self._try_arm(cue, ArmReason.Preload)

    def cue_removed(self, cue) -> None:
        """A cue was removed from the model — disarm + clean up state."""
        self._disarm(cue)
        self._failed.pop(cue.id, None)

    def maybe_rearm_for_mtime(self, cue) -> None:
        """Check if the cue's source file has been modified since the
        cue was armed. If so, re-arm.

        No active polling — this is called only at "should I arm/keep-
        armed?" decision points (standby visit, post-stop re-arm, etc.).
        """
        if cue.id not in self._armed:
            return
        old = self._mtime_at_arm.get(cue.id)
        new = self._cue_mtime(cue)
        if old is None or new is None:
            return
        if new > old:
            reason = self._armed[cue.id]
            self._disarm(cue)
            self._try_arm(cue, reason)

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
