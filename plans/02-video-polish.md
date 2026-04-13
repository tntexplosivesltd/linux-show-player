# Video Polish & Remaining PR #333 TODO Items

## Context

PR #333's TODO list included 8 items. The main video plan (`02-video-support.md`) addresses 3 fully (external monitor, video sink selection, opacity fading) and 1 partially (windowed playback exists but no audition concept). This follow-up covers the remaining 4 items plus the partial one. All build on Phase 1-3 infrastructure without architectural changes.

**Depends on**: Phases 1-3 of `02-video-support.md` being complete.

---

## Item 1: Hide Mouse Cursor During Playback

**Effort**: Trivial — single-method addition to `VideoOutputWindow`.

**File**: `lisp/plugins/gst_backend/gst_video_window.py`

In the `VideoOutputWindow` created by Phase 3 Step 3.1:
- Call `self.setCursor(QCursor(Qt.BlankCursor))` when entering fullscreen or starting playback
- Restore with `self.setCursor(QCursor(Qt.ArrowCursor))` when exiting fullscreen or showing controls
- The codebase already uses `QCursor` in `gst_backend.py` for wait cursors, so the import pattern is established

No settings page needed — cursor should always be hidden during fullscreen projection.

---

## Item 2: Video Parameters (Brightness, Contrast, Saturation, Hue)

**Effort**: Moderate — new element + settings page, following the exact `VideoAlpha` pattern.

### Step 2.1: Create VideoBalance element

**New file**: `lisp/plugins/gst_backend/elements/video_balance.py`

- `MediaType = MediaType.Video`, `ElementType = ElementType.Plugin`
- Wraps GStreamer's `videobalance` element
- Properties via `GstProperty` (same pattern as `Volume` in `elements/volume.py`):
  - `brightness` (float, range -1.0 to 1.0, default 0.0)
  - `contrast` (float, range 0.0 to 2.0, default 1.0)
  - `saturation` (float, range 0.0 to 2.0, default 1.0)
  - `hue` (float, range -1.0 to 1.0, default 0.0)
- Participates in video chain via `post_link()` — same wiring mechanism as `VideoAlpha`
- Placed before `VideoAlpha` in the video pipeline so alpha fading applies on top of color adjustments

### Step 2.2: VideoBalance settings page

**New file**: `lisp/plugins/gst_backend/settings/video_balance.py`

- Extends `SettingsPage` with `ELEMENT = VideoBalance`
- Four `QDoubleSpinBox` controls (or sliders) for each property
- Reset button to restore defaults
- Follow the `settings/volume.py` pattern: `loadSettings()` / `getSettings()`

### Step 2.3: Update default config

**File**: `lisp/plugins/gst_backend/default.json`

Add `VideoBalance` to the `video_pipeline` before `VideoSink`:
```json
"video_pipeline": ["Volume", "DbMeter", "VideoBalance", "VideoSink"]
```

### Tests

- Unit: `VideoBalance` properties have correct defaults and ranges
- Unit: element contains a `videobalance` GStreamer element
- Unit: settings page round-trips all four values through `loadSettings()`/`getSettings()`

---

## Item 3: Image Transform (Keystone Correction)

**Effort**: High — requires perspective transform element with a usable UI for adjusting corners.

### Step 3.1: Evaluate GStreamer transform options

Two approaches to investigate before implementation:

1. **`perspectiveTransform`** (gst-plugins-bad) — applies a 3x3 homography matrix. Lightweight but requires computing the matrix from four corner points.
2. **OpenGL shader via `glshaderbin`** — more flexible but introduces GL dependency and may not work on all systems.

Recommend approach 1 (`perspectiveTransform`) if available in the target GStreamer version (1.16+). Fall back to `videobox` + `perspective` if not.

### Step 3.2: Create KeystoneTransform element

**New file**: `lisp/plugins/gst_backend/elements/keystone.py`

- `MediaType = MediaType.Video`, `ElementType = ElementType.Plugin`
- Properties: four corner offset pairs (top-left, top-right, bottom-left, bottom-right), each an (x, y) float pair representing displacement from the default rectangle corners
- Computes the 3x3 perspective matrix from the four corners
- Participates in video chain via `post_link()`

### Step 3.3: Keystone settings page

**New file**: `lisp/plugins/gst_backend/settings/keystone.py`

- Visual corner-drag widget showing a preview rectangle with draggable corners
- Numeric spinboxes for precise adjustment
- Reset to flat rectangle

### Tests

- Unit: default corner offsets produce identity transform (no distortion)
- Unit: moving one corner produces a valid non-identity matrix
- Manual: project onto angled surface, adjust corners until rectangular

**Note**: This is the most complex item. It may warrant its own plan if the GStreamer element landscape proves tricky. Listing it here for completeness but it could reasonably be deferred further.

---

## Item 4: Video Audition Window

**Effort**: Moderate — extends `VideoOutputWindow` with a secondary windowed mode.

### Step 4.1: Add audition mode to VideoOutputWindow

