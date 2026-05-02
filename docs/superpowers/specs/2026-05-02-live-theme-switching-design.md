# Live Theme Switching — Design

**Date:** 2026-05-02
**Status:** Draft — ready to implement in a fresh session

## Goal

Selecting a theme in the settings dialog should apply it immediately to the running application instead of requiring a restart. Today, `BaseTheme.apply()` runs once during `lisp/main.py:main()` boot and the settings UI only persists the chosen theme name to config; the user has to close and reopen LiSP to see the change.

After this change, the round-trip is: open settings → change theme dropdown → save → UI reflows to the new theme without leaving the app.

## Non-Goals

- **Retuning the existing QSS files for cross-theme consistency.** `lisp/ui/themes/dark/theme.qss` contains hardcoded hex values (`#80AAD5`, `#404858`, `#626873`, etc.) that don't recolour with the palette. After a live switch, those chrome details will momentarily look inconsistent — the same way they look on cold load with a non-matching theme today. This is the "Phase-1 ships palette-only fidelity" caveat already documented in `2026-05-02-solarized-themes-design.md` and is out of scope here. A separate follow-up will address QSS retuning.
- **Live icon-theme switching.** `IconTheme` is set once at startup and is a separate concern from `lisp.ui.themes`. Out of scope.
- **Persisting nothing.** The chosen theme name still gets persisted to user config exactly as today; the new behaviour is purely additive (config write + immediate apply).
- **Animated transitions.** A jump-cut between themes is fine; no fade or crossfade.
- **Per-window theme overrides.** The application has one global theme; this design does not introduce per-window or per-layout themes.
- **Backward-compatibility shims for callers of `theme.apply()`.** The signature stays the same; callers don't need to change.

## Architectural Approach

Add a single `theme_changed` signal that fires whenever `BaseTheme.apply()` runs (boot or runtime). Components that cache theme-derived state subscribe to it and refresh.

The work splits into:

1. **Signal infrastructure** — new `theme_changed` signal in `lisp/ui/themes/__init__.py`, fired from `BaseTheme.apply()` at the end (after `_active = self`).
2. **Settings dialog wiring** — apply the new theme and emit immediately when the user saves the settings, instead of just writing config.
3. **Refresh hooks in stateful render sites** — list_view, cart cue_widget, and any other cache of theme-derived values.

## Architecture

### `lisp/ui/themes/__init__.py` — new signal

Add a module-level `Signal` instance:

```python
from lisp.core.signal import Signal

# Emitted after BaseTheme.apply() finishes installing the new
# palette and stylesheet on the QApplication. Subscribers should
# re-derive any cached theme-dependent state (cue brushes, cell
# stylesheets, etc.).
theme_changed = Signal()
```

The signal carries no payload — subscribers re-read whatever they need from `themes._active`, `cue_color_hex(...)`, `standby_indicator()`, etc., on each fire. Keeping the signal payload-free decouples subscribers from the active theme's identity.

**Important:** signal handlers must be bound to *named* methods, not lambdas. Per `feedback_signal_weak_refs.md` (project memory): LiSP's `lisp.core.signal.Signal` uses `weakref.WeakMethod` / `weakref.ref` for slot storage; bare lambdas get garbage-collected before the signal fires and silently disappear.

### `lisp/ui/themes/base.py` — emit on apply

At the end of `BaseTheme.apply(qt_app)`, after the existing `themes._active = self` and after the optional QSS load, fire the signal:

```python
def apply(self, qt_app):
    # ... existing palette + QSS code ...
    themes._active = self
    if self.QssPath:
        with open(self.QssPath, ...) as f:
            qt_app.setStyleSheet(f.read())
    themes.theme_changed.emit()  # ← new line
```

Boot-time emission is intentional — anything that subscribes during plugin load gets a normalised "now is the time to read theme values" signal regardless of whether it's the boot apply or a runtime swap.

### Settings dialog — apply on save

Find the settings page that hosts the theme dropdown (likely under `lisp/ui/settings/`). Today it writes the chosen theme name to `Configuration["theme.theme"]`. Add a step right after the write: look up the chosen theme via `lisp.ui.themes.get_theme(name)` and call `theme.apply(QApplication.instance())`.

Search hint: `grep -rn 'theme.theme\|themes_names\|"theme"' lisp/ui/settings/`. The class will likely be `AppGeneralSettings` or similar.

If the dropdown writes via a `Property`-style accessor, hook the apply into the same code path that writes config — don't duplicate it elsewhere.

