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
import time

from lisp.core.model import Model
from lisp.cues.cue import Cue, CueAction, CueState

logger = logging.getLogger(__name__)

# States in which a cue holds resources (media, a projection sink, a
# fade or wait thread) that halting it releases.
_ACTIVE = CueState.IsRunning | CueState.IsPaused


class CueModel(Model):
    """Simple model to store cue(s), as (cue.id, cue) pairs.

    The model can be iterated to retrieve the cues, to get id-cue pairs
    use the items() function, to get only the id(s) use the keys() function.
    """

    # Longest `reset()` waits, in seconds, for the cues it halts to
    # leave their active states.
    HALT_TIMEOUT = 2.0

    def __init__(self):
        super().__init__()
        self.__cues = {}

    def add(self, cue):
        if cue.id in self.__cues:
            raise ValueError("the cue is already in the model")

        self.__cues[cue.id] = cue
        self.item_added.emit(cue)

    def remove(self, cue):
        self.pop(cue.id)

    def pop(self, cue_id):
        """:rtype: Cue"""
        cue = self.__cues.pop(cue_id)
        self._halt(cue)
        self.item_removed.emit(cue)

        # Promote children of the removed cue to its parent group, so
        # dissolving an inner group doesn't leave them holding a
        # dangling group_id (which survives save/load and silently
        # breaks the nested hierarchy on the next reload). A corrupt
        # self-parented group promotes to the top level instead.
        # UngroupCuesCommand pre-promotes before calling remove, so this
        # no-ops on that path; it's the safety net for direct
        # cue_model.remove callers.
        parent_group_id = cue.group_id if cue.group_id != cue_id else ""
        promoted = [
            other.id for other in self.__cues.values()
            if other.group_id == cue_id
        ]

        # When a group is dissolved, splice the promoted ids into the
        # parent group's explicit `children` list in place of the
        # removed group's id. Playback iterates that list -- not the
        # group_id back-links -- so without this the promoted children
        # silently stop playing (bug C1). Done *before* promoting, so a
        # failure can't leave the links half-rewritten. Removing a plain
        # cue leaves its parent's list alone: `_resolve_children` skips
        # the missing id, and re-adding the cue (undo) restores playback.
        # Undoing a removal of a group is RemoveCuesCommand's job.
        # Groups are duck-typed -- a cue with a `children` list -- so
        # core doesn't import the group plugin.
        parent = self.__cues.get(parent_group_id)
        if self._is_group(cue) and self._is_group(parent):
            parent.replace_child(
                cue_id, cue.promotion_order(cue.children, promoted)
            )

        for other_id in promoted:
            self.promote(self.__cues[other_id], parent_group_id)

        return cue

    @staticmethod
    def _is_group(cue):
        return isinstance(getattr(cue, "children", None), list)

    @staticmethod
    def promote(cue, parent_group_id):
        """Move ``cue`` up to ``parent_group_id`` (its dissolved group's
        parent), never pointing a cue's group_id at itself -- that only
        happens with a corrupt group_id cycle; such a cue goes to the
        top level instead."""
        cue.group_id = parent_group_id if cue.id != parent_group_id else ""

    def get(self, cue_id, default=None):
        """Return the cue with the given id, or the default value.

        :rtype: Cue
        """
        return self.__cues.get(cue_id, default)

    def items(self):
        """Return a set-like object proving a view on model items (id, cue)"""
        return self.__cues.items()

    def keys(self):
        """Return a set-like object proving a view on of model keys (cue id)"""
        return self.__cues.keys()

    def reset(self):
        """Halt every active cue, then empty the model.

        Session teardown (`Session.finalize`) ends here. Without the
        halt, running cues are orphaned: never interrupted, never
        emitting interrupted/stopped, and one kept alive (e.g. by a
        running fade) keeps playing and keeps its projection sink,
        blocking every video/image cue of the next session.

        `Cue.interrupt`/`stop` run on their own threads, so this waits
        -- by polling state, never taking a cue's lock on this thread
        -- up to `HALT_TIMEOUT` for the halted cues to stop before
        clearing. So pipelines are released before the next session
        exists, and handlers connected directly to interrupted/stopped
        (which run on the halting thread) still find the cue in the
        model. Queued handlers run later, after the clear. A cue still
        active at the deadline is logged and dropped anyway.
        """
        halting = [cue for cue in self.__cues.values() if self._halt(cue)]
        self._wait_halted(halting)

        self.__cues.clear()
        self.model_reset.emit()

    @staticmethod
    def _halt(cue):
        """Interrupt *cue*, or stop it if it can't be interrupted.

        Only active cues are halted: an idle one has nothing to
        release, and each halt starts a thread. Returns whether a halt
        was dispatched. A cue that fails to dispatch is logged, so one
        broken cue can't stop the others from being halted.
        """
        try:
            if not cue.state & _ACTIVE:
                return False
            if CueAction.Interrupt in cue.CueActions:
                cue.interrupt()
            elif CueAction.Stop in cue.CueActions:
                cue.stop()
            else:
                return False
        except Exception:
            logger.exception("Failed to halt cue %r", cue.id)
            return False
        return True

    def _wait_halted(self, cues):
        """Wait, up to `HALT_TIMEOUT` in all, for *cues* to go idle."""
        deadline = time.monotonic() + self.HALT_TIMEOUT
        for cue in cues:
            while cue.state & _ACTIVE:
                if time.monotonic() >= deadline:
                    logger.warning(
                        "Cue %r still active %ss after being halted; "
                        "dropping it anyway",
                        cue.id,
                        self.HALT_TIMEOUT,
                    )
                    break
                time.sleep(0.005)

    def filter(self, cue_class=Cue):
        """Return an iterator over cues that are instances of the given class"""
        for cue in self.__cues.values():
            if isinstance(cue, cue_class):
                yield cue

    def __iter__(self):
        return self.__cues.values().__iter__()

    def __len__(self):
        return len(self.__cues)

    def __contains__(self, cue):
        return cue.id in self.__cues