**File**: `lisp/plugins/gst_backend/gst_video_window.py`

The Phase 3 `VideoOutputWindow` is a fullscreen projection window on an external display. Audition mode adds a smaller, resizable window on the operator's display for previewing video without projecting.

- Add `set_mode(mode)` method: `PROJECTION` (existing fullscreen behavior) or `AUDITION` (windowed, resizable, with title bar, on primary display)
- In audition mode: restore window frame hints, set a reasonable default size (640x360), show on primary `QScreen`
- Toggle via a toolbar button or keyboard shortcut in the main window

### Step 4.2: Add audition toggle to UI

**File**: `lisp/plugins/gst_backend/gst_backend.py`

- Add a menu item or toolbar action: "Video Audition" (toggle)
- When enabled, video output renders in the audition window instead of (or alongside) the projection window
- Could also be a right-click action on individual video cues: "Preview in audition window"

### Tests

- Unit: `set_mode(AUDITION)` removes frameless hint, restores title bar
- Unit: `set_mode(PROJECTION)` restores frameless fullscreen behavior
- Manual: toggle audition during playback, verify video appears in small window

---

## Item 5: Video Thumbnails

**Effort**: Moderate — thumbnail extraction + layout widget changes.

### Step 5.1: Add thumbnail extraction utility

**File**: `lisp/plugins/gst_backend/gst_utils.py`

`GstPbutils.Discoverer` is already used here for `gst_uri_metadata()`. Add:

```python
def gst_uri_thumbnail(uri: SessionURI, width=64, height=48) -> Optional[QPixmap]:
```

- Use `Discoverer.discover_uri()` to get `DiscovererInfo`
- Check for `GST_TAG_IMAGE` or `GST_TAG_PREVIEW_IMAGE` in tags
- If no embedded thumbnail, run a short pipeline: `uridecodebin ! videoconvert ! videoscale ! video/x-raw,width=W,height=H ! pngenc ! appsink` with `num-buffers=1` to grab the first frame
- Cache thumbnails by URI + mtime to avoid re-extraction (simple dict cache, cleared on session change)

### Step 5.2: Add thumbnail column to list layout

**File**: `lisp/plugins/list_layout/list_widgets.py`

New widget class following the `CueStatusIcons` pattern:
- Custom `QWidget` with `paintEvent()` that draws a `QPixmap` thumbnail
- Fixed column width (~64px)
- Lazy-loads thumbnail on first paint or when cue URI changes
- Shows a placeholder icon for non-media cues (action cues, groups)

**File**: `lisp/plugins/list_layout/list_view.py`

Add the thumbnail widget to the `COLUMNS` list:
```python
ListColumn("", ThumbnailWidget, QHeaderView.Fixed, width=64)
```

### Step 5.3: Add thumbnail to cart layout

**File**: `lisp/plugins/cart_layout/cue_widget.py`

- Add a small `QLabel` to the `CueWidget` layout showing the thumbnail as a background or icon
- Scale to fit the widget's width

### Step 5.4: Make thumbnails optional

**File**: `lisp/plugins/list_layout/default.json` (or equivalent config)

Add a `show_thumbnails` boolean setting (default `true` for video-capable setups). Users on audio-only workflows shouldn't pay the extraction cost.

### Tests

- Unit: `gst_uri_thumbnail()` returns a `QPixmap` for a video file
- Unit: `gst_uri_thumbnail()` returns `None` for an audio-only file
- Unit: thumbnail cache returns same pixmap on second call without re-extraction
- Unit: `ThumbnailWidget` renders placeholder when no thumbnail available

---

## File Summary

### New Files
| File | Purpose |
|---|---|
| `lisp/plugins/gst_backend/elements/video_balance.py` | Brightness/contrast/saturation/hue adjustment |
| `lisp/plugins/gst_backend/elements/keystone.py` | Perspective correction for projection |
| `lisp/plugins/gst_backend/settings/video_balance.py` | VideoBalance settings page |
| `lisp/plugins/gst_backend/settings/keystone.py` | Keystone corner adjustment UI |

### Modified Files
| File | Change |
|---|---|
| `lisp/plugins/gst_backend/gst_video_window.py` | Cursor hiding, audition mode |
| `lisp/plugins/gst_backend/gst_backend.py` | Audition toggle UI |
| `lisp/plugins/gst_backend/gst_utils.py` | Thumbnail extraction function |
| `lisp/plugins/gst_backend/default.json` | Add VideoBalance to video_pipeline |
| `lisp/plugins/list_layout/list_widgets.py` | Thumbnail widget |
| `lisp/plugins/list_layout/list_view.py` | Thumbnail column |
| `lisp/plugins/cart_layout/cue_widget.py` | Thumbnail display |

---

## Suggested Priority Order

1. **Hide mouse cursor** — trivial, immediate UX win
2. **Video parameters** — follows established element pattern, common user need
3. **Video thumbnails** — significant UX improvement for video workflows
4. **Video audition window** — useful for operators, moderate effort
5. **Keystone correction** — high effort, niche use case, consider deferring
