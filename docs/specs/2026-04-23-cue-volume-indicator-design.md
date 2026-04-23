# Cue Volume Indicator on the Playback Panel

## Overview

Add a small read-only dB readout to each running `MediaCue` in the
list layout's playback panel, so operators can see a cue's current
live volume — particularly useful during Fade and Volume-Control cues
where the value changes over time.

The indicator reflects the cue's **current fader position** (post-
interpolation `Volume.live_volume`), not the audio signal level. A
separate dB-meter feature already covers signal level; this fills the
gap for "what gain is this cue currently at?".

## Decisions

- **Read-only**. No interactivity — the operator adjusts volume via
  the inspector or Volume-Control cues. A draggable live fader is
  explicitly out of scope; the mutation path has interaction-conflict
  concerns with running fades that a pure indicator avoids.
- **MediaCue only**. Non-audio cues have no `Volume` element, so the
  label only exists on `RunningMediaCueWidget`, not the base
  `RunningCueWidget`.
- **Opt-in via layout menu**. Default off. Visibility toggles through
  a new `Show volume indicators` menu action mirroring the existing
  `Show dB-meters` pattern. Persisted under `show.volumeIndicator`.
- **Numeric dB label only**. Format `{db:+.1f} dB` (e.g. `+0.0 dB`,
  `-12.3 dB`). No bar, no fader handle — keeps the footprint
  minimal.
- **Silence sentinel**: at or below `MIN_VOLUME_DB` (-144), display
  `-∞ dB`. Threshold uses the library's existing silence constant so
  legitimate fades to values like `-60 dB` still read literally.
- **Placement**: stacked **above** the time display in cell `(1, 1)`
  of the running-widget grid. The time display has ample vertical
  headroom; the cue name's row stays at full width (unchanged).
- **Data source**: piggy-back on `CueTime.notify` (30 Hz `Clock_33`).
  No new timers, no new signals. Label auto-freezes on pause/stop
  because `CueTime` stops ticking in those states.
- **Mute state is not reflected** (out of scope). A muted cue at
  `-12 dB` still reads `-12.0 dB`, matching the inspector.

## Architecture

Changes are localised to the list layout plugin and use pull-model
data flow. GStreamer's `GstController` interpolates the volume in the
pipeline without emitting Qt signals, so the indicator polls
`Volume.live_volume` on each `CueTime.notify` tick.

```
cue.cue_time.notify (Clock_33, 30 Hz, running-only)
        │
        └─► _update_volume_label(time_ms)         # ignores time arg
                │
                ├─ element = cue.media.element("Volume")
                ├─ if element is None: hide label; return
                ├─ db = linear_to_db(element.live_volume)
                ├─ text = "-∞ dB" if db <= MIN_VOLUME_DB
                │          else f"{db:+.1f} dB"
                └─ volumeIndicator.setText(text)
```

The `(1, 1)` grid cell is split vertically with a `QVBoxLayout`
holding `[volumeIndicator, timeDisplay]`. The outer grid's row
stretches (`row0=1, row1=3`) and column stretches (`col0=7, col1=5`)
remain unchanged, so the widget's overall height and the name's
horizontal span are unaffected.

```
┌────────────────────────────────────────────────────────────┐
│ nameLabel (row 0, colspan=2, full width — unchanged)       │
├───────────────────────────┬────────────────────────────────┤
│                           │                      -12.3 dB  │  ← new
│ controlButtons            ├────────────────────────────────┤
│                           │   timeDisplay (LCD, existing)  │
└───────────────────────────┴────────────────────────────────┘
```

## Components

### `VolumeIndicatorLabel(QLabel)` — new class

Location: `lisp/plugins/list_layout/playing_widgets.py`, alongside
`_ColorStripe`.

- Monospace, right-aligned single-line label.
- `SizePolicy(Preferred, Fixed)`. Width follows content; height fixed
  to one line so the time display keeps the majority of cell `(1, 1)`.
- Method `setVolumeDb(db: float)` — applies the `-∞` threshold and
  updates `setText` with the `{:+.1f} dB` format.
- Starts hidden (`setVisible(False)`).

### `RunningMediaCueWidget` — modified

File: `lisp/plugins/list_layout/playing_widgets.py`.

- Replace `self.gridLayout.addWidget(self.timeDisplay, 1, 1)` with a
  composite `QWidget` carrying a `QVBoxLayout` of
  `[volumeIndicator, timeDisplay]`, added to cell `(1, 1)`.
  VBox `setContentsMargins(0, 0, 0, 0)`, tight spacing.
- Connect `self.cue_time.notify` to `_update_volume_label`,
  `Connection.QtQueued`.
- New method `_update_volume_label(time_ms)` implementing the flow
  above.
- New method `set_volume_indicator_visible(visible: bool)` that
  toggles `self.volumeIndicator.setVisible` and calls
  `_update_volume_label(0)` once on show so a freshly-revealed label
  paints its current value instead of flashing blank.
