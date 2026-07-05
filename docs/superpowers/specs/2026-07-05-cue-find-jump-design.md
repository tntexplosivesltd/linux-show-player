# Cue Find & Jump bar (list layout) — Design

**Date:** 2026-07-05
**Status:** Approved (brainstorm), pending implementation plan
**Todo item:** *Cue search / filter bar* (`docs/todo.md`, UI/UX section)

## Problem

In shows with hundreds of cues, an operator cannot quickly locate a cue by
name or `cue_number` without scrolling the list layout. There is no search
affordance today.

## Goal

A **find & jump** bar (browser-"find" style) for the list layout:

- Text query matches a cue's **name** *or* **cue_number** (case-insensitive
  substring).
- An optional **colour** swatch narrows matches to a single canonical cue
  colour (AND with the text query).
- All rows stay visible; **non-matching rows are dimmed** so matches stand
  out. Enter / Shift+Enter (and ▶/◀ buttons) jump the **standby cursor**
  forward / backward through matches, **wrapping** at the ends.
- Opened with **Ctrl+F** (plus a Layout-menu entry); **Escape** closes it,
  clears dimming, and returns focus to the cue list.

This is deliberately *not* a filter-that-hides mode — see "Out of scope".

## Non-goals / Out of scope

- Filter/hide mode (hiding non-matching rows).
- Saved searches, search history, regex.
- Matching fields other than name / cue_number / colour (e.g. notes, file
  path, cue type).
- Persisting search state to the session file.
- A find bar in the cart layout (different navigation model).

## Existing infrastructure this builds on

- **List layout** is a `QTreeWidget` (`CueListView`, no `QAbstractItemModel`);
  rows are `CueTreeWidgetItem`s, iterated via `iterAllItems()`
  (`list_view.py`). GroupCues nest as child items.
- **Ordered model:** `CueListModel` (`list_layout/models.py`) — iterate in
  visual order; each cue's `.index` is kept in sync.
- **Cue properties** (base class, `lisp/cues/cue.py`): `name`, `cue_number`
  (free-form string), `color_name` (canonical, theme-independent, one of
  `CUE_COLOR_NAMES`; empty for legacy cues).
- **Navigation:** `ListLayout.set_standby_index(index)` sets the tree's
  current item and auto-scrolls it to centre — the same path GO uses.
  `cueItemAt(index)` resolves a flat index to a (possibly nested) tree item.
- **Colour widget:** `CueColorPalette` (`lisp/ui/widgets/cue_color_palette.py`)
  — a reusable row of swatches ("No color" + 7 names) emitting `colorPicked`.
- **Row rendering:** `CueListView.__updateItemStyle` sets each row's
  **background** from `cue_background_hex(cue)`. The Q#/name cells are
  **`QLabel` widgets** installed via `setItemWidget`, *not* item display text.

## Architecture

Three new/changed units; match logic is a pure, Qt-free core.

### 1. `lisp/plugins/list_layout/find.py` (new, pure — no Qt)

The testable match core.

```python
def find_matches(ordered_cues, text, color_name):
    """Return the list of matching cue indices in list order.

    A cue matches when:
      - text is empty OR (case-insensitive) text is a substring of the
        cue's name OR of its cue_number, AND
      - color_name is empty OR cue.color_name == color_name.
    When both text and color_name are empty, returns [] (search inactive).
    """
```

- `ordered_cues` is any ordered iterable of cues (the `CueListModel`).
- Returns the cues' `.index` values, in list order.
- No Qt import; unit-tested in isolation.

### 2. `FindBar(QWidget)` (new — presentation only)

Lives in the list_layout package. Holds **no** cue knowledge.

Widgets:
- `QLineEdit` — placeholder "Find cue by name or number".
- A `CueColorPalette` (reused) for the colour swatch.
- ◀ / ▶ prev/next buttons.
- A match-counter `QLabel` — "2/7" (current / total), blank when inactive.
- A close button.

Signals emitted:
- `queryChanged(str)` — on text edit.
- `colorChanged(str)` — canonical colour name, "" for none.
- `findNext()`, `findPrev()`.
- `closed()`.

Behaviour it owns:
- Enter → `findNext`; Shift+Enter → `findPrev`; Escape → `closed`.
- `setMatchCounter(current, total)` and an invalid-state tint on the text
  field when `total == 0` with a non-empty query.
- `focusQuery()` — focus + select-all in the text field (used on open).

### 3. `ListLayout` (controller — existing, extended)

Owns all wiring and state:

- Instantiates `FindBar` (hidden), inserted into the view above the cue list.
- Adds a Layout-menu `QAction` "Find cue…" with shortcut **Ctrl+F** that
  toggles the bar and calls `focusQuery()`. Registered in the menu-build and
  `retranslate()` paths like the other layout actions.