Edge case: the user picks a theme, then *cancels* the dialog. The accept/reject flow should be: write config + apply only on accept. If the settings dialog uses a "live preview" pattern, that's also fine but introduces a "revert on cancel" requirement — keep it simple, apply on accept.

### `lisp/plugins/list_layout/list_view.py` — refresh on theme change

`__updateItemStyle(item)` reads `cue_background_hex(item.cue)`, `cue_color_alpha()`, and `themes.standby_indicator()` to compute the row brush. After a theme switch, every existing item carries a brush computed from the old theme. Add:

```python
# In CueListView.__init__, after the existing signal subscriptions:
themes.theme_changed.connect(self._on_theme_changed)

def _on_theme_changed(self):
    """Rebuild every item's brush after a theme swap."""
    for item in self.iterAllItems():
        self.__updateItemStyle(item)
    self.viewport().update()  # repaint hints (group outlines etc.)
```

`__updateItemStyle` is name-mangled (double-underscore); the dispatcher should be a public method on the class so the bound method survives weakref weakly. Use `_on_theme_changed` (single underscore — private convention but not name-mangled).

### `lisp/plugins/cart_layout/cue_widget.py` — refresh on theme change

Each `CueWidget` injects the themed hex into its stylesheet via `_resolve_cart_stylesheet(cue)` at `_setCue` time and on `_updateStyle` calls. After a theme swap, the injected hex is stale. Subscribe in `_setCue`:

```python
# In _setCue, alongside the other cue.changed(...) connects:
themes.theme_changed.connect(
    self._updateStyle, Connection.QtQueued
)
```

