# Cue Target Warning Indicator — Design

**Date**: 2026-05-02
**Status**: Draft, awaiting user review
**Author**: brainstormed with Claude

## Problem

Several LiSP cue types reference another cue by id (`target_id`) and silently
do nothing at runtime when that target is empty or no longer exists. There is
no visual signal in the list view, the cart view, or the cue's inspector that
the cue is misconfigured. A user can save and ship a session with a Stop cue
or Volume cue that will never fire, and discover the problem only during a
show.

This design adds a single warning indicator across all three surfaces, driven
by a small reusable check on the cue itself.

## Scope

### Cue types affected

The complete set of cues that resolve a target by id:

| Cue | Target shape | Notes |
|---|---|---|
| `StopCue` | single `target_id` | covers Fade Out and Stop / Pause via the `action` enum |
| `ResumeCue` | single `target_id` | covers Fade In and Resume via the `action` enum |
| `SeekCue` | single `target_id` | |
| `VolumeControl` | single `target_id` | always a fade |
| `CollectionCue` | list of `(target_id, action)` rows | warns if *any* row is empty/dangling |

There is no separate `FadeAndStopCue` or `FadeAndResumeCue` class — the fade
variants are `CueAction` enum values inside `StopCue` / `ResumeCue` and share
the same `target_id` property.

`GroupCue` is intentionally excluded: groups own their children via `group_id`
on the children, not via a `target_id`.

### What counts as "no target"

Both conditions trigger the indicator and are treated identically:

1. **Empty** — `target_id == ""` (user has not picked a target).
2. **Dangling** — `target_id` is set, but `cue_model.get(target_id)` returns
   `None` (target was deleted, or session reference is stale).

For `CollectionCue`, the indicator triggers if at least one row is empty or
dangling, OR if the list is empty.

The visual indicator is identical for both cases. The hover tooltip and the
inspector message *do* differentiate them so the user knows how to fix.

## Architecture

### `TargetingCue` mixin

A new mixin in `lisp/cues/targeting.py` centralizes the validity check and
its reactivity:

```python
class TargetingCue:
    invalid_target = Property(default=False)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.changed("target_id").connect(self._recheck_target)
        self.app.cue_model.item_added.connect(self._on_model_change)
        self.app.cue_model.item_removed.connect(self._on_model_change)
        self._recheck_target()

    def _resolve_targets(self) -> bool:
        """True if all targets resolve. Override for list-style cues."""
        if not self.target_id:
            return False
        return self.app.cue_model.get(self.target_id) is not None

    def _recheck_target(self, *_):
        invalid = not self._resolve_targets()
        if invalid != self.invalid_target:
            self.invalid_target = invalid  # emits changed("invalid_target")

    def _on_model_change(self, cue):
        if cue.id == self.target_id or self.invalid_target:
            self._recheck_target()
```

Widgets subscribe to `cue.changed("invalid_target")` — the same signal idiom
already used throughout LiSP (e.g. `cue.changed("icon")` in `CueStatusIcons`).
No bespoke signal is added.

`CollectionCue` overrides `_resolve_targets()`:

```python
def _resolve_targets(self) -> bool:
    if not self.targets:
        return False
    model = self.app.cue_model
    return all(tid and model.get(tid) is not None for tid, _ in self.targets)
```

`CollectionCue` additionally connects to its `collectionModel` row-changed
signal (exact name verified in Phase 0) so that adding/removing rows in the
inspector re-runs the check.

### Why a mixin

With 5 cue types and 3 widget surfaces, per-widget subscription is 15
connection points. The mixin centralizes the rule in one place, makes
"is this cue's target valid?" queryable from anywhere with a single property
read, and emits a single signal. It also gives `CollectionCue` a clean
override hook for list semantics.

### Reactivity, lifecycle, weak refs

LiSP signals use weak references (per project memory: see
`feedback_signal_weak_refs`). The mixin's connections drop automatically when
the cue is destroyed. Widgets connecting to `cue.changed("invalid_target")`
MUST bind a named method, not a lambda — same rule that already applies in
`CueStatusIcons`.

`cue_model` is a singleton living for the app's lifetime, so its connections
do not need teardown.

### Initial state on session load