- Holds search state: `text`, `color_name`, `matches: list[int]`,
  `current_match: int` (index into `matches`).
- On `queryChanged` / `colorChanged`: recompute
  `matches = find_matches(self._list_model, text, color_name)`; update the
  counter; call `view.set_search_dim(match_ids, active=bool(text or color))`;
  reset `current_match` to the first match at/after the current standby index
  (or 0).
- On `findNext` / `findPrev`: advance `current_match` with wrap-around, then
  `set_standby_index(matches[current_match])`; expand ancestor groups of the
  target if collapsed (reuse `setExpanded`) so the revealed row is visible;
  update the counter to `current_match+1 / len(matches)`.
- On `closed`: `view.set_search_dim(set(), active=False)`, hide the bar,
  return focus to the cue list. Standby stays where the last jump left it.
- Keep search results coherent while open: on model add/move/remove signals,
  recompute matches and re-apply dimming.

### 4. `CueListView.set_search_dim(matching_cue_ids: set, active: bool)` (new)

The one new view capability. Because the visible Q#/name cells are `QLabel`
widgets (not item display text), dimming acts on the **row's cell widgets**,
not `QTreeWidgetItem.setForeground`.

- `active=True`: for each visible row whose cue id ∉ `matching_cue_ids`, apply
  a light dim (e.g. a `QGraphicsOpacityEffect` at ~0.4 on the row's cell
  widgets, or a cached palette/stylesheet dim — the plan picks whichever
  composes cleanly with the cue-colour background and the standby indicator).
  Matching rows render normally.
- `active=False`: clear all dim effects and restore normal rendering.
- Idempotent; safe to call repeatedly as matches change.

## Data flow

1. Operator types / picks a colour → `FindBar` emits `queryChanged` /
   `colorChanged` → `ListLayout` recomputes `matches`, updates counter, calls
   `view.set_search_dim(...)`, resets `current_match`.
2. Enter / ▶ (or Shift+Enter / ◀) → `ListLayout` advances `current_match`
   (wrapping), `set_standby_index(matches[current_match])` (auto-scrolls to
   centre, expands ancestor groups), updates counter.
3. Zero matches → no dimming applied, counter "0/0", text field tinted
   invalid; the list stays fully readable.
4. Escape → dimming cleared, bar hidden, focus returned to the list.

## Error handling / edge cases

- **Empty query and no colour:** search inactive — no dimming, counter blank.
- **Zero matches:** no dimming, "0/0", invalid tint; next/prev are no-ops.
- **Nested matches in a collapsed group:** jumping expands ancestors so the
  target row is visible; dimming still applies to non-matches once revealed.
- **Model changes while bar open** (cue added/removed/moved): recompute and
  re-apply so the counter and dimming stay correct.
- **Selection mode on/off:** jumping uses `set_standby_index` (current item),
  which works in both `NoSelection` and `ExtendedSelection` modes.

## Testing

### Unit (`tests/plugins/list_layout/`)

- `test_find.py` — pure `find_matches`: name-substring, cue_number-substring,
  case-insensitivity, colour AND, empty-query inactivity, ordering of results.
- View dimming test using the existing `_build_view_with_cue` helper pattern
  (`test_list_view_color.py`): assert `set_search_dim` dims exactly the
  non-matching rows and that `active=False` restores them cleanly.

### E2E (`tests/e2e/`)

- Add harness method `layout.find` in `handlers.py` (set text/colour; return
  ordered matching indices + current standby index), dispatched on the main
  thread via `invoke_on_main_thread`.
- Add `color_name` to `serialize_cue_brief` (`serializers.py`) for colour
  assertions.
- `test_cue_find_e2e.py`: type query → assert matches; next/prev wrap →
  standby moves; colour narrows matches; Escape clears.

## Files touched (anticipated)

- **New:** `lisp/plugins/list_layout/find.py`, `FindBar` widget (new module in
  `list_layout/`), `tests/plugins/list_layout/test_find.py`,
  `tests/e2e/test_cue_find_e2e.py`.
- **Changed:** `lisp/plugins/list_layout/layout.py` (wiring, menu action,
  search state), `lisp/plugins/list_layout/view.py` (insert the bar),
  `lisp/plugins/list_layout/list_view.py` (`set_search_dim`),
  `lisp/plugins/test_harness/handlers.py` + `serializers.py` (E2E surface).

## Decisions made during brainstorm

- Behaviour: **find & jump** (not filter/hide).
- Match fields: **name + cue_number** via text; **colour** via a separate
  swatch, AND-combined.
- Match display: **dim non-matches** (background stays the cue colour).
- Invocation: **Ctrl+F** toggle, hidden by default; Escape closes.
- Next/prev **wrap around**; a **match counter** ("2/7") is shown.
