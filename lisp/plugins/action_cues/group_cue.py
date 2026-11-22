# This file is part of Linux Show Player
#
# Copyright 2024 Francesco Ceruti <ceppofrancy@gmail.com>
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
import random
from threading import Lock

from PyQt5.QtCore import QT_TRANSLATE_NOOP, Qt
from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QVBoxLayout,
)

from lisp.core.clock import Clock_33
from lisp.core.properties import Property
from lisp.core.signal import Connection, Signal

from lisp.cues.cue import Cue, CueAction, CueState
from lisp.ui.settings.cue_settings import CueSettingsRegistry
from lisp.ui.settings.pages import SettingsPage
from lisp.ui.ui_utils import translate

logger = logging.getLogger(__name__)


class GroupCue(Cue):
    Name = QT_TRANSLATE_NOOP("CueName", "Group Cue")
    Category = QT_TRANSLATE_NOOP("CueCategory", "Action cues")

    CueActions = (
        CueAction.Default,
        CueAction.Start,
        CueAction.Stop,
        CueAction.Pause,
        CueAction.Resume,
        CueAction.Interrupt,
    )

    children = Property(default=[])
    group_mode = Property(default="parallel")
    loop = Property(default=False)
    crossfade = Property(default=0.0)
    shuffle = Property(default=False)
    icon = Property(default="cue-group")
    collapsed = Property(default=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = translate("CueName", self.Name)

        self._lock = Lock()
        self._playlist_index = 0
        self._crossfade_armed = False
        # Owners (StopCue ids) of the Fade & Stop fades in flight on
        # this group (M78): while any, the group starts no new child.
        # A set, not a count, so a release from a fade that a restart
        # already forgot can't drop another fade's hold. Guarded by
        # _lock.
        self._fade_holders = set()
        # Id of the child whose natural end was held back: the advance
        # from it runs on release, or on resume after the pause.
        # Guarded by _lock.
        self._held_after_id = None
        # Seconds to fade the held child in when the group resumes
        # (set by Fade & Resume); None = its own fade-in. Guarded by
        # _lock.
        self._held_fadein = None
        # The catch-up after the last release runs on the main thread,
        # where natural advances run, not on the StopCue's fade thread.
        self._request_catch_up = Signal()
        self._request_catch_up.connect(
            self._catch_up, Connection.QtQueued
        )
        # Track which children have signal handlers connected
        self._connected_children = set()
        # Crossfade fade durations waiting to be put back, as
        # {(cue_id, attr): restore}. `Signal` holds slots weakly, so
        # this is what keeps each one-shot restore alive. Guarded by
        # _lock.
        self._pending_restores = {}
        # Restores released but not yet applied on the main thread, as
        # {(cue_id, attr): (held_value, original)}. Until applied, the
        # child still carries the held value; `_start_child` reads
        # through it so a quick re-GO doesn't use the crossfade
        # duration as the child's own fade-in. Guarded by _lock.
        self._restoring = {}
        # Restores are triggered on worker threads; the property write
        # itself is queued to the main thread, because property_changed
        # listeners (e.g. the inspector) expect the main thread.
        self._request_restore = Signal()
        self._request_restore.connect(
            self._apply_restore, Connection.QtQueued
        )

        # Signal to relay crossfade arming to the main thread.
        # Clock_33 is a QTimer — callbacks must be added from the
        # Qt main thread.  __start__ runs in a worker thread, so
        # we use QtQueued to post to the event loop.
        self._request_crossfade_arm = Signal()
        self._request_crossfade_arm.connect(
            self._start_crossfade_monitor, Connection.QtQueued
        )

        # Shuffle when the user toggles the option on.
        self.property_changed.connect(self._on_property_changed)

    def _on_property_changed(self, _cue, name, value):
        """Sanitise `children`; shuffle when shuffle turns on.

        Fires during deserialization as well. For `children` that is
        the point: a hand-edited/corrupt session can hold non-string
        entries (e.g. ``[["x"], {}]``) that load fine but make every
        id lookup (dict/set hashing) raise later, mid-operation. Drop
        them once, here, keeping order. For shuffle it's harmless:
        _shuffle_on_load runs on session_loaded and double-shuffling
        remains uniformly random.
        """
        if (
            name == "children"
            and isinstance(value, list)
            and not all(isinstance(i, str) for i in value)
        ):
            self.children = [i for i in value if isinstance(i, str)]
            return

        if (
            name == "shuffle"
            and value is True
            and self.group_mode == "playlist"
            and len(self.children) > 1
        ):
            self.shuffle_children()

    def shuffle_children(self):
        """Randomize children order and sync the layout.

        Mutates `self.children` in place (list of IDs) and moves
        each child cue in the active layout's model so the list
        view rows match the new playback order.
        """
        random.shuffle(self.children)
        self._resync_layout_to_children()

    def _resync_layout_to_children(self):
        """Move children in the layout model so row order follows
        `self.children`.  Uses the layout adapter's `move` API so
        `item_moved` is emitted and the tree view reorders rows.
        """
        layout = getattr(self.app, "layout", None)
        model = getattr(layout, "model", None) if layout else None
        if model is None:
            return
        # Children occupy contiguous slots starting right after
        # the group itself.  Walk the shuffled list and move each
        # child to its target slot; cues in between shift naturally.
        base = self.index + 1
        for offset, child_id in enumerate(self.children):
            child = self.app.cue_model.get(child_id)
            if child is None:
                continue
            target = base + offset
            if child.index != target:
                model.move(child.index, target)

    def replace_child(self, old_id, new_ids):
        """Splice ``new_ids`` into `children` in place of ``old_id``.

        Used when a nested group is dissolved (ungroup or removal) to
        move its promoted children into this, its parent, group:
        playback iterates `children`, not the `group_id` back-links,
        so the promoted ids must land here or they silently stop
        playing. If `children` doesn't list ``old_id`` (group_id and
        children have drifted apart in an older session) the ids are
        appended instead, for the same reason.

        Skipped ids: this group's own id, ids already listed, and any
        id whose own subtree already contains this group -- so a
        corrupt or stale hierarchy can't make a group contain itself
        or create a playback cycle. No-op if `children` isn't a list.

        The list is rebuilt and reassigned, never mutated in place:
        assignment fires `property_changed` (the layout and undo rely
        on it), and a playback worker iterating the old list never
        sees it half-updated.

        :return: True if `children` was changed
        """
        children = self.children
        if not isinstance(children, list):
            return False

        listed = set(children)
        # Ids from which this group is reachable through `children`
        # (itself included): splicing any of them in would be a cycle.
        blocked = self._ids_reaching(self.id)
        spliced = []
        for cue_id in new_ids:
            if cue_id in listed or cue_id in blocked:
                continue
            listed.add(cue_id)
            spliced.append(cue_id)

        if old_id in children:
            index = children.index(old_id)
            self.children = (
                children[:index] + spliced + children[index + 1:]
            )
            return True
        if spliced:
            self.children = children + spliced
            return True
        return False

    def _ids_reaching(self, target_id):
        """Ids whose `children` subtree contains ``target_id`` (plus
        ``target_id`` itself), found with one upward walk over the
        model -- linear in the model, however many ids get checked."""
        parents = {}
        for cue in self.app.cue_model:
            children = getattr(cue, "children", None)
            if isinstance(children, list):
                for child_id in children:
                    parents.setdefault(child_id, []).append(cue.id)

        reaching, stack = {target_id}, [target_id]
        while stack:
            for parent_id in parents.get(stack.pop(), ()):
                if parent_id not in reaching:
                    reaching.add(parent_id)
                    stack.append(parent_id)
        return reaching

    @staticmethod
    def promotion_order(listed_ids, promoted_ids):
        """Order the ids promoted out of a dissolved group.

        Ids follow the dissolved group's own `children` order
        (``listed_ids``); any promoted ids it didn't list (cues whose
        `group_id` pointed at it anyway) are appended after them.
        """
        if not isinstance(listed_ids, list):
            listed_ids = []
        promoted = set(promoted_ids)
        ordered = [i for i in listed_ids if i in promoted]
        listed = set(ordered)
        ordered += [i for i in promoted_ids if i not in listed]
        return ordered

    def _resolve_children(self):
        """Return the list of child Cue objects in order."""
        cues = []
        for child_id in self.children:
            cue = self.app.cue_model.get(child_id)
            if cue is not None:
                cues.append(cue)
        return cues

    def _resolve_playable_children(self):
        """Like `_resolve_children`, but excludes children whose
        `effective_disabled` is True. Used by playback paths so
        disabled children are skipped at start, during playlist
        advance, and during crossfade hand-off. Bookkeeping paths
        (e.g. `_resync_layout_to_children`) continue to use
        `_resolve_children` since they need the full list
        regardless of runtime state.
        """
        return [
            c for c in self._resolve_children()
            if not c.effective_disabled
        ]

    def _start_refused(self, action, notify=True):
        """Refuse what `Cue.execute` refuses, plus (H31):

        - a start with no playable children: a parent group (or GO's
          auto-follow) would otherwise wait for a group that never
          runs. `Default` arrives here already resolved, so GO and
          auto-follow are refused too, and a Default on a running
          group (a stop) is not affected.
        - resuming a paused group when a paused child would refuse its
          resume (an exclusive cue or a video started meanwhile): the
          group stays paused and keeps the child, as a paused cue
          resumed directly does.
        - resuming a paused group with no paused child but a held
          advance (M78) when every child it would start refuses: the
          group stays paused and keeps the advance.

        A refusal drops a Fade & Resume's fade-in request
        (`fade_in_held_next`): it was for this resume only.
        """
        refused = self._refuses_start(action, notify)
        if refused:
            with self._lock:
                self._held_fadein = None
        return refused

    def _refuses_start(self, action, notify):
        if super()._start_refused(action, notify):
            return True

        if action in (CueAction.Start, CueAction.FadeInStart):
            if self._state & CueState.IsRunning:
                return False
        elif action in (CueAction.Resume, CueAction.FadeInResume):
            if not self._state & CueState.IsPaused:
                return False
        else:
            return False

        children = self._resolve_playable_children()
        if not children:
            return True
        if self._state & CueState.IsPaused:
            paused = [c for c in children if c.state & CueState.IsPaused]
            if paused:
                return any(
                    child._start_refused(CueAction.Resume, notify=notify)
                    is True
                    for child in paused
                )
            with self._lock:
                held_after = self._held_after_id
            if held_after is not None:
                return self._held_advance_refused(held_after, notify)
        return False

    def _held_advance_refused(self, held_after, notify):
        """True when every child the held advance would try (as
        `_play_child_at` walks them) refuses to start. The operator
        hears of it once, for the first child."""
        index, playable = self._next_after(held_after)
        if index is None:
            return False  # the playlist is over: the resume ends it
        candidates = [
            playable[i] for i in self._playlist_walk(index, len(playable))
        ]
        if not all(
            child._start_refused(CueAction.Start, notify=False) is True
            for child in candidates
        ):
            return False
        if notify:
            candidates[0]._start_refused(CueAction.Start, notify=True)
        return True

    def __start__(self, fade=False):
        with self._lock:
            # Any (re)start is past every Fade & Stop: a later release
            # from one of them finds nothing to drop.
            self._fade_holders.clear()
        children = self._resolve_playable_children()
        if not children:
            self._forget_held()
            return False

        if self.group_mode == "parallel":
            return self._start_parallel(children)
        else:
            return self._start_playlist(children)

    def _start_parallel(self, children):
        """Start all children simultaneously.

        A child refused the start (exclusive cue, video exclusivity,
        disabled) will never end, so it is not waited for. Returns
        False when nothing is left to wait for -- every child was
        refused -- so `Cue.start` ends the group straight away and its
        `end` (auto-follow) still fires.
        """
        with self._lock:
            self._connected_children = set()

            for child in children:
                self._connect_child(child, parallel=True)

        for child in children:
            was_paused = child.state & CueState.IsPaused
            if not self._start_child(child):
                self._drop_refused(child, was_paused, parallel=True)

        with self._lock:
            return bool(self._connected_children)

    def _start_playlist(self, children):
        """Start the playlist: resume the paused child, else start the
        child after one whose end a Fade & Stop held back (M78), else
        start from the top."""
        with self._lock:
            idx = self._playlist_index
            resuming = bool(
                idx < len(children)
                and children[idx].state & CueState.IsPaused
            )
            held_after, self._held_after_id = self._held_after_id, None
            fadein, self._held_fadein = self._held_fadein, None
            self._connected_children = set()
            self._crossfade_armed = False

        held_idx = None
        if not resuming and held_after is not None:
            # A paused child, if any, wins: it is a song in progress.
            # Index the list the advance was resolved against.
            held_idx, children = self._next_after(held_after)
            if held_idx is None:
                # The playlist ended inside the fade: end the group,
                # as the catch-up and a natural advance would.
                return False
        if not resuming:
            idx = held_idx if held_idx is not None else 0
        with self._lock:
            self._playlist_index = idx

        restore = None
        if held_idx is not None and fadein:
            # Fade & Resume brings the held child in over its own
            # duration: the child wasn't playing, so its fade covers
            # nothing of it.
            restore = self._hold_child_fadein(children[idx], fadein)

        started = self._play_child_at(idx, children)
        if restore is not None and (
            not started or self._playlist_index != idx
        ):
            restore()  # it was refused and skipped: never started
        return started

    def _play_child_at(self, index, children=None):
        """Start the child at the given playlist index.

        A child refused the start (exclusive cue, video exclusivity,
        disabled) is skipped like a disabled one: the next child is
        tried, wrapping round when looping, each child at most once.

        :return: True if a child started. False when none could (no
            children, past the end without loop, or all refused): the
            caller ends the group, since this runs both inside
            `__start__` (where `Cue.start` does it) and on a natural
            advance.
        """
        if children is None:
            children = self._resolve_playable_children()

        count = len(children)
        if index >= count:
            if not (self.loop and count):
                return False
            index = 0

        for i in self._playlist_walk(index, count):
            child = children[i]
            with self._lock:
                self._playlist_index = i
                self._connect_child(child, parallel=False)

            was_paused = child.state & CueState.IsPaused
            if self._start_child(child):
                self._arm_crossfade_if_needed(i, children)
                return True
            self._drop_refused(child, was_paused, parallel=False)

        # Keep the position (a paused child stays the one to resume),
        # not the last child tried.
        with self._lock:
            self._playlist_index = index
        return False

    def _drop_refused(self, child, was_paused, parallel):
        """A child refused its start: stop following it. One refused
        a resume is stopped too, or it would stay paused with no group
        to stop it (__stop__ only stops running children); a paused
        video also keeps blocking every other video. Normally a paused
        group refuses the resume before this (`_start_refused`); this
        is the block arriving in between."""
        self._disconnect_child(child, parallel=parallel)
        if was_paused:
            child.execute(CueAction.Stop)

    def _playlist_walk(self, first, count):
        """Playlist indices from ``first`` on, wrapping round when
        looping, each at most once."""
        for step in range(count):
            i = first + step
            if i >= count:
                if not self.loop:
                    return
                i -= count
            yield i

    def _start_child(self, child):
        """Start (or resume, if paused) a child with its OWN fade-in.

        The group's own `fade` flag is deliberately not consulted: it
        is the group's fade-in, which a GroupCue never has, so gating
        on it meant no child ever faded in (H34). A child that can't
        take the fade action gets the plain one, since `Cue.execute`
        silently ignores actions outside `CueActions`.

        :return: False if the child refused the start (H31)
        """
        if child.state & CueState.IsPaused:
            plain, faded = CueAction.Resume, CueAction.FadeInResume
        else:
            plain, faded = CueAction.Start, CueAction.FadeInStart

        if self._own_fadein(child) > 0 and faded in child.CueActions:
            action = faded
        else:
            action = plain

        # `Cue.execute` returns False only when it refuses the start.
        return child.execute(action) is not False

    def _own_fadein(self, child):
        """The child's fade-in, minus any crossfade hold that has been
        released but whose restore hasn't run yet on the main thread
        (e.g. GO pressed right after stopping the group mid-crossfade).

        Only seen through while the value is still the held one, so an
        edit made after the hold wins. The child itself isn't written
        here: `_apply_restore` does that, on the main thread.
        """
        value = child.fadein_duration
        with self._lock:
            held = self._restoring.get((child.id, "fadein_duration"))
        if held is not None and value == held[0]:
            return held[1]
        return value

    def _arm_crossfade_if_needed(self, index, children):
        """Arm the crossfade monitor if there is a next child."""
        if self.group_mode != "playlist":
            # `crossfade` survives a switch to parallel mode.
            return
        has_next = index + 1 < len(children)
        can_loop = self.loop and len(children) > 1
        if self.crossfade > 0 and (has_next or can_loop):
            with self._lock:
                self._crossfade_armed = True
            # Relay to the main thread via QtQueued signal — Clock_33
            # is a QTimer whose callbacks must be added from the main
            # thread, but __start__ runs in a worker thread.
            self._request_crossfade_arm.emit()

    def _start_crossfade_monitor(self):
        """Add the crossfade check to the clock (main thread only)."""
        with self._lock:
            if not self._crossfade_armed:
                return
        Clock_33.add_callback(self._check_crossfade)

    def _connect_child(self, child, parallel):
        """Connect signal handlers to a child cue. Must hold _lock."""
        if parallel:
            child.end.connect(
                self._on_child_ended, Connection.QtQueued
            )
            child.stopped.connect(
                self._on_child_ended, Connection.QtQueued
            )
            child.interrupted.connect(
                self._on_child_ended, Connection.QtQueued
            )
            child.error.connect(
                self._on_child_ended, Connection.QtQueued
            )
        else:
            # Playlist: natural end advances, manual stop kills group
            child.end.connect(
                self._on_playlist_child_ended, Connection.QtQueued
            )
            child.stopped.connect(
                self._on_playlist_child_stopped, Connection.QtQueued
            )
            child.interrupted.connect(
                self._on_playlist_child_stopped, Connection.QtQueued
            )
            child.error.connect(
                self._on_playlist_child_stopped, Connection.QtQueued
            )
        self._connected_children.add(child.id)

    def _disconnect_child(self, child, parallel):
        """Disconnect signal handlers from a child cue."""
        if parallel:
            child.end.disconnect(self._on_child_ended)
            child.stopped.disconnect(self._on_child_ended)
            child.interrupted.disconnect(self._on_child_ended)
            child.error.disconnect(self._on_child_ended)
        else:
            child.end.disconnect(self._on_playlist_child_ended)
            child.stopped.disconnect(
                self._on_playlist_child_stopped
            )
            child.interrupted.disconnect(
                self._on_playlist_child_stopped
            )
            child.error.disconnect(
                self._on_playlist_child_stopped
            )
        with self._lock:
            self._connected_children.discard(child.id)

    def _disconnect_all_children(self):
        """Disconnect signal handlers from all connected children."""
        parallel = self.group_mode == "parallel"
        with self._lock:
            child_ids = set(self._connected_children)

        for child_id in child_ids:
            child = self.app.cue_model.get(child_id)
            if child is not None:
                self._disconnect_child(child, parallel)

    def _check_crossfade(self):
        """Clock callback: check if crossfade point is reached."""
        with self._lock:
            if not self._crossfade_armed or self._fade_holders:
                return
            index = self._playlist_index

        children = self._resolve_playable_children()
        if not children or index >= len(children):
            self._stop_crossfade_monitor()
            return

        child = children[index]
        if not (child.state & CueState.Running):
            return

        if child.duration <= 0:
            return

        remaining_ms = child.duration - child.current_time()
        crossfade_ms = self.crossfade * 1000

        if remaining_ms <= crossfade_ms:
            self._stop_crossfade_monitor()

            # Bring the next child in first: only fade the current
            # one out once another has really started. If none can
            # (all refused), the current child plays to its end, and
            # the natural advance retries or ends the group (H31).
            next_index = self._crossfade_in_next(index, children)
            if next_index is None:
                return

            # Disconnect the current child BEFORE fading it out,
            # so its `stopped` signal won't trigger
            # _on_playlist_child_stopped and kill the group.
            self._disconnect_child(child, parallel=False)

            # Fade out current child, temporarily using the
            # crossfade as its fade duration. The stop worker
            # reads it before the fade starts, so put it back on
            # fadeout_start, or once the child has stopped or
            # ended some other way.
            if child.fadeout_duration <= 0:
                self._hold_fade(
                    child,
                    "fadeout_duration",
                    self.crossfade,
                    (child.fadeout_start, child.stopped,
                     child.interrupted, child.error, child.end),
                )
            child.execute(CueAction.FadeOutStop)

            # Re-arm crossfade for the next transition
            self._arm_crossfade_if_needed(next_index, children)

    def _crossfade_in_next(self, index, children):
        """Start the first child after ``index`` that accepts a
        fade-in start, skipping refused ones (wrapping when looping).

        :return: its index, or None if no child started (the current
            one, at ``index``, stays the playlist's current child)
        """
        for next_index in self._playlist_walk(index + 1, len(children)):
            if next_index == index:
                break
            next_child = children[next_index]
            # Only ask: a refusal here is expected in a video playlist
            # (the outgoing video blocks the incoming one), and the
            # advance at the natural end reports a real block.
            if next_child._start_refused(
                CueAction.FadeInStart, notify=False
            ) is True:
                continue
            with self._lock:
                self._playlist_index = next_index
                self._connect_child(next_child, parallel=False)

            # Same for the fade-in, but only for a child that
            # can take FadeInStart (others ignore it, so a
            # hold would never be released by a start).
            restore_fadein = None
            if (
                CueAction.FadeInStart in next_child.CueActions
                and next_child.fadein_duration <= 0
            ):
                restore_fadein = self._hold_fade(
                    next_child,
                    "fadein_duration",
                    self.crossfade,
                    (self._fadein_read_signal(next_child),
                     next_child.stopped,
                     next_child.interrupted,
                     next_child.error, next_child.end),
                )
            if next_child.execute(CueAction.FadeInStart) is not False:
                return next_index

            # Refused (exclusive cue, disabled): it will never
            # start, so nothing else would restore or end it.
            if restore_fadein is not None:
                restore_fadein()
            self._disconnect_child(next_child, parallel=False)

        with self._lock:
            self._playlist_index = index
        return None

    def _hold_fade(self, cue, attr, value, signals):
        """Set ``cue.<attr>`` to ``value`` until one of ``signals``
        fires, then put the original back.

        Returns the restore callable. It runs at most once, whoever
        calls it first (a signal on a worker thread, or
        `_flush_pending_restores`), and queues the write to the main
        thread (`_apply_restore`), which leaves the value alone if
        someone changed it in the meantime. The registry holds it
        strongly until it has run, since `Signal` only holds a weak
        reference.
        """
        original = getattr(cue, attr)
        key = (cue.id, attr)

        def restore(*_args):
            with self._lock:
                if self._pending_restores.get(key) is not restore:
                    return
                del self._pending_restores[key]
                self._restoring[key] = (value, original)
            for signal in signals:
                signal.disconnect(restore)
            self._request_restore.emit(cue, attr, value, original)

        # Register and connect before setting the value, so no signal
        # can fire with the value set and no restore in place.
        with self._lock:
            self._pending_restores[key] = restore
        for signal in signals:
            signal.connect(restore)
        setattr(cue, attr, value)
        return restore

    def _apply_restore(self, cue, attr, value, original):
        """Main thread: put ``original`` back, unless the value was
        changed by someone else since the hold."""
        if getattr(cue, attr) == value:
            setattr(cue, attr, original)
        with self._lock:
            key = (cue.id, attr)
            if self._restoring.get(key) == (value, original):
                del self._restoring[key]

    @staticmethod
    def _fadein_read_signal(cue):
        """The signal after which ``cue`` has read its fade-in duration.

        A MediaCue that can fade reads it in an async fade task that
        can run after `started`, and announces it with `fadein_start`.
        Any other cue never emits `fadein_start`; it reads the
        duration (if at all) inside its start, before `started`.
        """
        can_fade = getattr(cue, "_can_fade", None)
        if callable(can_fade) and can_fade():
            return cue.fadein_start
        return cue.started

    def _flush_pending_restores(self):
        """Put back every crossfade fade duration still pending.

        For when the group stops: a child that never stops or starts
        would otherwise keep the crossfade value, and it would be
        saved with the session.

        Known limits: pausing keeps the held values (resume needs
        them), so a save while paused mid-crossfade writes them. A
        child still inside its own start when the group stops can
        miss its fade-in; the group doesn't stop such a child
        either (it isn't Running yet), which predates this.
        """
        with self._lock:
            pending = list(self._pending_restores.values())
        for restore in pending:
            restore()

    def _stop_crossfade_monitor(self):
        with self._lock:
            self._crossfade_armed = False
        try:
            Clock_33.remove_callback(self._check_crossfade)
        except Exception:
            pass

    def _on_child_ended(self, cue):
        """Parallel mode: track when all children have ended."""
        self._disconnect_child(cue, parallel=True)

        with self._lock:
            remaining = bool(self._connected_children)

        if not remaining and self.state & CueState.Running:
            self._ended()

    def _on_playlist_child_ended(self, cue):
        """Playlist mode: child finished naturally, advance."""
        self._disconnect_child(cue, parallel=False)

        if not (self.state & CueState.Running):
            return

        with self._lock:
            # If other children are still connected (crossfade
            # overlap), wait for them to finish too.
            if self._connected_children:
                return

        next_idx, playable = self._next_after(cue.id)
        if next_idx is None:
            self._ended()
            return

        with self._lock:
            if self._fade_holders:
                # A Fade & Stop is fading the group: a child started
                # now would play unfaded and be cut by its pause or
                # stop (M78). The advance runs on release or resume.
                self._held_after_id = cue.id
                return

        # Refused children are skipped; if none can start, end.
        if not self._play_child_at(next_idx, playable):
            self._ended()

    def _next_after(self, ended_id):
        """Where a natural advance from the child ``ended_id`` goes.

        :return: ``(index, playable)``: an index into the playable
            children, or None when the playlist is over.
        """
        # Walk the FULL ordered children list by id, so a sibling
        # disabled mid-playback doesn't shift the position, and
        # `_playlist_index` (which may have drifted) isn't needed.
        full_children = self._resolve_children()
        ended_pos = next(
            (i for i, c in enumerate(full_children) if c.id == ended_id),
            # Removed from the group mid-playback (rare): treat as the
            # end of the playlist.
            len(full_children),
        )
        next_cue = next(
            (c for c in full_children[ended_pos + 1:]
             if not c.effective_disabled),
            None,
        )
        playable = self._resolve_playable_children()
        if next_cue is None:
            return (0 if self.loop and playable else None), playable
        # None too if it somehow isn't playable: fail safe, end.
        index = next(
            (i for i, c in enumerate(playable) if c.id == next_cue.id),
            None,
        )
        return index, playable

    def hold_transitions(self, owner):
        """A Fade & Stop (`StopCue` ``owner``, any action) starts
        fading this group: start no new child until it is done (M78).

        The fade covers only the cues playing when it starts. A
        crossfade or natural advance during it would bring in a child
        at full level, and the pause or stop at its end would cut it.
        So the crossfade monitor stops, and a natural end is recorded
        instead of advancing.

        A start already dispatched when the hold lands (a child still
        starting up) is not covered (L108).

        Only playlist groups advance; a parallel group ignores it.
        """
        if self.group_mode != "playlist":
            return
        with self._lock:
            self._fade_holders.add(owner)
        self._stop_crossfade_monitor()

    def release_transitions(self, owner):
        """``owner``'s fade is over: after its action has landed, or
        aborted. When no hold is left, catch up (on the main thread)
        if the group is still playing."""
        with self._lock:
            if owner not in self._fade_holders:
                return  # a restart already dropped it
            self._fade_holders.discard(owner)
            if self._fade_holders:
                return
        self._request_catch_up.emit()

    def fade_in_held_next(self, seconds):
        """Fade & Resume: fade the held child (if any) in over
        ``seconds`` when the group resumes."""
        with self._lock:
            if self._held_after_id is not None and seconds > 0:
                self._held_fadein = seconds
            else:
                self._held_fadein = None

    def _catch_up(self):
        """Main thread, after the last release: run what the hold kept
        back if the group still plays (the fade was aborted, or its
        action never reached the group). A paused group keeps the held
        advance for its resume."""
        with self._lock:
            if self._fade_holders or not self._state & CueState.Running:
                return
            held_after, self._held_after_id = self._held_after_id, None
            self._held_fadein = None
            index = self._playlist_index

        if held_after is not None:
            next_idx, playable = self._next_after(held_after)
            if next_idx is None or not self._play_child_at(
                next_idx, playable
            ):
                self._ended()
            return

        playable = self._resolve_playable_children()
        if index < len(playable) and (
            playable[index].state & CueState.Running
        ):
            # Fires at once if the crossfade point has passed.
            self._arm_crossfade_if_needed(index, playable)

    def _hold_child_fadein(self, child, seconds):
        """Give ``child`` a ``seconds`` fade-in for its next start;
        returns the restore, or None if it can't fade in or already
        has its own fade-in."""
        if (
            CueAction.FadeInStart not in child.CueActions
            or child.fadein_duration > 0
        ):
            return None
        return self._hold_fade(
            child,
            "fadein_duration",
            seconds,
            (self._fadein_read_signal(child), child.stopped,
             child.interrupted, child.error, child.end),
        )

    def _forget_held(self):
        with self._lock:
            self._held_after_id = None
            self._held_fadein = None

    def _on_playlist_child_stopped(self, cue):
        """Playlist mode: child was stopped/interrupted, stop group."""
        self._stop_crossfade_monitor()
        self._disconnect_all_children()
        self._flush_pending_restores()

        if self.state & CueState.Running:
            self._ended()

    def __stop__(self, fade=False):
        # The hold itself stays until its fade releases it (or a
        # restart): dropping it here, before Running clears, would let
        # a queued natural end start a child in between.
        self._forget_held()
        self._stop_crossfade_monitor()
        self._disconnect_all_children()
        self._flush_pending_restores()

        for child in self._resolve_children():
            if child.state & CueState.IsRunning:
                if fade:
                    child.execute(CueAction.FadeOutStop)
                else:
                    child.execute(CueAction.Stop)

        return True

    def __pause__(self, fade=False):
        # A held advance stays for the resume.
        self._stop_crossfade_monitor()

        for child in self._resolve_children():
            if child.state & CueState.Running:
                if fade:
                    child.execute(CueAction.FadeOutPause)
                else:
                    child.execute(CueAction.Pause)

        return True

    def __interrupt__(self, fade=False):
        self._forget_held()
        self._stop_crossfade_monitor()
        self._disconnect_all_children()
        self._flush_pending_restores()

        for child in self._resolve_children():
            if child.state & CueState.IsRunning:
                if fade:
                    child.execute(CueAction.FadeOutInterrupt)
                else:
                    child.execute(CueAction.Interrupt)

        return True


class GroupCueSettings(SettingsPage):
    Name = QT_TRANSLATE_NOOP("SettingsPageName", "Group Settings")
    SortOrder = 30

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.setLayout(QVBoxLayout())
        self.layout().setAlignment(Qt.AlignTop)

        self.group = QGroupBox(self)
        self.group.setLayout(QFormLayout())
        self.layout().addWidget(self.group)

        self.modeCombo = QComboBox(self.group)
        self.modeCombo.addItem(
            translate("GroupCue", "Parallel"), "parallel"
        )
        self.modeCombo.addItem(
            translate("GroupCue", "Playlist"), "playlist"
        )
        self.group.layout().addRow(
            translate("GroupCue", "Mode"), self.modeCombo
        )

        self.crossfadeSpin = QDoubleSpinBox(self.group)
        self.crossfadeSpin.setRange(0.0, 60.0)
        self.crossfadeSpin.setSingleStep(0.5)
        self.crossfadeSpin.setSuffix(" s")
        self.crossfadeSpin.setDecimals(1)
        self.group.layout().addRow(
            translate("GroupCue", "Crossfade"), self.crossfadeSpin
        )

        self.loopCheck = QCheckBox(self.group)
        self.group.layout().addRow(
            translate("GroupCue", "Loop"), self.loopCheck
        )

        self.shuffleCheck = QCheckBox(self.group)
        self.group.layout().addRow(
            translate("GroupCue", "Shuffle"), self.shuffleCheck
        )

        self.modeCombo.currentIndexChanged.connect(
            self._mode_changed
        )

        self.retranslateUi()

    def retranslateUi(self):
        self.group.setTitle(
            translate("GroupCue", "Group Settings")
        )

    def _mode_changed(self, index):
        is_playlist = self.modeCombo.currentData() == "playlist"
        self.crossfadeSpin.setEnabled(is_playlist)
        self.loopCheck.setEnabled(is_playlist)
        self.shuffleCheck.setEnabled(is_playlist)

    def enableCheck(self, enabled):
        self.setGroupEnabled(self.group, enabled)

    def loadSettings(self, settings):
        mode = settings.get("group_mode", "parallel")
        index = self.modeCombo.findData(mode)
        if index >= 0:
            self.modeCombo.setCurrentIndex(index)

        self.crossfadeSpin.setValue(settings.get("crossfade", 0.0))
        self.loopCheck.setChecked(settings.get("loop", False))
        self.shuffleCheck.setChecked(settings.get("shuffle", False))
        self._mode_changed(self.modeCombo.currentIndex())

    def getSettings(self):
        if self.isGroupEnabled(self.group):
            return {
                "group_mode": self.modeCombo.currentData(),
                "crossfade": self.crossfadeSpin.value(),
                "loop": self.loopCheck.isChecked(),
                "shuffle": self.shuffleCheck.isChecked(),
            }
        return {}


CueSettingsRegistry().add(GroupCueSettings, GroupCue)
