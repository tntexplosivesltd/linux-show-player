# Video, Image & Slideshow Support for Linux Show Player

## Context

The user wants to project **video, still images, and slideshows** alongside audio during live stage shows. The workflow uses existing **GroupCue** infrastructure: parallel mode for simultaneous audio+video, playlist mode for slideshows with per-image display times.

Two upstream PRs exist (unmerged): **PR #333** (basic Wayland-only video POC) and **PR #349** (extended video with Alpha fading, split A/V pipeline, FaderGroup, video effects). Our fork has diverged significantly, so we adapt their approach rather than cherry-picking.

### Key Architectural Decision: `post_link()` Hook

PR #349 restructured `GstMediaElements.append()` and `GstMedia.__init_pipeline()` to split audio/video chains, breaking the clean linear linking model. Instead, we introduce a **`post_link()`** hook:

- The existing linear chain continues to handle **audio** (UriAVInput.src() -> Volume -> DbMeter -> VideoSink.sink())
- A `post_link()` pass runs after the linear chain is assembled, allowing **VideoSink** to find the video source and wire the **video branch** separately
- Audio-only pipelines are **completely unaffected** -- `post_link()` is a no-op for existing elements

This preserves backwards compatibility while enabling split A/V pipelines.

### Upstream PR Analysis

**PR #333** (Basic Video Support by markhamilton01):
- Wayland-only video sink, basic playback works
- Review feedback (s0600204): needs non-Wayland sinks, WaylandSink should be ElementType.Plugin not Output, settings page loads config wrong

**PR #349** (Video Support including Fading by tobi08151405):
- Extends #333 with Alpha fading, AutoVideoSink, split A/V pipeline, FaderGroup, video effects (Blur, Flip, Rotate, VideoBalance)
- Review feedback (s0600204): Alpha breaks looping, no output window control, Rotate is counter-intuitive, Blur needs documentation
- Owner feedback (FrancescoCeruti): Recommended FaderGroup with ThreadPoolExecutor for simultaneous A/V fading
- Known bugs: mutable default class variable in FaderGroup, `self._volume.volume` typo in fadein, `__cleanupAV` race condition

---

## Phase 1: Core Video Playback (MVP) ✅

**Goal**: Play a video file -- audio through speakers, video in a window.
**Commit**: `9e6ab3e` — split A/V pipeline with post_link hook

### Step 1.1: Add `post_link()` and `video_src()` hooks to GstMediaElement

**File**: `lisp/plugins/gst_backend/gst_element.py`

Add two default no-op methods to `GstMediaElement`:
- `video_src(self)` -> returns `None` (overridden by A/V source elements)
- `post_link(self, all_elements)` -> no-op (overridden by VideoSink)

### Step 1.2: Add post-link pass to GstMedia.__init_pipeline()

**File**: `lisp/plugins/gst_backend/gst_media.py`

After the element creation loop (line ~258), before `set_state(READY)`:
```python
for element in self.elements:
    element.post_link(self.elements)
```

### Step 1.3: Create UriAVInput element (audio+video source)

**New file**: `lisp/plugins/gst_backend/elements/uri_av_input.py`

Based on existing `UriInput` (`lisp/plugins/gst_backend/elements/uri_input.py`):
- `MediaType = MediaType.AudioAndVideo`, `ElementType = ElementType.Input`
- Uses `uridecodebin` with `pad-added` callback that inspects caps to route audio pads to `audio_queue -> audioconvert` and video pads to `video_queue -> videoconvert -> videoscale`
- `src()` returns audioconvert (feeds the linear audio chain)
- `video_src()` returns videoscale (feeds the video branch via post_link)
- Queues on each branch are **essential** to prevent GStreamer deadlock in multi-stream pipelines
- Reuses same URI property, duration detection, mtime tracking from UriInput
- `has_audio()`/`has_video()` methods inspect decoder pads at runtime

### Step 1.4: Create VideoSink element (compound A/V output)

**New file**: `lisp/plugins/gst_backend/elements/video_sink.py`

