# Cart Layout

```{image} _static/cart_layout_main_view.png
:alt: Linux Show Player - Cart Layout
:align: center
```

<br>
The Cart Layout organize all the cues in grid-like pages, cues are shown as
buttons, if the cue provides a duration, the current cue time is shown at the bottom.

## How to use

### Adding Pages

To add a new page you can use `Layout > Add page`, or `Layout > Add pages`,
to add multiple pages at once.

Pages will also be added automatically when needed.

### Removing Pages

To remove a page, select the page to be removed, then use `Layout > Remove current page`,
a confirmation dialog will be shown.

```{warning}
All cues in the page will be deleted.
```

### Moving between pages

Pages can be switched using the tab bar on top of the layout or directional keys.

### Renaming pages

It's possible to rename pages via `Double click` on the tab name.

### Cues Execution

A cue can be start/stopped by clicking on it.

Via `Right-Click` on the cue is also possible play, stop, or pause the cues explicitly.

### Cues Editing

Cue properties are edited in the [inspector](editing_cues.md), the
panel docked below the layout. `SHIFT+Right-Click` a cell to select
the cue and bring its settings up in the inspector; toggle the panel
with `View > Show Inspector` or ``[F4]``.

Cues can be selected/deselected for multi-cue editing with `Right-Click > Select` or `CTRL+Left-Click`.

Cues with their *Enabled* checkbox unticked render their cell dimmed.
Disabled cues are skipped by GO, *next-action* chains, and group
playback. See [Enabled](cues/index.md#enabled) for the full behaviour.

### Move and Copy Cues

Cues can be copied or moved (into free spaces) inside a page or between different pages:

* **Move:** cues can be moved with `SHIFT+Drag&Drop`
* **Copy:** cues can be copied with `CTRL+Drag&Drop`

to move/copy between pages, while dragging the cue, over the destination page.

## Options

In the application settings (`File > Preferences`) various options are provided:

### Default behaviours

This can be changed per-show via the `Layout` menu.

* **Countdown mode:** when enabled the current cue time is displayed as a countdown
* **Show seek-bars:** when enabled a slider able to change the current playing position
  of media cues (for media cues)
* **Show dB-meters:** when enabled, a dB level indicator is shown (for supported cues)
* **Show accurate time:** when enabled the cue time is displayed including tens of seconds
* **Show volume:** when enabled a volume slider is shown (for supported cues)

### Grid size

Define the number of rows & columns per page (reload the session to apply).

```{warning}
When the grid size is changed, cues will be visually shifted to keep their
logical positioning.
```

```{image} _static/cart_layout_settings.png
:alt: Linux Show Player - Cart Layout settings
:align: center
```

## Limitations

Given its non-sequential nature, Cart Layout does not support cues "next-action".
