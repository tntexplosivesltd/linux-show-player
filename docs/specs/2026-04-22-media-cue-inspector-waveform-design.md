# Media Cue Inspector — Waveform with Trim Markers

## Context

The Media Cue inspector page (`lisp/ui/settings/cue_pages/media_cue.py`)
currently shows three numeric fields: `Start time`, `Stop time`, and `Loop`.
Setting the in/out trim on a media file means reading timestamps off the
running-cue playback panel's waveform (or computing them in your head)
and typing them into HH:mm:ss.zzz spinboxes. Stop Time's `0:00:00` default
is opaque: a sentinel value meaning "play to end", enforced by the
`0 < stop_time < duration` guard at `gst_media.py:182`.

LiSP already has a full waveform stack used in the running-cue panel:

- `lisp/backend/waveform.py` — abstract `Waveform` with `peak_samples`,
  `rms_samples`, `duration`, `ready` and `failed` signals.
- `lisp/plugins/gst_backend/gst_waveform.py` — GStreamer implementation
  (`uridecodebin → audioconvert → appsink`) that transparently handles
  both audio files and video containers (pulls the audio stream off a
  video), emits `failed` when no audio is available. Caches results to
  disk.
- `lisp/ui/widgets/waveform.py` — `WaveformWidget` (paints peak/RMS) and
  `WaveformSlider` (adds click-seek + hover timestamp).

This spec adds a **draggable-marker waveform** to the Media Cue inspector
tab, composing the existing stack. Start and stop timestamps become
visible, grabbable surfaces; the numeric fields remain for precision.
The `stop_time == 0` sentinel gets mapped to `duration` on display so
the Stop Time field is never misleading.

## Design Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Marker interaction | Draggable (not read-only) | Read-only waveforms are decorative; the point of visible markers is placing cut points against peaks without timestamp math. |
| Stop-time sentinel handling | Pre-fill with `duration` on load; save verbatim | Honest UI — the field shows a meaningful time. Old sessions silently upgrade on first save. Backend treats `stop_time >= duration` the same as `== 0` (both fall through the `0 < stop_time < duration` guard → natural end), so behaviour is preserved. **No round-trip translation on save** — mixing data integrity with UI display is fragile. |
| Media-type scope | Audio and video | `GstWaveform`'s pipeline handles both via `uridecodebin`. Images fall back — see next row. |
| Image-cue behaviour | `startEdit`, `stopEdit` **disabled**; waveform replaced with "N/A" placeholder | `image_input.py:42-49` documents that `start_time` has no effect on images and `imagefreeze` ignores GStreamer seek-stop positions, so `stop_time` is also no-op today. The fields are pure noise; disable them. Loop field stays enabled (existing behaviour). |
| Panel layout | Two-column: narrow left (fields), wide right (waveform) | Matches QLab's layout. The waveform becomes the primary surface with numeric precision beside it. |
| Zoom and horizontal scroll | **Deferred** | V1 is fit-to-window only. On a typical resized dialog the waveform spans 400–600px, giving ~5–7× more pixel precision than the running-cue slider. Zoom + auto-scroll-during-drag is a sizable follow-up; shipping without it validates the core idea first. |
| Marker visual | Full-height vertical lines, draggable from anywhere; subtle fill between | Full-height hit target is forgiving. Shaded region between markers makes "kept range" legible at a glance. |
| Crossover handling | Clamp — start can't exceed `stop - 1ms`; stop can't go below `start + 1ms` | Simplest invariant. 1ms matches the `zzz`-precision of the existing `QTimeEdit` fields. Enforced in setters, applied to both drag and numeric input. |
| Multi-select behaviour | Hide waveform, show "Select a single cue" placeholder | Waveforms don't compose across cues. Showing cue A's peaks while dragging to set cue B's times would be a UX lie. Numeric fields continue to work via existing checkable-group multi-edit. |
| Waveform height | `setMinimumHeight(120)`, expanding | Floor is ~2–3× taller than the running-cue slider (meaningfully more peak detail). Expanding means bigger dialogs get bigger waveforms. |
| Keyboard navigation | Tab-focusable markers; `Left`/`Right` = ±100ms; `Shift+Left`/`Right` = ±1000ms | Minimal accessibility parity with the numeric fields. Can be deferred if scope pressure appears. |
| Component structure | New subclass `TrimmableWaveformWidget(WaveformWidget)`; fallback `TrimmableTimelineWidget` for no-audio | Subclassing preserves paint z-order (markers overlay peaks in one pass). Existing `WaveformSlider` and running-cue panel untouched. |
| Test strategy | Unit (widget, `_FakeWaveform` double) + integration (settings page, stubbed media) | Mirrors `tests/ui/test_cue_general_pages.py` pattern. Avoids real GStreamer in tests. Pixel-paint assertions excluded as too fragile. |

## Architecture

### Component split

```
lisp/ui/widgets/waveform.py
  ├─ WaveformWidget          (existing — unchanged)
  ├─ WaveformSlider          (existing — unchanged; running-cue panel)
  ├─ TrimmableWaveformWidget (NEW — subclass with markers, drag, clamp)
  └─ TrimmableTimelineWidget (NEW — no-peak fallback for images/failed)

lisp/ui/settings/cue_pages/media_cue.py
  └─ MediaCueSettings        (RESTRUCTURED — two-column grid)
```

