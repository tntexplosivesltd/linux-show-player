# Nested Group Cues — Design

**Status**: Draft
**Date**: 2026-05-03
**Author**: tphillips@ict.co (with Claude)

## Summary

Allow `GroupCue`s to contain other `GroupCue`s in the LiSP UI, so users can build the QLab-idiomatic structure of "parallel container holding a playlist of children, alongside other top-level cues" directly via right-click → **Group selected**, instead of routing around it with a `CollectionCue`.

The data model and runtime engine already support arbitrary nesting depth. The block is a single line of UI policy in the list-layout's grouping command (`lisp/plugins/list_layout/layout.py:578`). Removing it without further care surfaces two latent bugs in deletion and ungroup paths that currently never fire because nesting is impossible.

## Motivation

Today, to play (audio || video1 → video2 → video1 → ...) where the video pair loops alongside the audio, users must construct a `CollectionCue` whose targets list is `[(audio, Start), (video_group, Start)]` and trigger that. This works but is structurally non-obvious — the natural mental model "wrap the audio + video-group in a parallel parent" is the QLab approach and is what most users reach for first.

The runtime already supports it. The flat `CueModel` keys cues by id; hierarchy is expressed via a `group_id` property on each child cue. `effective_disabled` (`lisp/cues/cue.py:202-222`) already walks the chain with cycle protection. `GroupCue.__start__` (`lisp/plugins/action_cues/group_cue.py:169`) iterates resolved children and calls `child.execute(...)` — it doesn't care whether the child is a `MediaCue` or another `GroupCue`. The tree view in the list layout looks up parents via `_group_items[cue.group_id]` (`lisp/plugins/list_layout/list_view.py:658, 731`), which works at any depth.

The only thing standing between users and nested groups is a single `isinstance(c, GroupCue)` filter in the UI command path.

## Approach

Choose **Option B: Targeted** — drop the filter, fix the two latent reparenting bugs that nesting will surface, add a cycle guard to prevent invalid groupings, expand test coverage. No data-model or runtime engine changes.

Rejected alternatives:

- **Option A: Minimal — drop the filter only.** Surfaces silent bugs: deleting an inner group orphans its children to the top of the list instead of to the surviving grandparent; ungrouping an inner group does the same. Users would experience this as data loss (visually, the hierarchy collapses unexpectedly).
- **Option C: Deep — also model `GroupCue.duration` for cross-group crossfade and add depth-aware drag-drop hints.** Crossfade-with-nested-group is a genuine edge case but already fails gracefully today (the crossfade monitor at `group_cue.py:350` short-circuits on `duration <= 0`, producing "no crossfade" rather than a crash). Out of scope for this change; can be a follow-up if anyone reports the gap.

## Components

### 1. Drop the UI restriction — `lisp/plugins/list_layout/layout.py:571-589`

Today:

```python
def _group_cues(self, cues):
    from lisp.plugins.action_cues.group_cue import GroupCue

    cues = [
        c for c in cues
        if not isinstance(c, GroupCue)              # ← removed
        and (
            not c.group_id
            or self.app.cue_model.get(c.group_id) is None
        )
    ]
    if len(cues) < 1:
        return

    self.app.commands_stack.do(
        GroupCuesCommand(self.app, self._list_model, cues)
    )
```

Change:

- Remove the `not isinstance(c, GroupCue)` predicate. The "already in a live parent" filter on the next two lines correctly continues to prevent stealing a child from an active parent group.
- Add a cycle guard immediately before the `commands_stack.do` call: walk each candidate cue's `group_id` chain; if any ancestor is also in the candidate set, abort the command with a debug log. This prevents pathological selections like "select a parent group together with one of its descendants and try to group them" from creating a loop. Use `effective_disabled`-style cycle protection (a `visited` set) since corrupted sessions could already contain loops.

### 2. Ungroup-of-nested behavior — `lisp/command/group.py`

`UngroupCuesCommand` today (`lines 86-94`):

```python
def do(self):
    for child_id in self._child_ids:
        cue = self._app.cue_model.get(child_id)
        if cue is not None:
            cue.group_id = ""           # ← unconditional
    self._app.cue_model.remove(self._group_cue)
```

Change:

- In `__init__`, capture the dissolved group's own `group_id` once: `self._parent_group_id = group_cue.group_id`. (Captured at command-construction time, not at `do()` time, so undo/redo cycles are deterministic.)
- In `do()`, set children's `group_id` to `self._parent_group_id` rather than `""`. For top-level groups that's `""` (current behavior preserved); for nested inner groups that's the surviving grandparent's id (children stay in the parent group, just one level shallower).
- `undo()` already restores `cue.group_id = self._group_cue.id` for every child — unchanged. The dissolved group's *own* `group_id` is never modified by `do()`, so undo doesn't need to restore it.