Reuse the existing `_updateStyle(*_args)` method (already accepts arbitrary positional args for signal-slot compatibility — see `f4161356`'s docstring).

**Lifetime concern:** `CueWidget` instances come and go (cues added/removed). The `theme_changed` signal must hold the slot via `WeakMethod` so destroyed widgets don't get called. `lisp.core.signal.Signal` already does this — connect via the standard `connect(...)` call, no special handling needed.

### Audit pass

Likely-clean (read theme values live every paint):
- `cue_background_hex(cue)` — pure function, always reads the active theme.
- `cue_color_hex(name)` — same.
- `cue_color_alpha()` — same.
- `themes.standby_indicator()` — same; consumed in `list_view.py:__updateItemStyle` which we already refresh.

Likely-needs-checking:
- The cue colour picker UI (`lisp/ui/`) — when the picker shows seven swatches, where do those swatches come from? If they cache the palette, they'll show stale colours after a theme swap. **Action:** grep for `cue_palette()`, `DEFAULT_CUE_PALETTE`, or `CUE_COLOR_NAMES` outside `lisp/ui/themes/`; for each result, decide whether the consumer reads live or caches. Subscribe to `theme_changed` if it caches.
- Anywhere `QPalette.X` colours are read into a `QBrush(...)` and stored — the `setPalette` propagation handles widgets that use the palette directly via Qt's painting, but explicit `QBrush(palette.color(...))` captures break.

Run this grep before writing code:

```bash
grep -rn "cue_palette\|DEFAULT_CUE_PALETTE\|CUE_COLOR_NAMES\|qApp.palette\|QApplication.palette" \
    lisp/ --include='*.py' | grep -v lisp/ui/themes/
```

Resolve each hit: live-read = fine; cached = subscribe to `theme_changed`.

## Phasing

1. **Phase 1 — Signal + emission.** Add `theme_changed = Signal()` in `lisp/ui/themes/__init__.py`. Fire from `BaseTheme.apply()`. No subscribers yet. Test: `BaseTheme.apply()` increments a hand-installed counter on the signal.

2. **Phase 2 — list_view refresh.** Subscribe `CueListView` to `theme_changed`; re-style every item on fire. Test: build a `CueListView` with a coloured cue, apply Dark, swap to Solarized Dark, assert the item's `background(0).color()` updated to the new palette's hex.

3. **Phase 3 — cart cue_widget refresh.** Subscribe each `CueWidget` to `theme_changed`. Reuse `_updateStyle`. Test: build a `CueWidget` with a themed cue, apply two themes in sequence, assert the widget's `styleSheet()` reflects the second theme's hex.

4. **Phase 4 — settings dialog wiring.** Find the theme-picker save path; call `theme.apply(QApplication.instance())` after writing config. Test: simulate a settings save with a new theme name, assert `themes._active` is the expected instance.

5. **Phase 5 — audit pass.** Run the grep above; for each hit, verify live vs cached; subscribe any cachers. Test: ad hoc — exercise the cue picker UI in a smoke test if it caches.

6. **Phase 6 — manual smoke test.** Launch LiSP, open settings, switch among Dark/Light/SolarizedDark/SolarizedLight in sequence; verify cue list, cart layout, settings dialog itself, status bar, group outlines all reflect the new theme without restart. Note QSS-baked hex inconsistencies as expected (out of scope).

7. **Phase 7 — voltagent QA + code-reviewer subagent review** on the worktree before merge. Same protocol as the Solarized themes branch.

## Files to touch

- `lisp/ui/themes/__init__.py` — add `theme_changed = Signal()`.
- `lisp/ui/themes/base.py` — emit the signal at end of `apply()`.
- `lisp/plugins/list_layout/list_view.py` — subscribe; add `_on_theme_changed`.
- `lisp/plugins/cart_layout/cue_widget.py` — subscribe in `_setCue`; reuse `_updateStyle`.
- `lisp/ui/settings/<theme-page>.py` — apply on save (find via grep — exact filename TBD by the implementer).
- `tests/ui/themes/test_themes.py` — new `TestThemeChangedSignal` test class for Phase 1.
- `tests/plugins/list_layout/test_list_view_color.py` — new test for Phase 2.
- `tests/plugins/cart_layout/test_cue_widget_color.py` — new test for Phase 3.

Estimated total: 6–9 source files, 60–90 net lines of production code, ~120 lines of tests.

## Risks

- **Slot lifetime issues.** LiSP's signal system uses weak refs; if a slot is bound to an unnamed lambda, it gets GC'd before the signal fires. Mitigation: use named methods only (already documented in project memory). Verified by Phase-2/3 tests that emit the signal and assert observable side effects.

- **Slot-call ordering.** If multiple components subscribe, order is non-deterministic. None of the proposed subscribers depend on each other's order (each one just refreshes its own state from the active theme). If a future subscriber introduces ordering dependencies, that's a separate design problem.

- **Settings dialog re-entrancy.** If `apply()` triggers a paint or layout that loops back into the settings dialog (unlikely but possible), the dialog could try to re-apply the theme. Mitigation: the apply call writes to `themes._active` before emitting; subsequent re-entries are idempotent. Defensive: don't call `apply()` if the chosen theme is already `_active`.

- **QSS reload doesn't repolish all widgets.** Qt's `setStyleSheet` triggers re-polish on the application, but some widgets that already have a stylesheet set via `setStyleSheet(...)` directly (like cart cells, which carry their own per-widget stylesheet) won't pick up the new global QSS automatically. The Phase-3 cart-widget refresh covers cart cells; the rest of the chrome should follow Qt's automatic propagation. If specific widgets stay stale after Phase 6 manual testing, list them and decide per-widget.

## Acceptance criteria

- The theme dropdown in settings, when changed and saved, applies the new palette + QSS to the running application without restart.
- After a switch, every visible cue row in the list layout repaints with the new theme's `cue_color_hex(name)` and `cue_color_alpha()`.
- After a switch, every cart cue widget repaints with the new theme's hex.
- The standby cue band repaints with the new theme's `standby_indicator()`.
- All existing tests pass; new tests cover Phases 1–3.
- Theme persistence behaviour is unchanged: the chosen theme name is written to user config exactly as today and applied at boot exactly as today.
- No new warnings in `lisp.core.signal` logger after multiple switches in a row (catches stale weakref warnings or slot-resolution failures).

## Out of scope (deferred to follow-up)

- QSS retuning so chrome details (toast accents, splitters, panel borders) recolour with the palette. The off-palette hex values in `dark/theme.qss` and `light/theme.qss` will appear inconsistent immediately after a live switch until restart. The same caveat applies to cold-load-time non-matching themes today.

## Implementation notes for the next agent

Start by running the worktree skill to set up an isolated branch off master:

```
.worktrees/feat-live-theme-switch
```

Implement with TDD: write the test for each phase, watch it fail, then write the production code. Phase 1's test is the easiest entry point — it doesn't require any widget construction, just hooking a counter onto the signal and asserting `BaseTheme.apply()` increments it.

The settings dialog hookup (Phase 4) is the only phase that requires hunting through the codebase to find the right call site. Budget extra time for that and surface the exact file you found in your commit message so future readers can navigate.

Run the same QA + code-reviewer subagent pair as Phase 7 before merging.