The inspector page composes either a `TrimmableWaveformWidget` (audio/
video cues, once the pipeline ships peak data) or a `TrimmableTimeline
Widget` (image cues, silent video, decode failure) into the right column.
Left column keeps `startEdit`, `stopEdit`, `loopSpin` with
checkable-group multi-edit semantics.

### Layout

```
┌──────────────────┬───────────────────────────────────────────────┐
│ [Start HH:mm:ss] │ ╱╲ ╱╲╱╲ ╱╲_╱╲ ╱╲╱╲ ╱╲ ╱╲╱╲╱╲╱╲╱╲ ╲          │
│                  │ │                      │                      │
│ [Stop  HH:mm:ss] │ (region between is shaded)                    │
│                  │                                               │
│ [Loop      ∓  ]  │                                               │
│                  │                                               │
│ (stretch)        │                                               │
└──────────────────┴───────────────────────────────────────────────┘
```

Grid column stretches: left = 1, right = 3 (the waveform absorbs
horizontal space). Right column spans rows 0–2 so the waveform grows
vertically as the dialog is resized.

### `TrimmableWaveformWidget` API

```python
class TrimmableWaveformWidget(WaveformWidget):
    # Emitted continuously during drag — for UI sync only, not commits.
    startTimeChanged = pyqtSignal(int)   # ms
    stopTimeChanged  = pyqtSignal(int)   # ms
    # Emitted once on mouse-release — drives inspector commit.
    trimReleased     = pyqtSignal()

    def setStartTime(self, ms: int, silent: bool = False) -> None:
        """Clamp to [0, stop_ms - 1]. Emits startTimeChanged unless silent."""
    def setStopTime(self, ms: int, silent: bool = False) -> None:
        """Clamp to [start_ms + 1, duration]. Emits stopTimeChanged unless silent."""
    def startTime(self) -> int: ...
    def stopTime(self)  -> int: ...
```

Internal state: `_start_ms`, `_stop_ms`, `_active_marker` (start / stop /
None). Mouse handlers dispatch by x-proximity; `paintEvent` calls
`super().paintEvent()` first, then overlays shaded fill, full-height
lines, and (if a marker is focused) the focus ring.

### State machine

```
            ┌─────────────────┐
            │  MULTI-SELECT   │
            │  (>1 cue)       │
            └─────────────────┘
                    │ single cue
                    ▼
            ┌─────────────────┐
            │  IMAGE CUE      │    fields disabled +
            │                 │    "N/A" caption
            └─────────────────┘
                    │ (audio/video cue)
                    ▼
            ┌─────────────────┐
            │     LOADING     │    "Loading waveform…" label
            │                 │    numeric fields editable;
            │                 │    markers activate on ready
            └─────────────────┘
                 │       │
      ready ─────┘       └────── failed
                │                │
                ▼                ▼
          ┌──────────┐     ┌──────────────┐
          │  READY   │     │ NO-WAVEFORM  │
          │  peaks   │     │ flat timeline│
          └──────────┘     └──────────────┘
```

Transitions driven by `Waveform.ready` / `Waveform.failed` for the
audio/video path, and by `isinstance` check against `ImageInput` in
`cue.media.elements` for the image path. Multi-select detection: the
inspector's existing multi-cue plumbing — when `loadSettings` is fed
more than one cue's settings, the page switches to the placeholder.

### Data flow

**Load (cue → UI):**
```
cue.media.start_time ──┬──> startEdit.setTime()
                       └──> trimmer.setStartTime(silent=True)
cue.media.stop_time  ──> display_stop_time(stored, duration):
                             if stored == 0 and duration > 0: return duration
                             else: return stored
                         ──┬──> stopEdit.setTime()
                           └──> trimmer.setStopTime(silent=True)
```

**Live sync during edits:**
```
startEdit.timeChanged    → _on_start_edit_changed → trimmer.setStartTime(ms, silent=True)
trimmer.startTimeChanged → _on_start_marker       → startEdit.setTime(ms)  [blockSignals]
                                                    stopEdit.setMinimumTime(start + 1ms)
stopEdit.timeChanged     → _on_stop_edit_changed  → trimmer.setStopTime(ms, silent=True)
trimmer.stopTimeChanged  → _on_stop_marker        → stopEdit.setTime(ms)   [blockSignals]
                                                    startEdit.setMaximumTime(stop - 1ms)
```

Re-entry guarded by `silent=True` flag on the trimmer side and
`blockSignals()` on the `QTimeEdit` side.

**Commit (UI → cue):**
```
trimmer.trimReleased     → self.commit_requested.emit()
MediaCueSettings.getSettings() → {"media": {"start_time": …, "stop_time": …}}
```

The existing inspector commit engine already listens on `commit_requested`
(see `lisp/ui/inspector/commit.py:220`), so we wire the trimmer's
mouse-release signal through the page's existing signal and no commit-
engine changes are needed.