### 3. Tree-view deletion reparenting — `lisp/plugins/list_layout/list_view.py:751-773`

Today, when a `GroupCue` is removed from the model, `__cueRemoved` reparents surviving children to the top level via `insertTopLevelItem` regardless of where the deleted group sat in the hierarchy. This is wrong for nested groups (the children should stay inside the surviving grandparent). Currently dormant because nesting is impossible.

Change:

- Before the children-promotion loop, look up the destination parent: `dest_parent = self._group_items.get(cue.group_id)` where `cue` is the removed group. If `dest_parent` is not None, insert each child via `dest_parent.insertChild(pos, child)` using the existing index-based positioning. If None (top-level removed group), keep current `insertTopLevelItem` behavior.
- The position-finding loop (`for i in range(self.topLevelItemCount())`) becomes a position-finding loop over `dest_parent.childCount()` when nested.

### 4. Tests

**Unit tests** (`tests/cues/test_group_cue.py`):

- `test_nested_group_runtime_parallel_outer_playlist_inner` — outer parallel group with one media child + one playlist inner group; assert that starting outer fires both, that the inner group's playlist advances and loops, and that stopping outer cleanly stops everything.
- `test_nested_group_effective_disabled_propagates` — disabling the outer group makes a media cue at depth 2 report `effective_disabled = True`.

**Command tests** (`tests/command/test_group_commands.py`):

- `test_group_cues_accepts_groupcue_in_selection` — calling `GroupCuesCommand` with a selection containing a `GroupCue` produces a new parent group with the inner group as a child (`inner.group_id == outer.id`).
- `test_group_cues_rejects_ancestor_descendant_selection` — calling the layout's `_group_cues` with a parent + one of its descendants pushes nothing onto the commands stack.
- `test_ungroup_nested_promotes_to_grandparent` — ungroup an inner group; assert children's `group_id` is now the grandparent's id, not `""`.
- `test_ungroup_nested_undo_restores` — undo of the above restores the inner group and children's `group_id` chain.

**List-view tests** (`tests/plugins/list_layout/`):

- `test_remove_nested_group_reparents_children_to_grandparent` — delete an inner group cue; surviving QTreeWidgetItem children appear under the grandparent, not at top-level.

**E2E test** (`tests/e2e/test_nested_groups_e2e.py`):

- Build a parallel-of-playlist structure via the test_harness `cue.add` and `layout.context_action` (Group selected) RPCs. Save the session, restart LiSP, reload, assert structure (`group_id` chain) is intact and the outer-group Start triggers both branches.

### 5. Out of scope

- `GroupCue.duration` definition for nested crossfade — not implemented; existing `duration <= 0` skip in the crossfade monitor produces a graceful no-op.
- UI affordances such as visual depth indicators or collapse-all — out of scope.
- Migration tooling for older LiSP versions reading nested-group sessions — LiSP has no session-version migration story today; older versions will display nested groups flat. Documented but not blocked.
- Any changes to the cart layout — it ignores groups entirely as a renderer; only its disable-walk uses `group_id`, and that already supports arbitrary depth.

## Risk

- **Backward compatibility on read**: existing flat sessions load unchanged; child cues' `group_id` values are untouched.
- **Backward compatibility on write**: sessions saved by a nested-groups-aware LiSP load on older versions, but the inner group is rendered as a top-level cue with its own children visually flat. Cues themselves play correctly because the engine is depth-agnostic. Acceptable.
- **Performance**: `effective_disabled` is O(depth) per call. Already cycle-protected. Practical depths (~3-4 levels) have no measurable cost.
- **UX surprise**: with no UI depth indicator, very deep nesting could be confusing visually. Mitigated by the QTreeWidget's natural indentation.

## Validation

The change is correct when:

1. `_group_cues` accepts a selection containing a `GroupCue` and produces a parent-of-group structure visible in the list view.
2. The cycle guard rejects ancestor+descendant selections.
3. Deleting a nested inner group leaves its children inside the grandparent, not at top-level.
4. Ungrouping a nested inner group leaves its children inside the grandparent, not at top-level.
5. The runtime correctly cascades start/stop/pause/resume through nested groups in both `parallel` and `playlist` modes, with looping honored at the playlist level.
6. Sessions roundtrip nested structures intact.
7. All existing tests pass; new nested-case tests pass.
8. Manual smoke test: build "audio || (video1 → video2 → loop)" end-to-end via the UI, hit Go on the outer group, observe both branches firing.