- `MediaType = MediaType.AudioAndVideo`, `ElementType = ElementType.Output`
- Audio path: `autoaudiosink` (same as current AutoSink)
- Video path: `queue -> autovideosink`
- `sink()` returns audio sink element (compatible with upstream audio chain)
- `post_link(all_elements)` finds first element with `video_src() is not None`, links it to the video queue
- Properties: `fullscreen` (bool)
- Initial version uses `autovideosink` (opens its own window -- simplest, works on X11 and Wayland)

### Step 1.5: Add UriVideoCueFactory

**File**: `lisp/plugins/gst_backend/gst_media_cue.py`

New factory analogous to `UriAudioCueFactory`:
```python
class UriVideoCueFactory(GstCueFactory):
    input = "UriAVInput"
```

### Step 1.6: Register video cue menu entry

**File**: `lisp/plugins/gst_backend/gst_backend.py`

- Add "Video cue (from file)" under "Media cues" category (shortcut: `Ctrl+Shift+M`)
- File dialog filters to `supported_extensions()["video"]`
- Uses `UriVideoCueFactory` with video pipeline

### Step 1.7: Add video_pipeline to default config

**File**: `lisp/plugins/gst_backend/default.json`

```json
"video_pipeline": ["Volume", "DbMeter", "VideoSink"]
```

### Step 1.8: Add `MediaType.Unknown` to media_element.py

**File**: `lisp/backend/media_element.py`

Add `Unknown = 3` to the `MediaType` enum (needed by UriAVInput before pad detection runs).

### Phase 1 Tests

**Unit tests** (`tests/plugins/gst_backend/`):
- `test_gst_element.py`: Verify `post_link()` and `video_src()` exist on base class, return None/no-op
- `test_uri_av_input.py`:
  - Default properties match UriInput (uri, download, buffer_size, use_buffering)
  - `src()` returns audioconvert element
  - `video_src()` returns videoscale element
  - `has_audio()` / `has_video()` return False before playback
- `test_video_sink.py`:
  - `sink()` returns a GStreamer element (the audio sink)
  - `post_link()` with a mock element list finds video_src and wires it
  - `post_link()` with no video source is a no-op (no crash)
- `test_gst_media_pipeline.py`:
  - `__init_pipeline()` calls `post_link()` on all elements after creation
  - Audio-only pipeline (`UriInput -> AutoSink`) still works unchanged
  - Video pipeline (`UriAVInput -> Volume -> VideoSink`) creates all elements

**E2E tests** (via test_harness, require Xvfb for headless):
- `test_video_cue_lifecycle.py`:
  - Add a video cue via `cue.add_from_uri` with an MP4 file -> cue appears in model
  - Play video cue -> state transitions to Running
  - Pause video cue -> state transitions to Pause
  - Resume -> back to Running
  - Stop -> state transitions to Stop
  - Verify `cue.status` and `cue.current_time` work for video cues
- `test_audio_backward_compat.py`:
  - Load an existing audio-only session file -> all cues load correctly
  - Add audio cue, play, stop -> unchanged behavior
  - Verify audio pipeline uses AutoSink (not VideoSink)

### Phase 1 Manual Verification
- Add a video cue from file (MP4 with audio) -> both audio and video play
- Stop/pause/resume -> correct behavior
- Load an existing audio-only session -> still works unchanged

---

## Phase 2: Still Image Support ✅

**Goal**: Display still images as continuous video using GStreamer's `imagefreeze`.
**Commit**: `c07bb02` — imagefreeze pipeline with EOS timer

### Step 2.1: Create ImageInput element

**New file**: `lisp/plugins/gst_backend/elements/image_input.py`

- `MediaType = MediaType.Video`, `ElementType = ElementType.Input`
- Pipeline: `filesrc -> decodebin -> imagefreeze -> videoconvert -> videoscale`
- `imagefreeze` converts a single decoded frame into a continuous video stream
- `src()` returns `None` (no audio)
- `video_src()` returns videoscale
- Duration property: user-configurable (default 5000ms), enforced via `Media.stop_time`
- URI property for the image file path

**Why separate from UriAVInput**: Images need `imagefreeze` insertion, have no natural duration, and never have audio. A dedicated element is simpler and more reliable.