### Widget lifecycle

- **Construction** is lazy, inside `loadSettings()`: once per page instance,
  on the first single-cue load. `cue.media` → `get_backend().media_waveform(media)`
  → `TrimmableWaveformWidget(waveform, parent=right_column)`.
- **Disposal**: when `loadSettings()` is called with a different cue (user
  navigates the inspector cue list), the old trimmer is `deleteLater()`-d
  and a new one constructed. `Waveform.clear()` stops any in-flight
  GStreamer pipeline.
- **Caching**: `gst_waveform.py:_to_cache()` already writes peak/RMS to
  disk; second-time-open on the same file is near-instant.

## Testing

### New test files

- `tests/ui/widgets/test_trimmable_waveform.py` — unit tests for the widget,
  using a `_FakeWaveform` double.
- `tests/ui/test_media_cue_settings.py` — integration tests for the page.

### Fake Waveform double

```python
class _FakeWaveform(Waveform):
    def __init__(self, duration=10_000):
        super().__init__(...)
        self._duration = duration
        self._ready = False
    def load_waveform(self): pass
    def mark_ready(self):   self._ready = True;  self.ready.emit()
    def mark_failed(self):                          self.failed.emit()
```

### Unit test cases (`TrimmableWaveformWidget`)

- Initial state after `ready`: `start_time == 0`, `stop_time == duration`.
- `setStartTime` clamps to `[0, stop - 1ms]`.
- `setStopTime` clamps to `[start + 1ms, duration]`.
- Drag crosses over → clamps at the other marker's boundary.
- `silent=True` suppresses `startTimeChanged` / `stopTimeChanged`.
- Mouse press dispatches by x-proximity (left → start, right → stop).
- `trimReleased` emits exactly once per mouse cycle; not during move.
- `failed` transitions to flat-timeline paint (peak/RMS absent).
- Edge case: `start == stop + 1` — paint doesn't invert the region fill.

### Integration test cases (`MediaCueSettings`)

- `loadSettings({"media": {"stop_time": 0, "duration": 180_000}})`
  → `stopEdit` shows `0:03:00.000`.
- `loadSettings({"media": {"stop_time": 60_000, "duration": 180_000}})`
  → `stopEdit` shows `0:01:00.000`.
- `getSettings()` after user edit returns the typed value **verbatim** —
  no sentinel round-trip.
- Typing into `startEdit` moves the trimmer's start marker (signal bridge).
- Dragging the trimmer's start marker updates `startEdit.time()` (reverse).
- `stopEdit.minimumTime()` tracks `startEdit.time() + 1ms` after any change.
- Image cue: `cue.media.elements` contains `ImageInput` →
  `startEdit.isEnabled() == False`, `stopEdit.isEnabled() == False`,
  "N/A" caption visible.
- Multi-select: waveform hidden, placeholder shown; single-select
  restores waveform.

### Out of test scope (v1)

- Real-file GStreamer decode (covered implicitly by the running-cue panel
  in production).
- Pixel-exact paint output (Qt paint testing is too fragile).
- Performance / load timing for very long files.

## Scope boundary

### In this change

- Two-column restructure of `MediaCueSettings`.
- `TrimmableWaveformWidget` and `TrimmableTimelineWidget` in
  `lisp/ui/widgets/waveform.py`.
- Stop-time sentinel mapping (`0` → `duration` on display).
- Image-cue detection and field-disable with caption.
- Multi-select placeholder.
- Minimal keyboard navigation on markers.
- Unit + integration tests for the new widgets and page.

### Explicitly deferred

- Zoom and horizontal scroll. Clean follow-up: wrap widget in
  `QScrollArea`, add zoom controls, handle auto-scroll-during-drag.
- Scrub-audition preview (click waveform to hear position).
- Redesign of `ImageInput.duration` UI (lives in its own settings
  surface; this change only disables the unused trim fields).
- Any change to Loop-field behaviour for images.
- E2E test fixture checking-in a real audio file for load-path coverage.

### Out of scope entirely

- Session file format changes. All new behaviour composes existing
  `start_time` / `stop_time` properties.
- Cue / MediaCue / GstMedia model changes.
- Running-cue panel changes — keeps using `WaveformSlider`.
- Backend abstract class changes — existing `ready` / `failed` signals
  are sufficient.

## File impact summary

**Modify (2):**
- `lisp/ui/widgets/waveform.py` — ~+180 lines (two new classes).
- `lisp/ui/settings/cue_pages/media_cue.py` — restructured; ~+100 lines net.

**Create (2):**
- `tests/ui/widgets/test_trimmable_waveform.py` — ~+250 lines, 12–15 tests.
- `tests/ui/test_media_cue_settings.py` — ~+200 lines, 10–12 tests.

**Unchanged:**
- `lisp/backend/waveform.py`.
- `lisp/plugins/gst_backend/gst_waveform.py`.
- `lisp/plugins/gst_backend/gst_media.py`.
- `lisp/cues/media_cue.py`, `lisp/cues/cue.py`.
- Session file format.
- Running-cue panel (`lisp/plugins/list_layout/playing_widgets.py`).
- Test harness plugin.
