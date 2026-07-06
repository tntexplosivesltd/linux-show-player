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

from lisp.core.model import Model
from lisp.cues.cue import Cue, CueAction


class CueModel(Model):
    """Simple model to store cue(s), as (cue.id, cue) pairs.

    The model can be iterated to retrieve the cues, to get id-cue pairs
    use the items() function, to get only the id(s) use the keys() function.
    """

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

        # Try to interrupt/stop the cue
        if CueAction.Interrupt in cue.CueActions:
            cue.interrupt()
        elif CueAction.Stop in cue.CueActions:
            cue.stop()

        self.item_removed.emit(cue)

        # Promote children of the removed cue to its parent group,
        # so dissolving an inner group doesn't leave its children
        # holding a dangling group_id (which survives session
        # save/load and silently breaks the nested hierarchy on
        # the next reload). Mirrors UngroupCuesCommand's promotion
        # — UngroupCuesCommand pre-sets group_ids before calling
        # remove, so this loop no-ops on that path; it's the
        # safety net for direct cue_model.remove callers.
        parent_group_id = cue.group_id
        promoted = []
        for other in self.__cues.values():
            if other.group_id == cue_id:
                other.group_id = parent_group_id
                promoted.append(other.id)

        # Splice the promoted ids into the grandparent GroupCue's
        # explicit `children` list, replacing the removed group's id
        # (preserving order). Playback resolution iterates that list
        # — not the group_id back-links — so without this the
        # promoted children are silently dropped from the grandparent
        # (bug C1). Guarded by isinstance since a top-level ("")
        # parent has no children list. UngroupCuesCommand pre-splices
        # before calling remove, so this no-ops on that path (the
        # removed id is already gone from the parent's list); it's the
        # safety net for direct cue_model.remove callers.
        from lisp.plugins.action_cues.group_cue import GroupCue

        parent = self.__cues.get(parent_group_id)
        if isinstance(parent, GroupCue) and cue_id in parent.children:
            # Order the promoted ids by the removed group's own
            # children list where possible, appending any stragglers
            # (cues that pointed at the group but weren't listed).
            removed_children = list(getattr(cue, "children", []))
            ordered = [c for c in removed_children if c in promoted]
            ordered += [c for c in promoted if c not in ordered]

            index = parent.children.index(cue_id)
            parent.children = (
                parent.children[:index]
                + ordered
                + parent.children[index + 1:]
            )

        return cue

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
        self.__cues.clear()
        self.model_reset.emit()

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