### Step 2.2: Add UriImageCueFactory

**File**: `lisp/plugins/gst_backend/gst_media_cue.py`

Sets `input = "ImageInput"` and configures `stop_time` from a duration parameter.

### Step 2.3: Register image cue menu entry

**File**: `lisp/plugins/gst_backend/gst_backend.py`

- Add "Image cue (from file)" under "Media cues"
- Filter: jpg, jpeg, png, bmp, svg, tiff, webp

### Step 2.4: Add image_pipeline to default config

**File**: `lisp/plugins/gst_backend/default.json`

```json
"image_pipeline": ["VideoSink"]
```

No audio processing elements (Volume, DbMeter) since images have no audio.

### Phase 2 Tests

**Unit tests** (`tests/plugins/gst_backend/`):
- `test_image_input.py`:
  - Default duration is 5000ms
  - `src()` returns None (no audio)
  - `video_src()` returns videoscale element
  - URI property accepts image file paths
  - Pipeline contains imagefreeze element
- `test_image_cue_factory.py`:
  - `UriImageCueFactory` creates cue with ImageInput as source
  - `stop_time` is set to the configured duration
  - URI is propagated to the ImageInput element

**E2E tests** (via test_harness):
- `test_image_cue_lifecycle.py`:
  - Add image cue from JPEG -> cue appears in model with correct type
  - Play image cue -> state transitions to Running
  - Image cue auto-stops after configured duration (verify via `signals.wait_for` on `stopped` signal)
  - Image cue with custom duration (e.g., 3000ms) stops at ~3s
- `test_slideshow_workflow.py`:
  - Create 3 image cues with durations 2s, 3s, 2s
  - Group them into a GroupCue in playlist mode
  - Play the group -> first image plays
  - Wait for `end` signal on first child -> second image starts
  - Verify total duration is ~7s
  - Verify group state transitions: Running -> Stop after all images shown
- `test_audio_with_image.py`:
  - Create audio cue + image cue
  - Group in parallel mode
  - Play group -> both start simultaneously
  - Verify audio cue is Running AND image cue is Running
  - Group ends when both have completed

### Phase 2 Manual Verification
- Add a JPEG/PNG cue -> displays in video window for configured duration
- GroupCue playlist mode with multiple image cues -> slideshow works
- GroupCue parallel mode: audio cue + image cue -> simultaneous playback

---

## Phase 3: Video Output Window & Fading

**Goal**: Dedicated projection window, video fade-to-black via alpha.

### Step 3.1: Create VideoOutputWindow ✅

**New file**: `lisp/plugins/gst_backend/gst_video_window.py`

