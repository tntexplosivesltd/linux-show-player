# Bug: `VideoSink.play()` maps the projection surface before the new sink prerolls, briefly bleeding the previous cue's last frame

**Status:** Fixed on `fix/video-sink-stale-frame-bleedthrough` (2026-05-23) — `play()` now defers `show_display()` until the new sink's first buffer arrives via a pad probe on `proj_queue.src`. See [Fix](#fix-2026-05-23) below.
**Severity:** Medium — visible, brief artifact at every video/image cue transition. Not a playback failure, but cosmetically jarring under projection.
**Component:** `lisp/plugins/gst_backend/elements/video_sink.py`, `lisp/plugins/gst_backend/gst_video_window.py`
**Introduced by:** Inherent to the original video output design (`2ebafdb5` — "Add video output window with VideoOverlay and GL context management").
**Discovered:** Manual smoke testing during user-doc screenshot pass.

## Symptom

When a video or image cue starts after a previous video/image cue has played, the projection surface (and the video monitor, if open) briefly shows **a frame or two from the previous cue** before the new content takes over. The duration is approximately one preroll cycle of the new sink — ~16–33 ms on typical hardware — long enough for the audience to perceive at slower frame rates or on transitions to a markedly different image.

Affects:
- Video cue → video cue
- Image cue → video cue
- Video cue → image cue
- Image cue → image cue

Does **not** affect:
- The very first video/image cue of a session (no previous frame to bleed).
- Pre-armed cues that resume from PAUSED — the sink already holds a prerolled buffer at `play()` time (this is the new fix's "fast path").

## Root cause

The projection window is a process-wide singleton (`GstBackend._video_window`). Inside it lives a single `WA_NativeWindow` child widget (`_render_widget`) whose X11 XID is handed to **every** new cue's `glimagesink` via the synchronous `prepare-window-handle` bus message. The XID is the same XID across the lifetime of the application.

When a cue stops:

```python
# lisp/plugins/gst_backend/elements/video_sink.py — old play()/stop()
def stop(self):
    ...
    window.clear_display()    # _render_widget.hide() → XUnmapWindow
```

`clear_display()` only **unmaps** the native window — it does not clear pixel state. Modern X11 compositors (mutter, kwin, picom, etc.) cache the last-rendered contents of unmapped windows so fade-out / window-switcher animations have something to draw.

When the next cue starts:

```python
# old play()
def play(self):
    VideoSink._previous_sink = self
    window.show_display()     # _render_widget.show() → XMapWindow
    ...
```

`show_display()` runs as part of `GstMedia`'s `for element in self.elements: element.play()` loop — **before** the pipeline transitions to PAUSED for preroll. The sequence is:

1. `VideoSink.play()` calls `window.show_display()` — XMapWindow on the singleton native widget. The compositor briefly re-composites the cached contents (the previous cue's last frame).
2. `GstMedia.play()` continues: pipeline → PAUSED, blocks on `get_state(SECOND)` until preroll completes.
3. Preroll completes — the new `glimagesink` has its first buffer.
4. Pipeline → PLAYING. The sink draws the first buffer, finally overwriting the stale frame.

Between steps 1 and 4 there is a window of typically 16–33 ms during which the previous cue's contents are visible.

## Fix (2026-05-23)

Two-path `play()`:

- **Fast path** (pipeline already in `Gst.State.PAUSED`): the sink already holds a prerolled buffer (pre-armed cue, or resume-from-pause). Call `show_display()` immediately — no bleed risk, and showing immediately avoids one preroll cycle of added latency.
- **Cold-start path** (pipeline in `READY`/`NULL`): install a `Gst.PadProbeType.BUFFER` probe on `proj_queue.src`. The probe fires on the GStreamer streaming thread when the new sink's first buffer passes through; it emits a `Signal` connected with `Connection.QtQueued`, which marshals `_show_displays()` to the Qt main thread. The probe returns `Gst.PadProbeReturn.REMOVE` so it fires exactly once.

`stop()` and `dispose()` both call `_consume_first_buffer_probe()` so a cue stopped before its first buffer arrives does not leak the probe past pipeline tear-down.

### Why a pad probe and not the bus's `async-done`

`async-done` fires once preroll completes, which is the right moment in principle. But the bus subscription is shared across the entire pipeline's lifetime and would need state to distinguish "preroll of the *new* sink" from "preroll of an internal element rebuild" or "async seek complete". A buffer probe on the projection branch is unambiguous: the first buffer through `proj_queue.src` is, by construction, the first frame the new sink will render.

### Why we use `Signal` + `Connection.QtQueued` rather than `invoke_on_main_thread`

`invoke_on_main_thread` lives in `lisp.plugins.test_harness.qt_invoke` and would pull a test-harness import into the GStreamer backend. The framework already has `Connection.QtQueued` in `lisp.core.signal` for exactly this case (post a slot call to the Qt event loop from any thread); using it keeps `gst_backend`'s dependency surface clean.

## Branching note

Pre-existing master-side bug. Per project policy (see `feedback_bug_fix_branching.md`) the fix lives on its own branch off master.

## Test coverage

`tests/plugins/gst_backend/test_video_sink.py::TestVideoSinkDeferredShow`:

- `test_play_defers_show_display_in_ready_state` — cold-start: `play()` does **not** call `show_display()` on either projection window or visible monitor.
- `test_play_installs_first_buffer_probe_in_ready_state` — cold-start installs the probe on `proj_queue.src`.
- `test_play_calls_show_display_when_pipeline_already_paused` — fast path (Armed/resume): `show_display()` is called immediately, no probe installed.
- `test_stop_removes_pending_first_buffer_probe` — `stop()` before first buffer cleans up.
- `test_dispose_removes_pending_first_buffer_probe` — `dispose()` before first buffer cleans up (covers the cue-removed-mid-play path).
- `test_first_buffer_callback_clears_probe_handle` — the consume helper is idempotent and clears the stored probe id.

The visual symptom itself cannot be unit-tested without a real X server + compositor; manual verification confirmed the fix end-to-end (operator running a sequence of video/image cues sees the projection surface stay black between cues until the new sink draws).

## Notes for future work

The same singleton-XID assumption underpins the planned Wayland work (`docs/todo.md` → Video pipeline → "Native Wayland support"). The deferred-show pattern transfers cleanly: even with `waylandsink` + `VideoOverlay.set_render_rectangle()`, the surface is reused across cues, and the first-buffer probe still tells us when the new sink is ready to draw.