- In `__init__`, after constructing the label, call
  `_update_volume_label(0)` once so the initial state is correct even
  if the cue is not yet playing (label renders the cue's configured
  static volume).

### `ListLayout` — modified

File: `lisp/plugins/list_layout/layout.py`.

- Add `self.show_volume_indicator_action` to `layout_menu`, next to
  `show_dbmeter_action` (around line 109). Checkable, connected to
  `_set_volume_indicator_visible`.
- `retranslateUi`: `translate("ListLayout", "Show volume indicators")`.
- `_set_volume_indicator_visible(self, visible)` — mirrors
  `_set_dbmeters_visible`. Sets checkbox, forwards to
  `self._view.runView.volume_indicator_visible = visible`, persists.
- Property `volume_indicator_visible` reads the action's checked
  state.

### `RunningListWidget` (playback panel) — modified

File: `lisp/plugins/list_layout/playing_view.py`.

- New property `volume_indicator_visible`. Setter iterates the
  currently-shown running widgets and calls
  `set_volume_indicator_visible(visible)` on each instance of
  `RunningMediaCueWidget`. Non-media running widgets are skipped.
- On widget instantiation for a newly-started cue, apply the current
  `volume_indicator_visible` state so the new widget respects the
  global toggle.

### Settings page — modified

File: `lisp/plugins/list_layout/settings.py`.

- New `QCheckBox self.showVolumeIndicators` in
  `defaultBehaviorsGroup`, ordered next to `self.showDbMeters`.
- `retranslateUi`: `translate("ListLayout", "Show volume indicators")`.
- `loadSettings` / `getSettings` read/write
  `settings["show"]["volumeIndicator"]`.

### Default config — modified

File: `lisp/plugins/list_layout/default.json`.

- Add `"volumeIndicator": false` to the `"show"` object.

## Data Flow

One-way pull:

1. `CueTime` fires `notify` at 30 Hz while the cue is in a running
   (non-paused) state.
2. `_update_volume_label` looks up the cue's `Volume` element fresh
   on every tick (no cached reference, avoiding staleness after media
   reloads).
3. `live_volume` is read via the `GstLiveProperty` descriptor — a
   direct `element.get_property("volume")` call, so the value reflects
   whatever the `GstController` interpolation source has currently
   applied.
4. The linear value is converted to dB via `linear_to_db`, passed
   through the silence-sentinel check, formatted, and pushed to the
   label.

No new signals are declared. The existing `cue.changed("volume")`
signal fires only on explicit configured-volume changes, not on
live interpolation, so it is not a substitute for polling.

## Error Handling

- **Volume element missing**: `cue.media.element("Volume")` returns
  `None`. Hide the label for that cue. Next tick re-checks; if the
  element comes back (settings change), the label shows again.
- **Indefinite-duration cues** (`cue.duration == 0`): `CueTime` never
  activates, so `notify` never fires. The label still renders the
  initial value via the `_update_volume_label(0)` call in `__init__`
  and on toggle-visible, which reads the configured static volume.
  Live fades are atypical on indefinite cues; acceptable degradation.
- **Widget destruction**: `Connection.QtQueued` plus Qt
  parent/child ownership handle disconnection automatically; no
  explicit teardown.

## Testing

### Unit tests

New file: `tests/plugins/list_layout/test_volume_indicator.py`.

Table-driven test of the dB-formatting logic (pure function, no Qt):

| linear input | expected text |
| ------------ | ------------- |
| `1.0`        | `"+0.0 dB"`   |
| `0.5`        | `"-6.0 dB"`   |
| `2.0`        | `"+6.0 dB"`   |
| `10.0`       | `"+20.0 dB"`  |
| `0.0`        | `"-∞ dB"`     |
| `1e-09`      | `"-∞ dB"`     |

### E2E tests

New files under `tests/e2e/`:

- `test_volume_indicator_toggle.py` — start LiSP, add a media cue,
  flip `show.volumeIndicator`, verify the running widget exposes the
  indicator's visibility via a new `layout.running_widget_info`
  harness method (a small additive extension to the existing
  `test_harness` plugin).
- `test_volume_indicator_updates_during_fade.py` — add a media cue,
  add a Volume-Control cue that fades to `-12 dB` over 1 s, start
  both, poll `Volume.live_volume` at 100 ms intervals during the
  fade, assert monotonic decrease and final value ≈ `-12 dB`. This
  exercises the signal chain the label depends on without needing UI
  text readback.

### Out of scope

- Pixel-level rendering tests. Manual visual verification covers
  layout and font metrics.
- Mute-state reflection tests (deferred with the feature itself).

## Non-Goals

- Draggable live fader on the playback panel (see cart_layout's
  `volumeSlider` for a precedent; not being brought to list layout
  in this work).
- Signal-level metering (already covered by the existing
  `Show dB-meters` toggle and `QDigitalMeter`).
- Reflecting `Volume.mute` state in the label.
- Indicators on non-`MediaCue` running widgets.
