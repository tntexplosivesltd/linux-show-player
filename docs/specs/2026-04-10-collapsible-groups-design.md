# Collapsible Groups in List Layout

## Overview

Groups in the list layout should be collapsible, allowing users to hide
child cues under a group header for a more compact view. This uses the
native QTreeWidget parent/child hierarchy rather than the current flat
layout with text-indent hacks.

## Decisions

- **Approach**: True QTreeWidget hierarchy — child cues become
  `QTreeWidgetItem` children of the group item, using native
  collapse/expand arrows and keyboard navigation.
- **Persistence**: Per-group `collapsed` property on `GroupCue`,
  serialized automatically via the `Property` system into `.lsp` files.
- **Auto-expand on play**: Configurable (`autoExpandOnPlay`, default
  `True`). When a group starts playing, it expands. It does not
  auto-collapse when playback ends.
- **Bulk controls**: "Collapse all groups" / "Expand all groups" actions
  in the Layout menu bar with keyboard shortcuts.
- **Undo**: Collapse/expand is view state, not undoable.
- **Visual indicator**: Standard QTreeWidget expand/collapse arrow only.
  No child count badges or status summaries.

## Data Model

A single new property on `GroupCue`:

```python
collapsed = Property(default=False)
```

This is a view-hint stored on the cue. The `Property` descriptor handles
serialization, change notification (`changed("collapsed")`), and
session save/load automatically.

The `CueListModel` remains flat — all cues in index order. The
hierarchy is purely a view concern in `CueListView`.

## View Layer Changes

### CueListView (list_view.py)

**Indentation**: Re-enable `setIndentation()` (e.g. 16px) so native
tree arrows render. Currently set to 0.

**Parent-aware item management**:

- `__cueAdded`: When a cue has a `group_id` pointing to a live group,
  insert as a child of that group's `QTreeWidgetItem` instead of as a
  top-level item. When a `GroupCue` is added, insert as top-level and
  restore `item.setExpanded(not cue.collapsed)`.
- `__cueMoved`: Handle moves within/between groups and top-level.
  Take the item from its current parent and re-insert at the correct
  position under the new parent (or top-level).
- `__cueRemoved`: Remove from parent item rather than always from
  top-level.

**Collapse state sync**: Connect `QTreeWidget.itemCollapsed` and
`itemExpanded` signals to update the `GroupCue.collapsed` property when
the user toggles a group.

**Auto-expand on play**: Connect to each `GroupCue`'s `started`
signal (the same LiSP signal that `CueStatusIcons` already uses).
When fired and `autoExpandOnPlay` is enabled, call
`item.setExpanded(True)` and set `cue.collapsed = False`. Do not
auto-collapse on playback end.

**Standby index**: `standbyIndex()` and `setStandbyIndex()` currently
use `indexOfTopLevelItem` / `topLevelItem`. These need to traverse the
full tree (top-level items and their children in order) to map between
flat model indices and tree items.

### NameWidget (list_widgets.py)

Remove the 4-space text indent hack for grouped cues. The QTreeWidget
indentation handles this natively now.

### ListLayout (layout.py)

**Menu actions**: Add two actions to `menuLayout`:

- "Collapse all groups" (shortcut: `Ctrl+Shift+[`)
- "Expand all groups" (shortcut: `Ctrl+Shift+]`)

These iterate all top-level group items, set expanded/collapsed state,
and update each `GroupCue.collapsed` property.

**selected_cues**: Currently uses `indexOfTopLevelItem` to map selected
items back to model indices. Needs to handle child items that are not
top-level.

### Configuration (default.json)

Add to the list layout config section:

```json
"autoExpandOnPlay": true
```

## Drag-and-Drop

Drag-and-drop reorders cues within the same level. It does **not**
change group membership — grouping and ungrouping remain right-click
menu operations only. This avoids ambiguity about whether a drop
means "reorder" or "reparent".

Dragging a group moves the group and all its children together
(QTreeWidget handles this natively for parented items).

## Index Numbering

`CueListModel` stays flat, so indices remain sequential across all
cues. A collapsed group at index 3 with 4 children means the next
visible top-level item shows index 8. This is correct — indices
reflect true model order, which matters for OSC/MIDI triggers and
scripting.

## Standby / GO Behavior

The standby cursor skips child cues — this already works via
`_advance_standby_past_children` and the `group_id` check in `go()`.
With tree hierarchy, the cursor only lands on top-level items and
group items, consistent with children being triggered by their group.

## Edge Cases

- **Ungrouping**: Clears `group_id` on children, removes the
  `GroupCue`. View handles this via `group_id` change listener
  (reparent to top-level) and `__cueRemoved`.
- **Deleting a group**: Same as ungrouping — children get orphaned
  back to top-level.
- **Nested groups**: Not supported by the model today (`_group_cues`
  filters out `GroupCue` instances). No change needed. The design
  naturally supports it if ever enabled, since QTreeWidget supports
  arbitrary nesting.

## Out of Scope

- Drag-and-drop to change group membership
- Nested groups
- Child count badges or status summaries on collapsed groups
- Undo/redo for collapse state

## Files Changed

| File | Change |
|------|--------|
| `lisp/plugins/action_cues/group_cue.py` | Add `collapsed = Property(default=False)` |
| `lisp/plugins/list_layout/list_view.py` | Re-enable indentation; parent-aware add/move/remove; collapse state sync; auto-expand on play; tree traversal for standby |
| `lisp/plugins/list_layout/list_widgets.py` | Remove 4-space text hack from `NameWidget` |
| `lisp/plugins/list_layout/layout.py` | Add collapse/expand all menu actions with shortcuts; update `selected_cues` for child items |
| `lisp/default.json` | Add `autoExpandOnPlay: true` to list layout config |

## Testing

### Unit Tests

- Verify `GroupCue.collapsed` property serializes and restores
  correctly through the `Property` system.

### E2E Tests (via test harness plugin)

The test harness plugin exposes LiSP internals over JSON-RPC and can
drive all required scenarios:

- **Group lifecycle**: Use `cue.add` to create cues, then
  `layout.context_action` with `"Group selected"` to form groups.
  Verify child cues appear under the group.
- **Collapse/expand persistence**: Set collapsed state, use
  `session.save` / `session.load`, verify state restores.
- **Auto-expand on play**: Subscribe to group state signals via
  `signals.subscribe`, trigger group playback via `cue.execute`,
  use `signals.wait_for` to confirm state transitions.
- **Collapse all / Expand all**: Invoke the menu actions and verify
  all groups respond.
