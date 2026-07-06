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

from lisp.command.command import Command


class GroupCuesCommand(Command):
    """Group selected cues into a new GroupCue."""

    def __init__(self, app, list_model, cues):
        """
        :param app: Application instance
        :param list_model: CueListModel
        :param cues: list of Cue objects to group
        """
        self._app = app
        self._list_model = list_model
        self._cues = sorted(cues, key=lambda c: c.index)
        self._child_ids = [c.id for c in self._cues]
        self._insert_index = self._cues[0].index
        self._original_group_ids = {c.id: c.group_id for c in self._cues}

        # Pre-create the GroupCue so redo reuses the same ID
        from lisp.plugins.action_cues.group_cue import GroupCue

        self._group_cue = self._app.cue_factory.create_cue(
            "GroupCue"
        )
        self._group_cue.children = list(self._child_ids)

    def do(self):
        # Add group cue to the model
        self._app.cue_model.add(self._group_cue)

        # Move group cue to just before the first child
        if self._group_cue.index != self._insert_index:
            self._list_model.move(
                self._group_cue.index, self._insert_index
            )

        # Set group_id on all children
        for cue in self._cues:
            cue.group_id = self._group_cue.id

    def undo(self):
        # Restore original group_ids
        for cue in self._cues:
            cue.group_id = self._original_group_ids.get(cue.id, "")

        # Remove the group cue from the model (but keep the object)
        self._app.cue_model.remove(self._group_cue)

    def redo(self):
        self.do()


class UngroupCuesCommand(Command):
    """Dissolve a GroupCue, promoting children to its parent.

    For top-level groups the parent is "" (top-level), preserving
    legacy behavior. For nested inner groups the parent is the
    grandparent's id, so the surviving hierarchy collapses by
    exactly one level.
    """

    def __init__(self, app, list_model, group_cue):
        """
        :param app: Application instance
        :param list_model: CueListModel
        :param group_cue: The GroupCue to dissolve
        """
        self._app = app
        self._list_model = list_model
        self._group_cue = group_cue
        self._child_ids = list(group_cue.children)
        self._group_index = group_cue.index
        # Captured at construction so undo/redo cycles are
        # deterministic — the dissolved group's own group_id
        # is never mutated by do(), but the grandparent could
        # in principle be retargeted between cycles by some
        # other command, so we freeze the value we promote to.
        self._parent_group_id = group_cue.group_id
        # Snapshot of the grandparent's `children` list, taken in
        # do() so undo() can restore it verbatim. Stays None when the
        # parent is top-level ("") and thus has no children list.
        self._parent_children_before = None

    def do(self):
        from lisp.plugins.action_cues.group_cue import GroupCue

        # Promote children to the dissolved group's parent. For
        # top-level groups this is "" (legacy behavior); for
        # nested inner groups this is the grandparent's id.
        for child_id in self._child_ids:
            cue = self._app.cue_model.get(child_id)
            if cue is not None:
                cue.group_id = self._parent_group_id

        # Splice the promoted children into the grandparent GroupCue's
        # explicit `children` list, replacing the dissolved group's id
        # (preserving order). GroupCue playback iterates this list
        # (`_resolve_children`) rather than scanning for group_id
        # back-links, so without this the promoted children silently
        # stop being playable via the grandparent (bug C1). Top-level
        # parents ("") have no children list, hence the isinstance
        # guard.
        parent = self._app.cue_model.get(self._parent_group_id)
        if isinstance(parent, GroupCue) and (
            self._group_cue.id in parent.children
        ):
            self._parent_children_before = list(parent.children)
            index = parent.children.index(self._group_cue.id)
            parent.children = (
                parent.children[:index]
                + list(self._child_ids)
                + parent.children[index + 1:]
            )

        # Remove the group cue
        self._app.cue_model.remove(self._group_cue)

    def undo(self):
        # Re-add the group cue
        self._app.cue_model.add(self._group_cue)

        # Restore position
        if self._group_cue.index != self._group_index:
            self._list_model.move(
                self._group_cue.index, self._group_index
            )

        # Restore group_id on children
        for child_id in self._child_ids:
            cue = self._app.cue_model.get(child_id)
            if cue is not None:
                cue.group_id = self._group_cue.id

        # Restore the grandparent's `children` list to its pre-do()
        # state (undo the splice), so the dissolved group id is back
        # in place and its children are removed from the grandparent.
        if self._parent_children_before is not None:
            from lisp.plugins.action_cues.group_cue import GroupCue

            parent = self._app.cue_model.get(self._parent_group_id)
            if isinstance(parent, GroupCue):
                parent.children = list(self._parent_children_before)

    def redo(self):
        self.do()
