# Plan: Cue Groups ✅ Complete

## Context

CueModel is a flat `{id: cue}` dict. There is no hierarchy, nesting, or parent-child concept. The user wants QLab-style groups, starting with Parallel and Playlist modes, with optional crossfading.

## Modes to Implement Now

### Parallel
Start all children simultaneously. Equivalent to QLab's "Timeline" group.

### Playlist
Play children sequentially, one after another, with optional looping and optional crossfading between tracks. The playhead advances past the group when it starts. Designed for pre-show/intermission music.

## Design: Flat Model + Hierarchy Properties

**Keep CueModel flat.** All cues — including group children — live in the same `{id: cue}` dict.

### `lisp/cues/cue.py` — Add property

```python
group_id = Property(default="")  # Parent group's cue id, or "" if top-level
```

Serialized automatically by HasProperties — no session format changes needed.

### New file: `lisp/cues/group_cue.py`

```python
class GroupCue(Cue):
    Name = QT_TRANSLATE_NOOP("CueName", "Group")

    CueActions = (
        CueAction.Default,
        CueAction.Start,
        CueAction.Stop,
        CueAction.Pause,
        CueAction.Resume,
        CueAction.Interrupt,
    )

    children = Property(default=[])
    group_mode = Property(default="parallel")  # "parallel" or "playlist"
    loop = Property(default=False)             # Playlist: loop back to start
    crossfade = Property(default=0.0)          # Playlist: crossfade seconds
```

#### Parallel mode (`__start__`)
- Start all children simultaneously
- Group remains Running until last child ends
- Stopping the group stops all children

#### Playlist mode (`__start__`)
- Start first child
- When child ends, start next child
- If `crossfade > 0`, start next child `crossfade` seconds before current ends (fade out current, fade in next)
- If `loop` is True, wrap around to first child after last
- Stopping the group stops the current child

### Registration

Register GroupCue in CueFactory from the `action_cues` plugin, consistent with existing action cue pattern.

## List Layout Changes

`CueListView` already uses `QTreeWidget` — it natively supports parent-child items.

| File | Change |
|---|---|
| `list_view.py` line 125 | Change `setIndentation(0)` → `setIndentation(20)` |
| `list_view.py` `__cueAdded` | If `cue.group_id` is set, add as child of group's QTreeWidgetItem |
| `list_view.py` | Expand/collapse for GroupCue items (default: expanded) |
| `list_view.py` | GroupCue rows get folder icon, bold text |
| `models.py` | CueListModel keeps flat list; hierarchy is visual only |

## Cart Layout

GroupCue occupies one grid cell. Clicking starts all children (parallel) or starts playlist. No structural changes to CueCartModel.

## Commands (`lisp/command/group.py`)

- `GroupCuesCommand` — Set `group_id` on selected cues, update `GroupCue.children`
- `UngroupCuesCommand` — Clear `group_id`, remove GroupCue

## Context Menu

- **"Group Selected"** — Create GroupCue containing selected cues
- **"Ungroup"** — Dissolve group, promote children to top level

## Session Format

No structural changes. `group_id` and `children` are Properties serialized automatically. Ordering: GroupCue appears before its children in the array (naturally true from layout order).

## Key Interactions

| Interaction | Handling |
|---|---|
| CueNextAction chaining | `__cue_next` must be group-aware: in playlist mode, "next" is next child in group |
| Drag and drop | Extend `dropEvent` for dropping into/out of groups |
| RunningCueModel | No changes — tracks by signals |
| Exclusive mode | An exclusive GroupCue blocks other cue starts while any of its children play |
| StopAll | Stops all cues including group children (they're in the flat model) |

## Crossfading (Playlist mode)

When `crossfade > 0`:
- Monitor current child's remaining time
- When remaining time <= crossfade duration, start next child with fade-in
- Simultaneously fade out current child
- Uses existing `Cue.fadein_duration`/`fadeout_duration` on the children, or the group's `crossfade` value as override

## Implementation Phases

### Phase 1 — Core ✅
1. Add `group_id` Property to Cue
2. Create GroupCue class with parallel + playlist modes
3. Register in CueFactory
4. Create group Command classes

### Phase 2 — List Layout UI ✅
5. Indentation, parent-child items, expand/collapse
6. Group-aware `__cue_next`
7. Drag-and-drop for groups
8. Context menu (Group Selected, Ungroup)

### Phase 3 — Playlist features ✅
9. Crossfade support
10. Loop support
11. GroupCue settings page (mode selector, crossfade, loop)

### Phase 4 — Polish ✅
12. Group icon
13. Edge cases: deleting a group, nested groups (disallow initially)

---

## Future Modes (Not Implementing Now)

### Sequence ("Start First" in QLab)
Start first child, playhead advances past the group. Children chain internally via auto-continue. The group runs independently while the operator continues triggering other cues.

### Shuffle ("Start Random" in QLab)
Each trigger plays a random un-played child. Cycles through all children before repeating (round-robin). Use case: varied sound effects (doorbells, gunshots, thunder) — prevents the same recording from playing twice in a row.

Could be implemented as:
- A standalone mode, or
- A `shuffle` boolean flag on Playlist mode (shuffled playlist for pre-show music)

### Organizational ("Start First And Enter" in QLab)
Pure visual grouping — collapse/expand without changing playback behavior. Children behave as if ungrouped. This is automatically available with any group mode since collapse/expand is a UI feature.
