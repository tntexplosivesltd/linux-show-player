# Video Compositor Foundation — Design

**Date:** 2026-07-05
**Status:** Approved for planning
**Scope:** Foundation only (internal replumbing). The user-facing video-mixing
capability is a separate, later spec that builds on this one.

## Summary

Replace the per-cue video-sink hand-off with a single, persistent
compositor+sink pipeline that every video/image cue feeds into. This
dissolves the entire cross-sink GL-surface bug class documented in
`docs/bugs/2026-05-29-video-cross-sink-gl-surface-wedge.md` (Symptom A —
image→video hard wedge; Symptom B — video→video first-transition flicker),
retires `VideoExclusiveManager`'s reliance on sink-state introspection, and
deletes the deferred-clear / first-buffer-probe / image-NULL-on-EOS machinery
that exists only to paper over the hand-off.

**Explicit non-goal:** no operator-visible behaviour changes. One active video
at a time, the same fade in/out, the same "black on stop", and the same
seamless playlist auto-advance as today. The *only* observable difference is
that the flicker and wedge are gone. Actually mixing multiple videos on screen
(per-cue opacity, position, z-order, video crossfade) is deferred to a
follow-on spec that this foundation is deliberately shaped to accept.

## Background: why today's design produces the bug class

LiSP builds **one `Gst.Pipeline` per cue** (`GstMedia.__init_pipeline`,
`gst_media.py`). Today each video/image cue's pipeline ends in a `VideoSink`
element that owns its own `glimagesink`, and every one of those per-cue
`glimagesink`s is bound to the **one** process-wide projection window (an X11
child widget's `winId()`), via a synchronous `prepare-window-handle` bus
message. Every inter-cue transition is therefore a hand-off of a single shared
GL surface between two independently-created sinks, each with its own
`GstGLContext`:

- **Symptom A** — an outgoing image-fronted sink parked in `READY` keeps
  owning the surface's GL context; the next cue's video wedges on the frozen
  image. Currently patched by driving image-fronted pipelines to `NULL` on EOS
  (`GstMedia.__is_image_fronted`).
- **Symptom B** — each `glimagesink`'s *first* present to the shared surface is
  black (~2 frames). Cue A's is masked by startup black; cue B's lands on the
  first live transition. Currently unfixed (characterization test only).

Both are the same root cause: **N GL contexts contending for one surface, with
a hand-off on every transition.** No amount of hand-off choreography removes
the class; only removing the hand-off does.

## Architecture

### New component: `VideoCompositor`

A singleton owned by `GstBackend` (alongside `VideoOutputWindow` and
`VideoMonitorWindow`). It owns **one** persistent `Gst.Pipeline`, built at
backend init, driven to `PLAYING`, and kept warm for the entire process
lifetime:

```
videotestsrc pattern=black is-live=true ! capsfilter(W×H,fps)
    ! glupload ! glvideomixer name=mix         (sink_0 = black background, zorder 0)
mix. ! tee name=t
  t. ! queue ! glimagesink   → VideoOutputWindow  XID   (projection)
  t. ! queue ! glimagesink   → VideoMonitorWindow XID   (monitor)
```

The **permanent black background layer** is the load-bearing idea: the mixer
always produces frames, so both sinks are warm from process start and never
cold-present. Consequences:

- **Symptom B cannot occur** — the sinks' first present happened at startup,
  against black, before any cue existed.
- **Symptom A cannot occur** — there is no per-cue sink and no hand-off; one
  sink owns the surface for the process lifetime.
- **"Black between cues" is free** — it is the mixer's `background` property /
  the background layer, not a Qt widget hide. `clear_display()` /
  `show_display()` and their hide/show dance are no longer needed.
- **One `GstGLContext`** for the whole projection pipeline (`glupload`,
  `glvideomixer`, both `glimagesink`s negotiate a shared context automatically
  because they share a pipeline), instead of N contending contexts.

XID binding (`prepare-window-handle`) happens **once**, here, for both sinks,
for the process lifetime — not per cue.

### GL-first, with a system-memory fallback

Primary path is GL: `glupload` → `glvideomixer` → `glimagesink`. This keeps
compositing on the GPU, pairs natively with `glimagesink`, and is the
forward-compatible substrate for the later mixing spec. When GL elements are
unavailable, `VideoCompositor` falls back at build time (same factory-probe
pattern as today's `_create_video_sink`) to a system-memory pipeline:
`compositor ! tee ! xvimagesink`/`autovideosink`, with no `glupload` on the
inputs.

### Per-cue side: `VideoSink` internals rewritten

The element **stays registered under the name `"VideoSink"`** so existing saved
sessions' `video_pipeline` / `image_pipeline` lists still resolve — only its
internals change:

- **Audio path unchanged.** `autoaudiosink` in the cue's own pipeline, removed
  when the source has no audio (as today). Per-cue volume, fade, and routing
  are untouched. Audio never crosses into the projection pipeline.
- **Video path now ends in `appsink`** (replacing `glimagesink` + `tee` +
  monitor sink). The existing `VideoAlpha` fade element stays where it is, in
  the cue pipeline, upstream of the `appsink`, so fade in/out is unchanged.
- On `play()`: **register** with `VideoCompositor`. The compositor creates an
  `appsrc` (+ `glupload`) and a `glvideomixer` request pad (zorder above the
  background) on the projection pipeline, and starts a **pump**.
- On `stop()` / `eos()`: **unregister**. The pump stops; the mixer request pad
  and `appsrc` are released with a blocking pad-probe for clean live removal;
  the mixer reverts to the black background = "black on stop".

### The pump and A/V sync (the critical mechanism)

The `appsink` `new-sample` callback pulls each sample and pushes the **same
buffer** into that cue's `appsrc` on the projection pipeline, **preserving
PTS** and offsetting it onto the projection pipeline's running-time at
registration. For this to stay in sync with the cue's own audio (which renders
in the cue pipeline):

- `GstBackend` hands every cue pipeline the **same clock** as the projection
  pipeline (a single shared `Gst.Clock`).
- The pump computes a per-cue base-time / PTS offset at registration so the
  cue's video buffers map onto the projection running-time — the same offset
  logic that keeps the video aligned with the cue's audio.
- `appsrc` runs `format=time`, `do-timestamp=false`; the mixer syncs each pad
  to the shared clock.

Cross-pipeline A/V sync is the single biggest risk in this design and is
validated by a throwaway spike (Phase 1) before the rest is built.

### `VideoExclusiveManager` — new source of truth

Behaviour is unchanged (a second video/image cue is blocked while one is
active, with the same notification). The *implementation* re-points from
`VideoSink._previous_sink` + per-sink pipeline-state introspection to a single
query against `VideoCompositor`: "is any cue other than this one currently
registered?" Simpler and correct.

### What gets deleted

The refactor's dividend — all of this exists only to manage the hand-off it
removes:

- `VideoSink._previous_sink`, `_pending_clear`, `_maybe_do_clear`, the
  deferred-clear `Signal`/`QTimer`, and `_DEFERRED_CLEAR_MS`.
- `VideoSink._first_buffer_probe` / `__on_first_buffer` / `_show_displays` and
  the stale-frame bleed-through guard — the persistent sink never re-maps, so
  there is nothing to guard against.
- `GstMedia.__is_image_fronted()` and the image NULL-on-EOS hack (Symptom A's
  Option-3 fix). Images no longer own a GL surface; they return to normal
  `READY` parking.
- `VideoOutputWindow.clear_display()` / `show_display()` and the render-widget
  hide/show machinery. The render widget stays mapped for the process lifetime.
- All `[FLICKER-DIAG]` logging (`video_sink.py`, `gst_media.py`,
  `image_input.py`) — kept in-tree specifically to diagnose this bug class,
  removed once it is structurally gone.

## Data flow

### Start a video cue

1. `Cue.play` → `GstMedia.play` → `element.play()` for each element;
   `VideoSink.play()` registers the cue with `VideoCompositor`.
2. `VideoCompositor` adds an `appsrc` (+ `glupload`) and a `glvideomixer`
   request pad (zorder above background), and starts the pump (appsink
   `new-sample` → push buffer with offset PTS → appsrc).
3. The cue pipeline goes `PLAYING`; decoded video → `VideoAlpha` → `appsink` →
   pump → `appsrc` → mixer → tee → sinks. Audio → `autoaudiosink` in the cue
   pipeline, synced via the shared clock.
4. Video appears composited over black, in sync with the cue's audio.

### Stop / EOS

1. `VideoSink.stop()` / `eos()` → unregister from `VideoCompositor`.
2. The pump stops; the mixer request pad and `appsrc` are released under a
   blocking pad-probe; the mixer reverts to black background.
3. Cue pipeline → `READY` (video), as today. **Playlist auto-advance:** the
   next child registers within the same Qt tick; because the mixer and sinks
   are always warm, the new cue's first frame composites with no black gap —
   seamless, no flicker. **Standalone stop:** removing the only foreground pad
   leaves the black background = "black on stop".

## Error handling & graceful degradation

- **No GL:** fall back to `compositor ! tee ! xvimagesink`/`autovideosink`
  (system-memory, no `glupload`), detected at build via factory probing.
- **Projection pipeline fails to reach `PLAYING` at startup:** log a warning,
  notify the operator, and degrade gracefully (no projection) rather than
  crashing the app.
- **appsrc backpressure:** the pump is bounded (queue + drop-oldest) so a
  stalled sink can never wedge a cue's decode thread or its audio.
- **Monitor window hidden:** its tee branch uses a `leaky` queue so the monitor
  sink never back-pressures the projection branch.

## Wayland impact

This refactor makes a future Wayland port **easier**, not harder, and adds no
new windowing coupling.

- **The X11 binding surface collapses from per-cue-scattered to one persistent
  seam.** Today `prepare-window-handle` → `set_window_handle(XID)` runs
  per cue, for two sinks × N cues, on N pipelines — the exact `winId()`-as-XID
  assumption a Wayland port must rewrite (into `set_render_rectangle()` +
  sharing `wl_display` via `need-context`). After this refactor there are two
  sinks, bound once, on one pipeline.
- **GL-first is the Wayland-friendly choice.** `glimagesink` is the
  cross-platform GL sink (X11 `VideoOverlay` *and* Wayland `wl_display` /
  `GstGLDisplayWayland`); `xvimagesink` is X11-only. One shared `GstGLContext`
  (single-context-single-surface) is also the model Wayland compositors
  (EGL-native) expect.
- **The bridge is display-agnostic.** The pump, compositor, clock-sharing,
  PTS offset, and `VideoExclusiveManager` never touch windowing.

**Design note (bank it now):** `VideoCompositor`'s single sync-bus handler
implements `prepare-window-handle` today and is written to be extended with
`need-context` later, documented in-code as *"the Wayland seam: the one place a
Wayland port adapts."*

**Orthogonal caveat (unchanged):** choosing *which* monitor to project onto
still uses `set_display_screen()`'s absolute `move()` — the window-*placement*
half of the Wayland todo (needs `QWindow::setScreen()`), separate from the
sink-*binding* half. This refactor neither helps nor hurts it; it stays on the
Wayland backlog as-is.

## Testing

- **Regression proof (the reason this effort exists):** flip
  `tests/e2e/test_video_transition_flicker_e2e.py`'s currently-commented
  assertion into the hard check `dark_run <= 1`. It must now pass.
  `tests/e2e/test_video_wedge_e2e.py` (Symptom A) must stay green.
- **New E2E — A/V sync:** a clip with a coincident beep + flash; assert the
  projected flash frame and the audio transient land within tolerance. The
  acceptance test for the sync-critical claim.
- **New E2E — behaviour parity:** standalone stop → black; playlist loop
  seamless over many iterations (no dark run); second video cue still blocked
  (`VideoExclusiveManager` intact).
- **Unit:** `VideoCompositor` register/unregister bookkeeping and the
  exclusive-query logic (the parts testable without a live pipeline).

E2E tests run as standalone scripts (`poetry run python tests/e2e/…`), not via
pytest; verify no stale LiSP holds port 8070 (`pgrep -af lisp.main`) before
running.

## Phasing (for the implementation plan)

0. **Worktree setup.**
1. **Spike (throwaway, go/no-go gate):** prove cross-pipeline A/V sync *and*
   live `glvideomixer` request-pad add/remove on real media with audio. If
   sync cannot be held to tolerance, stop and reconsider the bridge before
   building anything permanent.
2. **`VideoCompositor` persistent pipeline:** black background, tee, two
   sinks, one-time XID binding, GL-with-fallback build. Verify warm black +
   monitor with no cues.
3. **Rewrite `VideoSink` internals:** `appsink` + register/unregister + pump;
   shared clock + PTS offset.
4. **Re-point `VideoExclusiveManager`** to `VideoCompositor`; delete
   `_previous_sink` et al.
5. **Remove dead machinery:** deferred-clear, first-buffer-probe, image
   NULL-on-EOS hack, `[FLICKER-DIAG]` logging, window show/hide.
6. **Tests:** flip the Symptom B assertion; add the sync + parity E2E; run the
   full unit + E2E suite.
7. **QA + code review:** `voltagent qa-expert` and `code-reviewer` subagents.

## Risks

- **Cross-pipeline A/V sync** (highest). Mitigated by the Phase-1 spike gate,
  shared clock, and PTS-preserving pump.
- **Live mixer-pad add/remove** on an always-`PLAYING` pipeline (blocking
  probes; clean `release_request_pad`). Also covered by the spike.
- **GL context / caps negotiation** across `glupload` → `glvideomixer` →
  `glimagesink`, and the GL fallback path. Validated in Phase 2.
- **Monitor branch** stalling the projection branch — mitigated by a `leaky`
  queue on the monitor tee branch.

## Out of scope (future mixing spec)

Multiple simultaneous videos, per-cue opacity/position/scale/z-order, video↔
video crossfade, and the inspector controls + commands to drive them. This
foundation is shaped to accept them (real `glvideomixer` with dynamic request
pads, one warm sink) but exposes none of them; `VideoExclusiveManager` keeps
enforcing one-at-a-time until that spec deliberately lifts it.
