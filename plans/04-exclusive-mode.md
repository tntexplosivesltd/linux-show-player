# Plan: Exclusive Mode ✅ Core Complete (Phase 3 optional polish remaining)

## Context

`Cue.start()` is async (`@async_function`), acquires state lock, calls `__start__()`, transitions to `CueState.Running`, emits `started` signal. No cross-cue coordination exists. Each cue has an independent state lock (`_st_lock`).

`StopAll` action cue exists but is manual — the user must place it and trigger it explicitly. `CueLayout` has `stop_all()` and `execute_all()` methods but these are also manual.

There is currently no way to say "when this cue starts, stop other playing cues."

## Design: Per-Cue Properties + Central Signal-Based Manager

### Properties on `lisp/cues/cue.py`

```python
exclusive = Property(default=False)        # Simple toggle
exclusive_group = Property(default="")     # Named group for mutual exclusivity
```

**Resolution logic:**
- `exclusive_group` is non-empty → cue belongs to that named group
- `exclusive=True` with empty `exclusive_group` → belongs to default `"__global__"` group
- Both empty/false → not exclusive (default, fully backward compatible)

This is more flexible than a global toggle:
- Different groups of cues can be independently exclusive (e.g., "background_music" vs "sound_effects")
- Some cues can opt out entirely
- Works naturally with cue groups (Plan 3) — set all children to the same `exclusive_group`

### New file: `lisp/core/exclusive_manager.py`

```python
class ExclusiveManager:
    def __init__(self, cue_model):
        self._cue_model = cue_model
        self._lock = threading.Lock()  # Serialize concurrent starts
        cue_model.item_added.connect(self._on_cue_added)
        cue_model.item_removed.connect(self._on_cue_removed)

    def _on_cue_added(self, cue):
        cue.started.connect(self._on_cue_started)

    def _on_cue_removed(self, cue):
        cue.started.disconnect(self._on_cue_started)

    def _on_cue_started(self, started_cue):
        group = self._resolve_group(started_cue)
        if not group:
            return
        with self._lock:
            for other in self._cue_model:
                if other is started_cue:
                    continue
                if other.state & CueState.IsRunning:
                    if self._resolve_group(other) == group:
                        self._stop_displaced(other)

    def _resolve_group(self, cue):
        if cue.exclusive_group:
            return cue.exclusive_group
        if cue.exclusive:
            return "__global__"
        return ""

    def _stop_displaced(self, cue):
        if cue.fadeout_duration > 0:
            cue.stop(fade=True)
        else:
            cue.stop()
```

### Instantiation in `lisp/application.py`

In `Application.__init__`, after creating CueModel:

```python
self.__exclusive_manager = ExclusiveManager(self.__cue_model)
```

## UI

### Per-cue settings

Add a section to `CueGeneralSettingsPage` (`lisp/ui/settings/cue_pages/cue_general.py`):

- Checkbox: **"Exclusive"** (maps to `exclusive` Property)
- Text field: **"Exclusive group"** (maps to `exclusive_group` Property, enabled only when "Exclusive" is checked)
- Optional: dropdown of existing group names for convenience

### App-level config

Add to `CueAppSettings` (`lisp/ui/settings/app_pages/cue.py`):

- Default exclusive stop action: Stop / FadeOutStop / Interrupt (stored in `lisp/default.json`)

### List Layout column (optional, low priority)

Small icon column in CueListView showing a lock/E icon for exclusive cues.

## Commands

No new Command subclasses needed. `exclusive` and `exclusive_group` are standard cue Properties. The existing `UpdateCueCommand` and `UpdateCuesCommand` in `lisp/command/cue.py` handle property changes with full undo/redo.

## Interaction with Cue Groups (Plan 3)

| Scenario | Behavior |
|---|---|
| Children of a GroupCue share same `exclusive_group` | Mutually exclusive within group (useful for parallel mode) |
| GroupCue itself has `exclusive_group` set | Groups compete — starting one stops another. `GroupCue.__stop__` stops all children. |
| Global exclusive (`exclusive=True`) on individual cues | All such cues are mutually exclusive regardless of group membership |

The ExclusiveManager is group-agnostic — it operates purely on individual cue Properties.

## Threading Considerations

The `started` signal fires from a worker thread (due to `@async_function` on `Cue.start()`). Therefore:

- `ExclusiveManager._on_cue_started` runs on that worker thread
- Calling `other.stop()` is safe — also `@async_function`, acquires `_st_lock` with `blocking=False`, won't deadlock
- **Race condition**: Two exclusive cues starting simultaneously on different threads could each see the other as not-yet-running. The `threading.Lock` in ExclusiveManager serializes the handler to prevent this.

## Edge Cases

| Case | Handling |
|---|---|
| Cue stopping itself | `ExclusiveManager` skips `other is started_cue` |
| CollectionCue starts multiple exclusive cues | Each triggers ExclusiveManager. Last one wins. Correct behavior. |
| StopAll cue | Not affected — ExclusiveManager only acts on `started` signals |
| Cue already fading out when new exclusive cue starts | `stop()` on a fading cue interrupts the fade and stops immediately (existing behavior) |

## Files to Modify

| File | Change |
|---|---|
| `lisp/cues/cue.py` | Add `exclusive` and `exclusive_group` Properties |
| `lisp/core/exclusive_manager.py` | **New file** — the coordinator |
| `lisp/application.py` | Import and instantiate `ExclusiveManager` |
| `lisp/ui/settings/cue_pages/cue_general.py` | Add exclusive mode UI section |
| `lisp/default.json` | Add default config for exclusive stop behavior |

## Implementation Phases

### Phase 1 — Core ✅

1. Add `exclusive` and `exclusive_group` Properties to `Cue`
2. Create `ExclusiveManager` class
3. Instantiate in `Application.__init__`

### Phase 2 — UI ✅

4. Add exclusive mode section to `CueGeneralSettingsPage`
5. Add app-level config defaults to `default.json`
6. Add app settings page for exclusive behavior defaults

### Phase 3 — Polish

7. Optional: List layout column indicator for exclusive cues
8. Optional: Batch-set exclusive group on multiple selected cues via context menu
