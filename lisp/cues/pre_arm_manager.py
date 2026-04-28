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

import functools
import logging
from enum import Flag, auto
from pathlib import Path

from lisp.core.signal import Signal
from lisp.ui.widgets.notification import NotificationLevel

logger = logging.getLogger(__name__)


def _safe(method):
    """Decorator: catches and logs exceptions in PreArmManager public
    methods. The manager is glue between subsystems; per spec design
    rule 4 ('No exception leaks out of the manager'), it must never
    crash the show. ERROR-log with the method name and traceback,
    return None.
    """

    @functools.wraps(method)
    def _wrapper(self, *args, **kwargs):
        try:
            return method(self, *args, **kwargs)
        except Exception:
            logger.error(
                "PreArmManager.%s raised", method.__name__,
                exc_info=True,
            )
            return None

    return _wrapper


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

        # When non-None, _try_arm collects failed preload cues here instead
        # of emitting per-cue toasts. session_loaded sets/clears this to
        # coalesce a batch of failures into a single summary toast.
        self._collecting_session_failures: list | None = None

        # Strong references to per-cue signal handlers (closures) keyed
        # by cue.id. LiSP signals use weak refs, so we must keep these
        # alive here or they get GC'd before any signal can fire.
        self._cue_handlers: dict = {}

        # Track which layout instances have already been wired so that
        # _wire_layout is idempotent — Application.__wire_layout_for_pre_arm
        # subscribes to session_created and may be called multiple times.
        self._wired_layout_ids: set = set()

        self.armed_set_changed = Signal()

        # Wire to application-level signals so the public methods
        # fire automatically. (Tests bypass this by calling the
        # methods directly.) Each connection is wrapped via _safe
        # at the method level — exceptions in handlers won't leak.
        self._wire_application_signals()
        self._wire_layout(getattr(self._app, "layout", None))

    # --- Signal wiring ------------------------------------------------

    def _wire_application_signals(self) -> None:
        """Connect to app and cue_model signals."""
        try:
            self._app.session_loaded.connect(self.session_loaded)
        except AttributeError:
            logger.debug("PreArmManager: app.session_loaded missing")
        cue_model = getattr(self._app, "cue_model", None)
        if cue_model is not None:
            try:
                cue_model.item_added.connect(self.cue_added)
                cue_model.item_removed.connect(self.cue_removed)
            except AttributeError:
                logger.debug(
                    "PreArmManager: cue_model signals missing"
                )

    def _wire_layout(self, layout) -> None:
        """Connect to a CueLayout's signals. Tolerant of None or
        layouts that lack one of the signals (e.g. cart_layout has
        no standby_changed). Idempotent — calling twice with the
        same layout instance is a no-op.
        """
        if layout is None:
            return
        layout_id = id(layout)
        if layout_id in self._wired_layout_ids:
            return
        self._wired_layout_ids.add(layout_id)
        if hasattr(layout, "standby_changed"):
            try:
                layout.standby_changed.connect(self.standby_changed)
            except AttributeError:
                pass
        if hasattr(layout, "cue_executed"):
            try:
                layout.cue_executed.connect(self.cue_executed)
            except AttributeError:
                pass

    def _wire_cue_signals(self, cue) -> None:
        """Connect to per-cue signals on the first arm of a given cue.
        Idempotent across multiple arm/disarm cycles via the
        _pre_arm_wired flag attribute on the cue itself.
        """
        if getattr(cue, "_pre_arm_wired", False) is True:
            return
        # Use a private flag attribute so we can detect re-arms of the
        # same cue without re-connecting handlers.
        try:
            cue._pre_arm_wired = True
        except Exception:
            # If cue is read-only (rare; probably a frozen dataclass
            # in tests), give up — the manager will still function via
            # tests calling methods directly.
            return

        # Hold strong refs to bound methods/lambdas so weak-ref signals
        # don't lose them. Keyed by cue.id for cleanup on cue_removed.
        handlers = []

        def _on_uri(_v, c=cue):
            self.on_uri_changed(c)

        def _on_start(_v, c=cue):
            self.on_start_time_changed(c)

        def _on_preload(value, c=cue):
            self.on_preload_changed(c, value)

        handlers.extend([_on_uri, _on_start, _on_preload])
        self._cue_handlers[cue.id] = handlers

        for sig_name in ("stopped", "interrupted", "end", "error"):
            sig = getattr(cue, sig_name, None)
            if sig is not None:
                try:
                    sig.connect(self.on_cue_stopped)
                except AttributeError:
                    pass

        # preload lives on the cue itself (MediaCue.preload)
        try:
            cue.changed("preload").connect(_on_preload)
        except (AttributeError, TypeError, ValueError):
            pass

        # start_time and pipe-rebuild signals live on cue.media
        # (Media.start_time and GstMedia.pipe respectively — neither
        # exists as a top-level cue property).
        media = getattr(cue, "media", None)
        if media is not None:
            try:
                media.changed("start_time").connect(_on_start)
            except (AttributeError, TypeError, ValueError):
                pass
            # URI / file changes drive a full pipe rebuild. Subscribing
            # through `pipe` is the robust proxy: any element swap
            # (including different URI in the same input element) will
            # trigger it, whereas UriInput.uri is per-element and harder
            # to reach cleanly from here.
            try:
                media.changed("pipe").connect(_on_uri)
            except (AttributeError, TypeError, ValueError):
                pass

    # --- Eligibility --------------------------------------------------

    def _eligible(self, cue) -> bool:
        if not self._enabled:
            return False
        # GroupCue is not pre-arm-eligible per spec
        if type(cue).__name__ == "GroupCue":
            return False
        media = getattr(cue, "media", None)
        if media is None:
            return False
        elements = getattr(media, "elements", None)
        if not elements:
            return False  # pipeline not yet built — not eligible
        try:
            media_type = getattr(elements[0], "MediaType", None)
        except (IndexError, TypeError):
            return False
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
        logger.debug(
            "PreArmManager: _try_arm cue=%s reason=%s already_armed=%s",
            cue.id, reason, cue.id in self._armed,
        )
        if cue.id in self._armed:
            self._armed[cue.id] |= reason
            self.armed_set_changed.emit()
            return True
        if not self._eligible(cue):
            logger.debug(
                "PreArmManager: %s not eligible for arming", cue.id
            )
            return False
        if len(self._armed) >= self._cap:
            logger.info(
                "PreArmManager: cap reached (%d), refusing arm of %s",
                self._cap, cue.id,
            )
            self._record_failure(cue, "cap reached", from_cap=True)
            if self._fail_on_cap_hit:
                self._on_prearm_failed(cue)
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
            self._on_prearm_failed(cue)
            return False
        self._armed[cue.id] = reason
        self._failed.pop(cue.id, None)
        mtime = self._cue_mtime(cue)
        if mtime is not None:
            self._mtime_at_arm[cue.id] = mtime
        self._wire_cue_signals(cue)
        self.armed_set_changed.emit()
        logger.info(
            "PreArmManager: armed %s (reason=%s, total armed=%d)",
            cue.id, reason, len(self._armed),
        )
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
        logger.info("PreArmManager: disarmed %s", cue.id)

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

    @_safe
    def session_loaded(self, *_args) -> None:
        """Called when a session finishes loading. Arms preload-marked
        cues first (priority), then attempts to arm the standby cue.

        Failures during this batch are coalesced into a single toast
        (per-cue if 1, summary if >=2).
        """
        if not self._enabled:
            logger.info(
                "PreArmManager: session_loaded but pre-arm is disabled"
            )
            return

        preload_count = sum(
            1 for c in self._app.cue_model
            if getattr(c, "preload", False)
        )
        logger.info(
            "PreArmManager: session_loaded — scanning %d cues "
            "(%d preload-marked)",
            len(list(self._app.cue_model)), preload_count,
        )

        self._collecting_session_failures = []
        try:
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

            failures = self._collecting_session_failures
        finally:
            self._collecting_session_failures = None

        self._emit_batch_failure_notification(failures)

    def _emit_batch_failure_notification(self, failures) -> None:
        """Emit one toast summarising preload failures from session_load.

        No-op if `failures` is empty. Per-cue toast for one failure;
        summary toast for >=2.
        """
        if not failures:
            return
        if len(failures) == 1:
            cue = failures[0]
            category = self._failed.get(cue.id, "preload failed")
            name = self._cue_display_name(cue)
            message = f'Failed to preload "{name}": {category}'
        else:
            message = (
                f"Failed to preload {len(failures)} cues — "
                "see log for details"
            )
        self._app.notify.emit(message, NotificationLevel.Warning)

    def _on_prearm_failed(self, cue) -> None:
        """Route a prearm failure to the appropriate toast surface.

        During session_load, the failure is buffered for batch coalescing.
        Otherwise (mid-show), a per-cue toast is emitted directly.

        Auto-arm failures (preload=False) never produce a toast — the spec
        keeps best-effort optimisations silent.
        """
        if not getattr(cue, "preload", False):
            return  # auto-only failures stay silent
        if self._collecting_session_failures is not None:
            self._collecting_session_failures.append(cue)
            return
        # Mid-show: emit immediately
        self._emit_failure_toast(
            cue, self._failed.get(cue.id, "preload failed")
        )

    def _emit_failure_toast(self, cue, category: str) -> None:
        """Emit a per-cue WARNING toast for a preload failure.

        Always direct, never batched. Caller decides when to use this vs
        the batched session-load path.
        """
        name = self._cue_display_name(cue)
        message = f'Failed to preload "{name}": {category}'
        self._app.notify.emit(message, NotificationLevel.Warning)

    @staticmethod
    def _cue_display_name(cue) -> str:
        """Return a non-empty display name for a cue, falling back to
        the cue id if `name` is missing or empty. A cue is normally
        born with a default name, but a freshly-created cue or a test
        mock may lack one — defensive enough to not produce empty
        quoted strings in toasts.
        """
        name = getattr(cue, "name", None)
        if name:
            return name
        return getattr(cue, "id", "<unknown>")

    @_safe
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

    @_safe
    def cue_executed(self, cue) -> None:
        """Called when a cue is fired. The cue is now Playing, so it
        leaves the armed set.
        """
        if cue.id in self._armed:
            self._armed.pop(cue.id, None)
            self._mtime_at_arm.pop(cue.id, None)
            self.armed_set_changed.emit()

    @_safe
    def on_cue_stopped(self, cue) -> None:
        """Called when a cue stops/ends/is interrupted/errors. If marked
        preload, re-arm immediately. Otherwise no-op.
        """
        if getattr(cue, "preload", False) and self._eligible(cue):
            self._try_arm(cue, ArmReason.Preload)

    # --- T11: Edit invalidation ---------------------------------------

    @_safe
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

    @_safe
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

    @_safe
    def on_preload_changed(self, cue, new_value: bool) -> None:
        """User toggled the preload checkbox.

        True → add Preload reason (which arms the cue if not already).
        False → remove Preload reason (downgrades to Auto if also Auto,
        full-disarms if Preload-only).
        """
        logger.debug(
            "PreArmManager: on_preload_changed cue=%s new=%s",
            cue.id, new_value,
        )
        if new_value:
            if self._eligible(cue):
                self._add_reason(cue, ArmReason.Preload)
        else:
            self._remove_reason(cue, ArmReason.Preload)

    # --- T12: Add/remove + mtime --------------------------------------

    @_safe
    def cue_added(self, cue) -> None:
        """A new cue entered the model — arm if marked preload."""
        logger.debug(
            "PreArmManager: cue_added cue=%s preload=%s eligible=%s",
            cue.id,
            getattr(cue, "preload", False),
            self._eligible(cue),
        )
        if getattr(cue, "preload", False) and self._eligible(cue):
            self._try_arm(cue, ArmReason.Preload)

    @_safe
    def cue_removed(self, cue) -> None:
        """A cue was removed from the model — disarm + clean up state."""
        self._disarm(cue)
        self._failed.pop(cue.id, None)
        self._cue_handlers.pop(cue.id, None)

    @_safe
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