Cues are constructed during session restore *before* all targets exist. The
first `_recheck_target()` in `__init__` will mark them as invalid; the later
`cue_model.item_added` signals (as targets load in) will flip them back to
valid. The indicator is briefly visible during load. This is acceptable
because the UI isn't interactive yet, but is documented behavior.

### `self.app` ordering caveat

If `self.app` is not yet wired up when `TargetingCue.__init__` runs, the
mixin defers connection (e.g. on first `Property` `changed` emission, or via
a one-shot `QTimer.singleShot(0, ...)` on the main thread). Phase 0 spike
will determine which approach is needed.

## Visual rendering

### List layout

Extend `CueStatusIcons.paintEvent` (`lisp/plugins/list_layout/list_widgets.py:181`).
After painting the cue icon, if `cue.invalid_target` is True, paint a
`dialog-warning` glyph (≈40% of the icon size) in the bottom-right corner of
the icon rect. Set the widget `toolTip` to the appropriate string. Subscribe
to `cue.changed("invalid_target")` to repaint and refresh the tooltip.

### Cart layout

Extend the cue widget's painting (`lisp/plugins/cart_layout/cue_widget.py`).
Same corner-badge approach, scaled to the cart cell size. Same tooltip. The
badge can be slightly larger relative to the icon since cart cells are bigger.

### Inspector

Each cue's settings page draws its own target picker. For invalidity:

- Thin red outline (Qt stylesheet `border: 1px solid <red>`) on the picker
  control.
- Small `dialog-warning` icon next to the picker label.
- One-line warning text below the picker that distinguishes the two cases:
  - "Target cue is not set" — when `target_id` is empty.
  - "Target cue no longer exists. Pick a new target." — when dangling.

For `CollectionCue`'s inspector: the picker is a table of rows. Highlight
each invalid row's target cell with the red outline; show a single summary
line "N invalid target(s)" below the table.

### Icon source

`IconTheme.get("dialog-warning")` — Numix already ships this glyph in the
theme LiSP bundles. Verified in Phase 0; if missing, fall back to a small
painted triangle (similar to existing ad-hoc painting in `cue_widget.py`).

### i18n

Three new translatable strings, all via `translate()` from `lisp.ui.ui_utils`:

- `"Target cue is not set"`
- `"Target cue no longer exists"`
- `"Collection has invalid target(s)"`

`i18n_update.py` picks these up on next run.

## Testing

### Unit tests — `tests/cues/test_targeting.py` (new)

Use the existing `mock_app` fixture from `tests/conftest.py`.

- Empty `target_id` → `invalid_target` is True.
- Set `target_id` to an existing cue's id → `invalid_target` flips to False;
  `target_validity_changed` fires once.
- Delete the target cue from the model → `invalid_target` flips back to
  True; signal fires.
- Re-add a cue with the same id → `invalid_target` flips to False; signal
  fires.
- `CollectionCue`: empty list → invalid; one valid + one dangling row →
  invalid; all valid → valid; remove the dangling row → flips to valid.
- `changed("invalid_target")` does NOT fire when state is unchanged (covers
  the `if invalid != self.invalid_target` guard).

### E2E tests — `tests/e2e/test_target_validity.py` (new, standalone script)

Per project memory `feedback_e2e_tests`: E2E tests run as standalone
scripts, not via pytest; they launch LiSP themselves.

- Add a `StopCue` with no target via `cue.add` → query `cue.list` and assert
  `invalid_target` is True (the harness will be extended to expose it).
- Add a target cue, set the StopCue's `target_id`, assert flip to False.
- Delete the target cue, assert flip back to True.
- `signals.subscribe` on the cue's `changed("invalid_target")` and
  `signals.wait_for` to verify the signal arrives.

### Visual verification

Launch LiSP and exercise all four scenarios:

1. Cue with empty `target_id` → corner badge visible, tooltip shows "Target
   cue is not set".
2. Cue with valid `target_id` → no badge.
3. Cue whose target was deleted → badge appears, tooltip shows "Target cue
   no longer exists".
4. `CollectionCue` with one valid + one dangling row → badge visible,
   tooltip shows "Collection has invalid target(s)"; inspector highlights
   the dangling row only.