- `QMainWindow` with `Qt.FramelessWindowHint`
- Black background `QWidget` as central widget
- `set_display(screen_index)` -> moves to specified `QScreen` via `QApplication.screens()`
- `set_fullscreen(enabled)` -> toggles fullscreen
- `window_handle()` -> returns `winId()` for GStreamer VideoOverlay
- `closeEvent()` overridden to **hide** instead of close (fixes PR #349 bug where closing window caused unhandled error)
- Singleton managed by GstBackend plugin

### Step 3.2: Upgrade VideoSink to use VideoOverlay ✅

**File**: `lisp/plugins/gst_backend/elements/video_sink.py`

Replace `autovideosink` with a specific sink (`glimagesink` preferred, `xvimagesink` fallback) that implements `GstVideo.VideoOverlay`. Call `set_window_handle()` to render into the `VideoOutputWindow`.

**File**: `lisp/plugins/gst_backend/gi_repository.py` -- add `GstVideo` import.

### Step 3.3: Create FaderGroup ✅

**New file**: `lisp/core/fader_group.py`

Based on PR #349's approach (recommended by project owner FrancescoCeruti):
- Wraps multiple `BaseFader` instances
- `fade(duration, to_values, fade_type)` runs all faders in parallel via `ThreadPoolExecutor`
- `to_values` is a list with per-fader targets (audio volume != video alpha)
- `prepare()` and `stop()` delegate to all faders
- **Fix PR #349 bug**: No mutable default class variable

### Step 3.4: Create VideoAlpha element ✅

**New file**: `lisp/plugins/gst_backend/elements/video_alpha.py`

- `MediaType = MediaType.Video`, `ElementType = ElementType.Plugin`
- Uses `compositor` with single input for alpha control (same approach as PR #349)
- Properties: `alpha` (saved), `live_alpha` (GstLiveProperty for fading)
- `get_controller("live_alpha")` returns GstPropertyController
- **Fix PR #349 looping bug**: Add `videoconvert` after compositor to re-negotiate caps
- Participates in video chain via `post_link()`: VideoSink's post_link wires video-type Plugin elements into the video branch in pipeline order

### Step 3.5: Update MediaCue to use FaderGroup ✅

**File**: `lisp/cues/media_cue.py`

- Replace single `__fader`/`__volume` with `FaderGroup` containing both audio and video faders
- `__elements_changed()` discovers both `Volume` and `VideoAlpha` elements
- Fadeout: `to_values = [0] * len(fader_group)` (all to zero)
- Fadein: `to_values = [volume.volume, alpha.alpha]` (restore to saved levels)
- `_can_fade()` returns True if ANY fader exists (audio-only, video-only, or both)

### Step 3.6: Add settings pages ✅

**New files**:
- `lisp/plugins/gst_backend/settings/video_sink.py` -- Display selection dropdown, fullscreen toggle
- `lisp/plugins/gst_backend/settings/image_input.py` -- File chooser, duration spinner

### Phase 3 Tests

**Unit tests** (`tests/core/`):
- `test_fader_group.py`:
  - Empty FaderGroup: `fade()` returns True, `stop()` is no-op
  - Single fader: behaves identically to standalone fader
  - Two faders: both reach target values after fade completes
  - Interrupted fade: `stop()` interrupts all faders, `fade()` returns False
  - Per-fader target values: audio fades to 0.8, video fades to 1.0 simultaneously
  - `prepare()` calls prepare on all faders
  - No mutable default class variable (regression test for PR #349 bug)
  - Thread safety: concurrent `fade()` and `stop()` don't deadlock

**Unit tests** (`tests/plugins/gst_backend/`):
- `test_video_alpha.py`:
  - Default alpha is 1.0
  - `get_controller("live_alpha")` returns a GstPropertyController
  - `get_fader("live_alpha")` returns a functional fader
  - Pipeline contains videoconvert after compositor (looping fix)
- `test_video_output_window.py`:
  - Window creates with frameless hint
  - `window_handle()` returns non-zero int
  - `closeEvent()` hides instead of closing
  - `set_fullscreen(True/False)` toggles state

**Unit tests** (`tests/cues/`):
- `test_media_cue_fading.py`:
  - MediaCue with Volume only: FaderGroup has 1 fader (backward compat)
  - MediaCue with Volume + VideoAlpha: FaderGroup has 2 faders
  - MediaCue with neither: `_can_fade()` returns False
  - Fadeout calls FaderGroup.fade with [0, 0] for dual faders
  - Fadein calls FaderGroup.fade with [volume.volume, alpha.alpha]

**E2E tests** (via test_harness):
- `test_video_fading.py`:
  - Play video cue with FadeInStart -> `fadein_start` signal fires, `fadein_end` follows
  - FadeOutStop on video cue -> `fadeout_start` signal fires, cue stops after fade
  - Interrupt during fade -> fade stops, cue stops immediately
- `test_video_looping.py`:
  - Set video cue loop=2, play -> cue loops twice then stops (verify via `end` signal timing)
  - Video cue with VideoAlpha + loop=1 -> loops without glitch (regression test for PR #349)
- `test_video_crossfade.py`:
  - GroupCue playlist mode with 2 video cues, crossfade=2s
  - Play group -> first video plays
  - Near end of first video: both `fadeout_start` on first and second video starts
  - Group completes after second video ends

### Phase 3 Manual Verification
- FadeOutStop on video cue -> audio fades to silence AND video fades to black simultaneously
- FadeInStart on video cue -> both fade in
- Configure video output to secondary display -> window appears on correct screen
- GroupCue crossfade between video cues -> smooth audio+visual transition
- Video looping works with VideoAlpha in pipeline

---

## Phase 4: Polish & Edge Cases ✅

### Step 4.1: Auto-detect file type when adding cues *(includes Phase 2 review M1)* ✅

`add_cue_from_urls()` (the drag-and-drop path) currently combines only `audio` + `video` extensions, then always creates audio cues via `UriAudioCueFactory`. Image files are silently discarded, and video files get the wrong factory.

**Fix**: Route by extension category in `add_cue_from_urls()`:
- Image extensions (jpg, png, bmp, etc.) → `add_image_cue_from_files()`
- Video extensions (mp4, mkv, webm, etc.) → `add_video_cue_from_files()`
- Audio extensions (wav, mp3, flac, etc.) → `add_cue_from_files()` (existing behavior)

Extension-based routing covers all practical cases. `GstPbutils.Discoverer` is not needed — ambiguous containers (e.g., audio-only `.mp4`) work fine through `UriAVInput`, which already removes the unused video branch when no video stream is found (fixed in Phase 1 review H2/H3).

### ~~Step 4.2: Handle audio-only files in UriAVInput gracefully~~ ✅

Already implemented. `UriAVInput.__on_no_more_pads()` removes the unused video branch (queue, convert, scale) when no video pad is linked, and removes the unused audio branch when no audio pad is linked. Unit-tested in `tests/plugins/gst_backend/test_uri_av_input.py::TestNoMorePads`.

### ~~Step 4.3: Video window shows black between cues~~ ✅

Already implemented. `VideoOutputWindow` sets `background-color: black` on the central widget. `VideoSink.stop()` calls `window.clear_display()` which hides the native render widget, revealing the black background. `VideoSink.play()` calls `window.show_display()` before rendering starts.

### Step 4.4: Update GstPipeEdit for mixed pipelines ✅

`GstPipeEdit.__init_available_plugins()` shows ALL plugin elements regardless of the pipeline's media type. Users can add `VideoAlpha` to an audio pipeline or `Pitch` to an image pipeline, creating broken pipelines at runtime.

**Fix**: Pass a `MediaType` context from the caller into `GstPipeEditDialog`. Filter the available plugins list to show only elements whose `MediaType` is compatible with the pipeline type:
- Audio pipeline: show `MediaType.Audio` elements only
- Video/image pipeline: show `MediaType.Audio` + `MediaType.Video` + `MediaType.AudioAndVideo` elements
- The element registry (`elements/__init__.py`) doesn't currently index by `MediaType`, so filtering should check each plugin class's `MediaType` attribute at display time

### Step 4.5: Image cue looping *(Phase 2 review M2)* ✅ (Option C: looping disabled)

Setting `loop > 0` on an image cue silently does nothing. The looping mechanism in `GstMedia` works via `SEGMENT_DONE` messages — when loops remain, it adds `Gst.SeekFlags.SEGMENT` to the seek, and on receiving `SEGMENT_DONE`, seeks back to the start. But `ImageInput` bypasses this: its timer posts `EOS` directly on the bus, which hits the `Gst.MessageType.EOS` handler and transitions to READY, never entering the `SEGMENT_DONE` loop path.

**Fix options** (choose one):
- **Option A**: Have `ImageInput._on_timer_expired()` check `GstMedia.__loop` and, if loops remain, reset its own timer + seek pipeline to start instead of posting EOS
- **Option B**: Post `SEGMENT_DONE` instead of `EOS` when loops remain, letting the existing `GstMedia` loop handler do the work
- **Option C**: Disable the loop property for image cues (simplest, if looping images isn't a real use case — slideshows use GroupCue playlist mode instead)

### Phase 4 Tests
- Unit test: `add_cue_from_urls()` routes .mp4 → video factory, .wav → audio factory, .jpg → image factory
- Unit test: GstPipeEdit filters plugins by MediaType
- E2E test: drag-drop a video file creates a video cue (not an audio cue)
- E2E test: drag-drop an image file creates an image cue

---

## Test Infrastructure

### Test Fixtures and Helpers

**New fixture** in `tests/conftest.py` or `tests/plugins/gst_backend/conftest.py`:
- `video_file` -- path to a short (~1s) test video with audio (MP4/H.264+AAC). Can be generated by `gst-launch-1.0` or stored as a small fixture file in `tests/fixtures/`
- `image_file` -- path to a small test image (PNG)
- `audio_file` -- path to a short test audio file (already exists in tests)

**Test video generation** (one-time, checked into `tests/fixtures/`):
```bash
# Generate a 1-second test video with audio (colored bars + sine tone)
gst-launch-1.0 -e \
  videotestsrc num-buffers=30 ! x264enc ! queue ! mux. \
  audiotestsrc num-buffers=44 ! audioconvert ! avenc_aac ! queue ! mux. \
  mp4mux name=mux ! filesink location=tests/fixtures/test_video.mp4

# Generate a test image
gst-launch-1.0 \
  videotestsrc num-buffers=1 ! pngenc ! filesink location=tests/fixtures/test_image.png
```

**Xvfb for headless E2E tests**: E2E tests involving video output require a virtual framebuffer. Add to CI config:
```bash
xvfb-run -a poetry run pytest tests/ -v
```

### Test File Layout
```
tests/
  fixtures/
    test_video.mp4          # Short test video with audio
    test_image.png           # Test image
  core/
    test_fader_group.py      # FaderGroup unit tests
  cues/
    test_media_cue_fading.py # MediaCue dual-fader tests
  plugins/
    gst_backend/
      test_gst_element.py    # post_link/video_src hook tests
      test_uri_av_input.py   # UriAVInput element tests
      test_image_input.py    # ImageInput element tests
      test_video_sink.py     # VideoSink element tests
      test_video_alpha.py    # VideoAlpha element tests
      test_video_output_window.py  # Window tests
      test_gst_media_pipeline.py   # Pipeline construction tests
  e2e/
    test_video_cue_lifecycle.py    # Video cue play/pause/stop
    test_image_cue_lifecycle.py    # Image cue with duration
    test_slideshow_workflow.py     # GroupCue playlist with images
    test_audio_with_image.py       # GroupCue parallel audio+image
    test_video_fading.py           # Fade operations on video cues
    test_video_looping.py          # Video loop behavior
    test_video_crossfade.py        # GroupCue crossfade with video
    test_audio_backward_compat.py  # Existing audio cues unaffected
```

---

## File Summary

### New Files (Phase 1-3)
| File | Purpose |
|---|---|
| `lisp/plugins/gst_backend/elements/uri_av_input.py` | Audio+video source (uridecodebin with A/V routing) |
| `lisp/plugins/gst_backend/elements/image_input.py` | Still image source (decodebin + imagefreeze) |
| `lisp/plugins/gst_backend/elements/video_sink.py` | Compound A/V output with post_link video wiring |
| `lisp/plugins/gst_backend/elements/video_alpha.py` | Video opacity for fade-to-black |
| `lisp/plugins/gst_backend/gst_video_window.py` | Borderless projection window |
| `lisp/core/fader_group.py` | Simultaneous multi-fader coordination |
| `lisp/plugins/gst_backend/settings/video_sink.py` | VideoSink settings page |
| `lisp/plugins/gst_backend/settings/image_input.py` | ImageInput settings page |

### Modified Files
| File | Change |
|---|---|
| `lisp/plugins/gst_backend/gst_element.py` | Add `post_link()`, `video_src()` to GstMediaElement |
| `lisp/plugins/gst_backend/gst_media.py` | Add post-link pass in `__init_pipeline()` |
| `lisp/plugins/gst_backend/gst_backend.py` | Video window, menu entries, factories |
| `lisp/plugins/gst_backend/gst_media_cue.py` | Add UriVideoCueFactory, UriImageCueFactory |
| `lisp/plugins/gst_backend/default.json` | Add video_pipeline, image_pipeline |
| `lisp/backend/media_element.py` | Add MediaType.Unknown |
| `lisp/cues/media_cue.py` | FaderGroup for dual audio/video fading |
| `lisp/plugins/gst_backend/gi_repository.py` | Add GstVideo import |

### Unchanged
All existing audio elements, GstMediaElements linking, GroupCue, CueModel, existing layouts and plugins.
