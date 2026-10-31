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
from lisp.command.model import ModelRemoveItemsCommand
from lisp.cues.cue_model import CueModel


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
        # A corrupt self-parented group promotes to the top level.
        self._parent_group_id = (
            group_cue.group_id
            if group_cue.group_id != group_cue.id
            else ""
        )
        # Snapshot of the grandparent's `children` list, taken in
        # do() so undo() can restore it verbatim. None when do() made
        # no splice (e.g. the parent is top-level and has no list).
        self._parent_children_before = None
        # Cues that pointed at the group without being listed in its
        # children; do() promotes them too, so undo() must restore them.
        self._straggler_ids = []

    def do(self):
        from lisp.plugins.action_cues.group_cue import GroupCue

        # Reset per run: a redo() that makes no splice must not leave
        # an earlier run's snapshot for undo() to write back.
        self._parent_children_before = None

        model = self._app.cue_model
        group_id = self._group_cue.id
        present = [i for i in self._child_ids if model.get(i) is not None]
        self._straggler_ids = [
            cue.id for cue in model
            if cue.group_id == group_id and cue.id not in present
        ]
        promoted = GroupCue.promotion_order(
            self._child_ids, present + self._straggler_ids
        )

        # Splice the promoted children into the grandparent GroupCue's
        # explicit `children` list, replacing the dissolved group's id
        # (preserving order). GroupCue playback iterates this list
        # (`_resolve_children`) rather than scanning for group_id
        # back-links, so without this the promoted children silently
        # stop being playable via the grandparent (bug C1). Top-level
        # parents ("") have no children list, hence the isinstance
        # guard. Done before promoting, so a failure can't leave the
        # group_ids half-rewritten.
        parent = model.get(self._parent_group_id)
        if isinstance(parent, GroupCue):
            before = list(parent.children) if isinstance(
                parent.children, list
            ) else None
            if parent.replace_child(group_id, promoted):
                self._parent_children_before = before

        # Promote children to the dissolved group's parent. For
        # top-level groups this is "" (legacy behavior); for
        # nested inner groups this is the grandparent's id.
        for child_id in promoted:
            CueModel.promote(model.get(child_id), self._parent_group_id)

        # Remove the group cue
        model.remove(self._group_cue)

    def undo(self):
        # Re-add the group cue
        self._app.cue_model.add(self._group_cue)

        # Restore position
        if self._group_cue.index != self._group_index:
            self._list_model.move(
                self._group_cue.index, self._group_index
            )

        # Restore group_id on children (and on any stragglers do()
        # promoted along with them)
        for child_id in self._child_ids + self._straggler_ids:
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


class RemoveCuesCommand(ModelRemoveItemsCommand):
    """Remove cues from the cue model, undoably for the group hierarchy.

    `CueModel.pop()` promotes a removed group's children to its parent
    (rewriting their `group_id`) and splices them into the parent
    GroupCue's `children` list. A plain re-add, which is all
    `ModelRemoveItemsCommand.undo()` does, can't reverse that: the
    restored group would sit in the UI with its children promoted out
    of it, and with the grandparent no longer listing it, so it never
    plays. This records every `group_id`/`children` value that do()
    changed and puts them back on undo().
    """

    def __init__(self, cue_model, *cues):
        super().__init__(cue_model, *cues)
        # {cue: (group_id, children)} as they were before do(), for
        # just the fields do() changed; children is None for non-groups.
        self._restore = {}

    def do(self):
        before = {cue: self._hierarchy_state(cue) for cue in self._touchable()}
        super().do()
        self._restore = {
            cue: state
            for cue, state in before.items()
            if self._hierarchy_state(cue) != state
        }

    def undo(self):
        # Re-add in *reverse* removal order. Each cue kept the index it
        # had when it was removed (after the earlier removals), so the
        # reverse order puts every row back exactly, and a group is
        # always back before the children removed after it -- the list
        # view only nests a re-added row under a group row that already
        # exists, and never adopts existing rows when a group returns.
        for item in reversed(self._items):
            self._model.add(item)
        # Then restore links. Each group_id write fires property_changed
        # -> the list view reparents the row under the group's tree
        # item, which only exists once the group is back.
        for cue, (group_id, children) in self._restore.items():
            cue.group_id = group_id
            if children is not None:
                cue.children = list(children)

    def redo(self):
        self.do()

    def _touchable(self):
        """The cues whose group_id/children pop() can rewrite here: the
        removed cues, cues pointing at a removed cue (they get promoted,
        cascading through removed ancestors), and the removed cues'
        parents (which receive the splice). Snapshotting just these
        keeps a delete from rebuilding the whole model's hierarchy."""
        removed_ids = {cue.id for cue in self._items}
        parent_ids = {cue.group_id for cue in self._items}
        # Ordered (removed cues in removal order, then the rest in model
        # order) so undo writes -- and the property_changed signals they
        # fire -- happen in the same order every run.
        touchable = list(self._items)
        for cue in self._model:
            if cue.id in removed_ids:
                continue
            if cue.group_id in removed_ids or cue.id in parent_ids:
                touchable.append(cue)
        return touchable

    @staticmethod
    def _hierarchy_state(cue):
        from lisp.plugins.action_cues.group_cue import GroupCue

        children = None
        if isinstance(cue, GroupCue) and isinstance(cue.children, list):
            children = tuple(cue.children)
        return cue.group_id, children
