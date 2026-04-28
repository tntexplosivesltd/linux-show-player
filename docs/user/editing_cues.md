# Editing cues

Cue properties are edited in the **inspector** — a panel docked below
the cue layout. Selecting a cue binds the inspector to it; edits are
written back live as you make them.

```{image} _static/inspector_overview.png
:alt: Inspector panel docked below the cue layout
```

[screenshot: main window showing the cue layout on top and the inspector
panel below, with a cue selected and the inspector showing its General
page]

## Showing and hiding the inspector

* **Show / hide:** `View > Show Inspector` or ``[F4]``
* The panel is separated from the layout by a draggable splitter — drag
  the divider to give the inspector more or less space.
* The visible state and panel size are saved with your preferences and
  restored on the next launch.

## Editing a single cue

Click a cue in the layout. The inspector binds to it and shows the
settings pages that apply to that cue type.

* Edits **commit immediately** as you change a field — there is no
  *Apply* or *OK* button.
* Each edit is pushed onto the undo stack, so `[CTRL+Z]` reverses the
  most recent change.
* Switching the selection to another cue commits any pending edit
  before re-binding.

[screenshot: inspector bound to a single Media Cue, showing the General
page with name, fade, exclusive, etc.]

## Editing multiple cues

Select a range of cues — `[CTRL+Click]`, `[SHIFT+Click]`, or *Selection
mode* (`Layout > Selection mode`, ``[CTRL+SHIFT+E]``) — and the
inspector switches to multi-cue mode.

The inspector shows only the settings pages shared by every cue in the
selection (the greatest-common subset of settings pages across the
selected types).

### Mixed values

When a field's value differs across the selection, the inspector
decorates that field with a **mixed-value indicator**. Editing the
field clears the indicator and applies the new value to every cue in
the selection.

[screenshot: inspector in multi-cue mode showing a mixed-value
indicator on the Fade In duration field]

### Apply per group

Each settings group (the framed sections within a page — *Behaviour*,
*Fade*, *Pre/Post wait*, etc.) gains a checkbox in its title bar in
multi-cue mode.

* **Checked** — the group's values are applied to every selected cue.
* **Unchecked** — the group is left untouched. Use this when you want
  to edit only one set of properties without disturbing others that
  already differ between cues.

The default for each group is *unchecked*; check the groups you want
to apply.

[screenshot: inspector in multi-cue mode with the Fade group checkbox
ticked and the Behaviour group checkbox unticked]

## Inspector pages

Which pages appear depends on the selected cue type. Common pages:

| Page         | Purpose                                                         |
|--------------|-----------------------------------------------------------------|
| **General**  | Identity (name, description), appearance, default actions, fades, exclusive mode |
| **Pre/Post wait** | Delays before/after the cue, *Next action* setting         |
| **Media**    | *(Media cues)* Pipeline, source URI, trim, dB-meter, ReplayGain |
| **Cue-specific** | Pages contributed by particular cue types (e.g. Stop Settings, Resume Settings, Collection items) |

For the catalogue of properties on each page see
[Cues](cues/index.md).

## External changes

Edits made outside the inspector — undo / redo, presets being applied,
network-control changes — are reflected in the inspector live without
a refresh. Any pending edit you have in flight is committed first so
external state never silently overwrites work in progress.

## Keyboard

| Shortcut         | Action                                                  |
|------------------|---------------------------------------------------------|
| ``[F4]``         | Toggle the inspector                                    |
| ``[CTRL+SHIFT+E]`` | Toggle Selection mode (for multi-cue editing)         |
| ``[CTRL+Z]``     | Undo the most recent inspector edit                     |
| ``[CTRL+Y]``     | Redo                                                    |
| ``[CTRL+A]``     | Select all cues (then edit them in the inspector)       |
