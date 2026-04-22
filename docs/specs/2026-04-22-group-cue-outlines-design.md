# Group Cue Outlines in List Layout

## Overview

Draw a coloured rounded-rectangle outline around each `GroupCue` header
and its child cues in the list layout, to make group boundaries
visually obvious at a glance — similar to QLab's group brackets, but
using a full enclosing rectangle.

The outline colour encodes the group's playback mode:

- **Parallel** groups → green
- **Playlist** groups → orange

This adds a semantic signal (mode) on top of the structural signal
(grouping), with no new controls or settings.

## Decisions

- **Shape**: Full rounded rectangle enclosing the group header and
  all of its children (when expanded) or just the header (when
  collapsed).
- **Colour source**: Driven by `GroupCue.group_mode`, not by the
  per-cue `stylesheet` tint. Stylesheet tint keeps its existing
  row-background meaning; mode colour is a separate visual channel.
- **Palette**:
  - Parallel: `QColor(76, 175, 80, 200)` — muted green.
  - Playlist: `QColor(255, 152, 0, 200)` — muted orange.
  - Alpha ~78% so the stroke reads cleanly over selection and
    current-item highlights without being harsh.
- **Collapsed groups**: Still outlined, around the header row only.
  Keeps "this is a group" consistent whether expanded or folded.
- **Running state**: No change — outline stays the same colour
  regardless of playback state. Per-cue status is already shown via
  `CueStatusIcons` and row highlighting.
- **Implementation**: Override `CueListView.paintEvent` and draw
  outlines on the viewport after the base class renders the rows. No
  custom delegate, no new widget.

## Architecture

All changes are contained in
`lisp/plugins/list_layout/list_view.py`. No new files, classes, or
signals.

### New constants on `CueListView`

```python
GROUP_OUTLINE_WIDTH = 2
GROUP_OUTLINE_RADIUS = 4
GROUP_OUTLINE_PARALLEL = QColor(76, 175, 80, 200)
GROUP_OUTLINE_PLAYLIST = QColor(255, 152, 0, 200)
GROUP_OUTLINE_COLORS = {
    "parallel": GROUP_OUTLINE_PARALLEL,
    "playlist": GROUP_OUTLINE_PLAYLIST,
}
```

### New methods

**`paintEvent(self, event)`** — calls `super().paintEvent(event)`
first, then iterates `self._group_items.values()` and paints one
rounded rectangle per group whose rect intersects the viewport.

```python
def paintEvent(self, event):
    super().paintEvent(event)

    painter = QPainter(self.viewport())
    painter.setRenderHint(QPainter.Antialiasing)
    pen = QPen()
    pen.setWidth(self.GROUP_OUTLINE_WIDTH)

    viewport_rect = self.viewport().rect()
    for group_item in self._group_items.values():
        color = self.GROUP_OUTLINE_COLORS.get(
            group_item.cue.group_mode
        )
        if color is None:
            continue

        rect = self._groupOutlineRect(group_item)
        if rect is None or not rect.intersects(viewport_rect):
            continue

        pen.setColor(color)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(
            rect,
            self.GROUP_OUTLINE_RADIUS,
            self.GROUP_OUTLINE_RADIUS,
        )
```

**`_groupOutlineRect(self, group_item)`** — union of the visible rows
for the group, inset (by `GROUP_OUTLINE_WIDTH // 2 + 1` pixels) so the
stroke sits fully inside the cell edges rather than being clipped by
the viewport or the neighbouring row.

```python
def _groupOutlineRect(self, group_item):
    header = self.visualItemRect(group_item)
    if header.isEmpty():
        return None

    rect = QRect(header)
    if group_item.isExpanded() and group_item.childCount() > 0:
        last_child = group_item.child(group_item.childCount() - 1)
        child_rect = self.visualItemRect(last_child)
        if not child_rect.isEmpty():
            rect = rect.united(child_rect)

    inset = self.GROUP_OUTLINE_WIDTH // 2 + 1
    rect.adjust(inset, inset, -inset, -inset)
    return rect
```

`visualItemRect()` returns empty for items scrolled out of view or
whose parent is collapsed, so those cases drop out naturally.

### Repaint wiring

Three existing handlers gain a single `self.viewport().update()`
call:

1. **`__itemExpanded`** — group expanded, bounds grew.
2. **`__itemCollapsed`** — group collapsed, bounds shrunk.
3. **`__cuePropChanged`** — extended with
   `if property_name == "group_mode": self.viewport().update()`.

All other repaint triggers (scroll, resize, selection change, model
add/remove/move, `group_id` reparent) already drive
`QTreeWidget.paintEvent` via Qt's own machinery — no extra wiring
needed.

## Edge Cases

| Case | Behaviour |
|------|-----------|
| Empty group, expanded | Header-only rect (`childCount() == 0`). |
| Empty group, collapsed | Header-only rect (`isExpanded() == False`). |
| Group fully scrolled out of viewport | `visualItemRect()` empty → skip. |
| Header above viewport, last child visible | Union rect extends above viewport; Qt clips; top edge not drawn. Reads as "group continues above". |
| Unknown `group_mode` (future third mode) | `.get()` returns `None` → skip drawing, no crash. |
| Child dragged out of group (`group_id` cleared) | Existing `__cueGroupChanged` path runs; tree updates; next paint picks up new bounds. |
| Group deleted | Existing `__cueRemoved` pops from `_group_items`; next paint sees no entry. |
| Selection / current-item highlight on a child row | Row background paints first; outline paints over it at ~78% alpha. Both readable. |
| Drag-and-drop in progress | Qt's drop indicator paints after `paintEvent`; sits on top of the outline. Correct. |

## Out of Scope

- Theme-aware palette. One palette is used for both the light and
  dark themes LiSP ships. Can be revisited if users report contrast
  problems.
- Running-state visual emphasis (thicker stroke or brighter colour
  while a group is executing).
- Nested groups. The data model currently disallows them; no
  behaviour to specify.
- Per-user palette configuration.
- Outlines in the cart layout. Cart layout has a different visual
  structure and is not part of this feature.

## Files Changed

| File | Change |
|------|--------|
| `lisp/plugins/list_layout/list_view.py` | Add outline constants, `paintEvent` override, `_groupOutlineRect` helper; add `viewport().update()` calls to `__itemExpanded`, `__itemCollapsed`, and `__cuePropChanged` (new `group_mode` branch). |

## Testing

### Unit Tests

New file: `tests/plugins/list_layout/test_group_outline.py`
(directory may need creating).

Using the `mock_app` fixture from `tests/conftest.py` and
`pytest-qt`:

1. `_groupOutlineRect` returns `None` for a group whose header's
   `visualItemRect()` is empty.
2. `_groupOutlineRect` returns a header-only rect when the group is
   collapsed, even if it has children.
3. `_groupOutlineRect` returns a header-only rect when the group is
   expanded but has no children.
4. `_groupOutlineRect` returns the union of header + last-child
   rects when the group is expanded with children.
5. `GROUP_OUTLINE_COLORS.get("unknown_mode")` is `None`.

Tests that depend on real geometry need `view.show()` +
`qtbot.waitExposed(view)` so `visualItemRect()` returns non-empty
values. If this proves brittle in headless CI, mark the affected
tests `@pytest.mark.gui`.

### E2E Tests (via `test_harness` plugin)

New standalone script: `tests/e2e/test_group_outlines.py`, run
directly (not under pytest), following the existing E2E pattern.
Cannot assert pixels, but verifies the wiring that should trigger
repaints does not crash:

1. Add a parallel `GroupCue` with two child cues → assert tree state
   via `cue.list` / `session.info`.
2. Update `group_mode` to `"playlist"` via `cue.update` → assert
   property change lands and no exception is raised on the main
   thread.
3. Collapse the group via property write → assert `collapsed == True`
   and no crash.
4. Ungroup via `layout.context_action` → assert children reparent to
   top-level and the group is gone.

### Manual Verification

Per `CLAUDE.md`, UI changes require running the app and visually
checking:

- Parallel group → green outline; playlist group → orange outline.
- Collapse/expand toggles outline size in sync.
- Changing `group_mode` in the group settings flips the colour
  immediately.
- Scrolling, resizing, drag-and-drop, selection highlight, and
  current-item highlight all render correctly with the outline
  present.
- Dark and light themes both look acceptable.