If visual verification cannot be completed in the dev environment, that is
stated explicitly in the final report rather than glossed over (per
CLAUDE.md).

### Out of scope

Pixel-level visual regression testing is not set up in this repo and is not
introduced for this feature. The `paintEvent` change is small enough to
review directly.

## Risks & edge cases

1. **Plugin-disable safety**. The mixin defends against missing
   `self.app.cue_model` (e.g. tests using `mock_app`) with a `try/except
   AttributeError` on subscription.
2. **Performance**. `_recheck_target()` runs on every `cue_model.item_added`
   / `item_removed`. With N targeting cues, that is O(N) work per change.
   Mitigated by the `if cue.id == self.target_id or self.invalid_target`
   early exit — sub-microsecond per cue.
3. **Self-target** (`target_id == self.id`). Currently legal in LiSP. The
   mixin treats it as valid (it resolves). No regression introduced; not
   our problem to police.
4. **GroupCue** is excluded. Groups use `group_id` on children, not
   `target_id`.
5. **Backward compat**. `invalid_target` is a derived `Property`. It will
   be serialized to disk unless explicitly skipped. Phase 0 verifies the
   skip idiom; otherwise we accept the small extra field.
6. **i18n**. Three new strings — `i18n_update.py` picks them up on next run.

## File changes

### New

- `lisp/cues/targeting.py` — `TargetingCue` mixin (~60 lines).
- `tests/cues/test_targeting.py` — unit tests.
- `tests/e2e/test_target_validity.py` — E2E script.

### Modified

- `lisp/plugins/action_cues/stop_cue.py` — add `TargetingCue` to MRO.
- `lisp/plugins/action_cues/resume_cue.py` — same.
- `lisp/plugins/action_cues/seek_cue.py` — same.
- `lisp/plugins/action_cues/volume_control.py` — same.
- `lisp/plugins/action_cues/collection_cue.py` — add `TargetingCue`,
  override `_resolve_targets()`, wire `collectionModel` row-changed signal.
- `lisp/plugins/list_layout/list_widgets.py` — `CueStatusIcons` badge
  painting + tooltip + signal subscription.
- `lisp/plugins/cart_layout/cue_widget.py` — same treatment for the cart cell.
- 5 settings pages (one per cue type) — red outline + warning text on the
  target picker. `CollectionCue` settings: per-row outline.
- `lisp/plugins/test_harness/` — expose `invalid_target` so E2E can read it.

## Build sequence

- **Phase 0** — Worktree setup; Phase 0 spikes:
  - Create isolated worktree off `master` via `superpowers:using-git-worktrees`.
  - Spike `targeting.py` to confirm `Application` is reachable from
    `Cue.__init__`.
  - Verify `dialog-warning` icon exists in the bundled Numix theme.
  - Verify the `Property` serialization-skip idiom (or accept the extra field).
- **Phase 1** — `TargetingCue` mixin + unit tests against `mock_app`. No UI.
- **Phase 2** — List layout indicator (`CueStatusIcons` paint + tooltip).
- **Phase 3** — Cart layout indicator.
- **Phase 4** — Inspector indicators (5 settings pages).
- **Phase 5** — Test harness exposure + E2E test + visual verification (run
  LiSP, exercise all four scenarios) + `i18n_update.py`.
- **Phase 6 — Review**:
  - `voltagent-qa-sec:qa-expert` validates the feature end-to-end against
    this spec.
  - `voltagent-qa-sec:code-reviewer` reviews the diff against the spec,
    CLAUDE.md conventions (weak-ref signals, named handlers, GPL header,
    ruff 80-char), and flags any mismatch.
  - Address findings.
  - Merge per `feedback_rebase_not_merge`: rebase the worktree branch onto
    current master first, then `git merge --no-ff`.

## Non-goals

- A "warnings panel" listing all issues across the session. The per-cue
  indicator + tooltip is sufficient and matches existing LiSP UI density.
- Distinguishing dangling vs empty in the *icon* (only in the tooltip /
  inspector text). Per user decision (option C earlier in brainstorming).
- Validating other cue references such as `GroupCue.group_id` on children.
- Auto-fixing dangling references (e.g. picking a similarly-named replacement).
