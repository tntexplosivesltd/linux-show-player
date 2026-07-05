# Bug: image→video trigger handoff leaves projection wedged on image's last frame (and the residual playlist first-transition flicker)

**Status:** Symptom A FIXED (2026-06-20) via Option 3 (image-fronted pipelines → NULL on EOS); pixel-verified against an automated reproducer. Options 2 and 1 were implemented and empirically refuted first. Symptom B (video→video flicker) is NOT yet addressed — deliberately out of Option 3's scope. Diagnostic logging still in tree, to be stripped before merge. See [Resolution](#resolution-2026-06-20).
**Severity:** Medium-High — the image→video trigger case is a hard wedge (operator sees image, video plays underneath) on the first transition of a given pair. Subsequent transitions in the same session work.
**Component:** `lisp/plugins/gst_backend/elements/video_sink.py`, `lisp/plugins/gst_backend/gst_media.py`
**Related:** [`docs/bugs/2026-05-23-video-sink-stale-frame-bleedthrough.md`](./2026-05-23-video-sink-stale-frame-bleedthrough.md). The bleedthrough fix architecture (deferred-clear + first-buffer probe) is correct and stays. This investigation is a separate GL/X11 issue layered underneath.

## Symptoms

Two related symptoms emerged during testing of `~/bronwyn_show_music/test_3.lsp`:

### Symptom A — image→video trigger wedge (primary)

Setup: an `ImageInput` cue (`Legion_Wallpaper_1920x1080`) has its `Ended` trigger wired to start a `UriAvInput` video cue (`Task 3 ｜ #HomeTasking [...]`).

First time through:
- Image plays to its display duration, EOS fires, video is triggered.
- **Audio of the video plays normally** (pipeline reaches PLAYING, decoders run).
- **Projection surface stays on the image's last frame** for the entire video.

If the operator manually stops the wedged video and re-triggers it directly (no image in between), it renders correctly. The wedge is specifically the cold *image-sink → video-sink handoff*.

### Symptom B — first-cue-transition flicker in playlist groups (original report)

Already in `docs/todo.md` under Video pipeline. First inter-cue boundary in a playlist `GroupCue` shows a brief flicker; subsequent transitions in the same playlist (incl. loop iteration 2+) flow cleanly. Likely the same root cause as A but with milder presentation because both sides are video (no `imagefreeze` keeping a frame pinned).

## Root cause (confirmed)

The projection window's render widget is a process-wide singleton — its X11 XID is shared by every cue's `glimagesink` via the synchronous `prepare-window-handle` bus message. So **multiple `glimagesink` instances all hold `set_window_handle(XID)` for the same X11 surface concurrently.**

When a cue reaches natural EOS, `GstMedia.__on_message` transitions the pipeline to **`Gst.State.READY`** (not `NULL`). The `glimagesink` element stays alive in READY, **still holding its EGL/GLX context bound to the shared XID**. This is desirable for warm restart (next loop iteration restarts from PAUSED rather than rebuilding from scratch — see [Tradeoff](#tradeoff)).

The wedge happens because:

1. The outgoing sink's GL state on the X11 surface is *retained* across READY.
2. The incoming sink's `glimagesink` *can* produce buffers and even reach PLAYING (audio is heard, the first-buffer pad probe fires, `_show_displays` runs).
3. But its `eglSwapBuffers` does not become visible. The X server / GL driver appears to still treat the outgoing sink's surface as the active presentation surface — the incoming sink's draws go to a back/orphaned buffer.

After enough wall-clock time (operator-scale gap, seconds), the GL driver releases the outgoing sink's surface association naturally, and a fresh re-trigger of the incoming cue renders correctly. Hence "second re-trigger works."

### Diagnostic evidence

`[FLICKER-DIAG]` log lines added across `video_sink.py`, `gst_media.py`, `image_input.py` produced this timeline from a clean test_3 run:

```
22:27:23.110 VideoSink.__init__ iid=1 pipeline=pipeline0   ← video cue's sink built at session load
22:27:23.198 VideoSink set_window_handle iid=1 handle=37748751 target=monitor
22:27:23.233 VideoSink set_window_handle iid=1 handle=37748747 target=projection
22:27:23.279 VideoSink.__init__ iid=2 pipeline=pipeline1   ← image cue's sink built
22:27:23.360 VideoSink set_window_handle iid=2 handle=37748751 target=monitor
22:27:23.395 VideoSink set_window_handle iid=2 handle=37748747 target=projection
22:27:23.458 PreArmManager: session_loaded but pre-arm is disabled

22:27:27.945 VideoSink.play ENTER iid=2 state=ready prev=None
22:27:27.949 VideoSink.play PROBE-INSTALLED iid=2
22:27:28.102 VideoSink.__on_first_buffer iid=2
22:27:28.103 VideoSink._show_displays iid=2                ← image renders ✓

22:27:32.945 ImageInput posting EOS on pipeline=pipeline1
22:27:32.946 GstMedia EOS pipeline=pipeline1 → READY
22:27:32.954 VideoSink.stop ENTER iid=2 state=ready prev_is_self=True pending_probe=False
22:27:32.956 VideoSink.play ENTER iid=1 state=ready prev=None       ← 2 ms after image stop
22:27:32.961 VideoSink.play PROBE-INSTALLED iid=1
22:27:33.087 VideoSink.__on_first_buffer iid=1             ← video DOES produce a buffer
22:27:33.087 VideoSink._show_displays iid=1                ← Qt show runs (widget already visible, no-op)
                                                            ← but screen still shows image
```

What this rules in:
- The pipeline reaches PLAYING (audio plays, first-buffer probe fires).
- `_show_displays` correctly runs on the incoming sink.
- The handoff is on the order of **2 ms** — well below any GL-driver cleanup window.

What this rules out:
- Not a `_show_displays` timing issue (it fires; the widget was already visible from the image anyway).
- Not a `prepare-window-handle` ordering issue at the Python level (both sinks bound the same XID at session load; the binding doesn't change at handoff time).
- Not a `pre-arm` interaction — disabling `preArm.enabled` in `lisp.json` produced identical traces and identical symptom.

### The decisive experiment

A temporary diagnostic flag `_FLICKER_EXP_FORCE_NULL` in `gst_media.py` makes the EOS handler additionally drive the pipeline to `NULL` (which fully tears down `glimagesink` and releases the GL context):

```python
if _FLICKER_EXP_FORCE_NULL:
    self.__pipeline.set_state(Gst.State.NULL)
    self.__pipeline.get_state(Gst.SECOND)
```

With this flag `True`:
- **The image→video wedge goes away.** Video renders correctly on first trigger.

This is the smoking gun: when the outgoing sink is fully disposed, the incoming sink's surface claim succeeds. The retained GL state in READY is what was blocking it.

## Tradeoff

Forcing pipeline → NULL on EOS as a blanket policy is too aggressive. It breaks the warm-restart property that playlist looping relies on:

- **Before** (pipeline → READY on EOS): `~/bronwyn_show_music/test_video_loop.lsp` — a 2-cue playlist with `loop=true` — has seamless cue1 ↔ cue2 looping from iteration 2+ onward, because each cue's pipeline is restarted from a hot READY state (fast PAUSED preroll).
- **With FORCE_NULL**: every EOS rebuilds the next iteration from scratch (cold pipeline construction, cold preroll). The loop is no longer seamless; there's a perceptible gap at every transition.

So the proper fix needs to **release only the GL surface binding** on the outgoing sink (so the incoming sink can take over), **not tear down the whole pipeline**. The hot pipeline in READY needs to remain hot for warm restart.

`_FLICKER_EXP_FORCE_NULL` is currently set to `False` (disabled) so the loop case is unblocked. Kept in code as an A/B affordance for the next session.

## Handoff (2026-05-29)

### Current working-tree state — `fix/video-playlist-first-transition-flicker` (UNCOMMITTED)

```
modified:   lisp/plugins/gst_backend/elements/image_input.py    (+5 -2)
modified:   lisp/plugins/gst_backend/elements/video_sink.py     (+74 -6)
modified:   lisp/plugins/gst_backend/gst_media.py               (+27 +0)
```

All changes are **diagnostic logging** (`[FLICKER-DIAG]` prefix, `logger.info`) plus the `[FLICKER-EXP]` flag in `gst_media.py` (currently `False`). No behaviour changes from upstream. Unit suite is green (1318 unit tests, 234 in `tests/plugins/gst_backend/`).

The logging is useful for resuming the investigation. Decision for next session: keep it during fix development, then strip before merge.

### Design options for the surgical fix

Four options, ordered by my current preference:

**Option 2 — Re-claim handle on incoming sink at `play()` time.** At the start of `VideoSink.play()`, call `set_window_handle(XID)` again on `self.video_sink` (and `monitor_sink`) so the incoming sink becomes the most-recently-bound claimant. Smallest possible change. Hinges on whether the GL/X driver follows "last bind wins" semantics — if it does, this transfers presentation rights without touching the outgoing sink. If it doesn't (driver caches per-EGL-surface state at *creation time* rather than *bind time*), this won't help.

**Option 1 — Release outgoing sink's handle in incoming sink's `play()`.** Walk to the previous sink and call `set_window_handle(0)` on its `glimagesink`, detaching it from the X11 surface. The outgoing pipeline stays in READY. Risk: on the outgoing cue's next replay, `glimagesink` may not re-post `prepare-window-handle` (it's only posted on initial element setup), so the cue may never re-claim the surface. Needs a round-trip test: does `set_window_handle(0)` → later `set_window_handle(XID)` restore visibility?

**Option 3 — Force NULL only for `ImageInput`-fronted pipelines.** Narrow the blast radius of force-NULL: imagefreeze is cheap to rebuild (no decode chain — single decoded frame, no demuxer, no codec init), so the cost of force-NULL on images is small. Loop case (video→video) keeps current READY behaviour. Risk: does not address the documented playlist video→video flicker (`docs/todo.md` first-cue-transition flicker entry); only mitigates the image-specific wedge.

**Option 4 — Dispose only the projection-side sink element on EOS, keep the rest of the pipeline.** `pipeline.remove(video_sink)` + `pipeline.remove(monitor_sink)` on EOS, with `post_link` re-run on next play to rebuild them. Most surgical at the resource level but requires non-trivial code changes to make selective rebuild work cleanly.

### Recommended next step

Start with **Option 2** — single-line change, runs against the same `test_3.lsp` repro. If it works, also confirm `test_video_loop.lsp` still loops seamlessly (it should — the outgoing sink's pipeline is untouched). If Option 2 doesn't visibly fix the wedge, escalate to Option 1, then Option 3.

In all cases, the gating tests are:
1. **Image→video trigger** (`~/bronwyn_show_music/test_3.lsp`): video must render on first trigger, not just after re-trigger.
2. **Playlist loop seamlessness** (`~/bronwyn_show_music/test_video_loop.lsp`): cue1 → cue2 → cue1 must remain perceptibly seamless from iteration 2 onward.
3. **Standalone stop → black** (`docs/bugs/2026-05-23-video-sink-stale-frame-bleedthrough.md` half 1): manual stop with no follow-up must still clear projection to black after ~100 ms.
4. **Existing unit suite**: `poetry run pytest tests/plugins/gst_backend/` — all 234 tests green.

### What was ruled out during this session

- Pre-arm ordering hypothesis (last-set-window-handle wins): disabling `preArm.enabled` did not change the symptom.
- `_show_displays` timing / widget mapping at the Qt level: the show call runs at the right moment; the widget is already visible from the image cue.
- `_previous_sink` cross-contamination: at the moment of video's `play()`, `_previous_sink` is already `None` (cleared by image's `stop()`).
- The bleedthrough-fix architecture (deferred clear + first-buffer probe): still correct; the wedge is an unrelated layer underneath.

### Why the `_previous_sink` comment is still aspirational

`video_sink.py:67-68` says:
> Track the last VideoSink that rendered, so we can release its GL context before a different sink takes over.

The intent matches exactly the surgical fix shape we now need. `play()` currently only reassigns the variable. Whichever option above lands, it'll likely be implemented by hanging the release/re-claim logic off that pre-existing affordance.

## Resolution (2026-06-20)

### Outcome

Symptom A (image→video wedge) is **fixed**. The decisive finding: **`set_window_handle` bind/unbind does NOT transfer GL-surface presentation ownership between two live `glimagesink` instances sharing one XID — only destroying the outgoing sink's GL context (state → NULL) does.** This invalidated the two options the handoff recommended trying first:

- **Option 2 (re-bind incoming sink at `play()`) — REFUTED.** Implemented; logs confirmed the re-claim ran on the incoming sink immediately before its first buffer, yet the projection stayed wedged on the image's last frame. Re-issuing the handle the sink already holds is a no-op for presentation rights (the driver caches per-surface GL state at context-creation time, not bind time — exactly the risk the handoff flagged).
- **Option 1 (release outgoing sink's handle, then re-assert incoming) — REFUTED.** Implemented `_take_surface` / `_release_window_handles` hung off a new `_surface_owner` class var (since `_previous_sink` is already `None` at handoff). Logs confirmed the outgoing image sink's handles were set to 0 and the incoming video sink re-claimed — yet still wedged. `set_window_handle(0)` in READY does not tear down glimagesink's EGL surface/context; the surface stays owned.
- **Option 3 (NULL only image-fronted pipelines) — LANDED.** On EOS, if the media's source is an `ImageInput` (imagefreeze), drive the pipeline to `NULL` (fully releasing the GL context) instead of parking it in READY. Video-fronted pipelines are untouched — they still go to READY — so playlist-loop warm restart is preserved. Images are cheap to rebuild (single decoded frame, no demuxer/codec), so the lost warm restart is negligible.

The fix is ~10 functional lines in `gst_media.py`: a `__is_image_fronted()` helper + a conditional `set_state(NULL)` in the EOS handler. All Option 1/2 code was reverted; `video_sink.py` is back to diagnostic-logging-only.

### How it was verified — automated pixel reproducer

The existing E2E suites never caught this (they assert cue *state* and `current_time`, both of which advance normally during the wedge — it is presentation-only). Built a pixel-level verifier (`scratchpad/verify_wedge.py`, not yet promoted) that:

- adds a solid-**red** image cue and a **green moving-ball** video cue, **video first** so the video sink binds the shared XID *before* the image's — the ordering is essential: the wedge only manifests when the incoming (video) sink holds the *older* bind and the outgoing (image) holds the newer one (mirrors `test_3.lsp`, where the video cue precedes the image in the list);
- plays the image, and on its `end` signal immediately starts the video (the cold handoff);
- captures the projection render surface by its XID (`import -window <handle>`) and checks **mean colour** (red ⇒ wedged) and **frame-to-frame motion** (frozen ⇒ wedged) — two independent signals that agree.

Validated as a true detector by A/B: with the fix disabled it reports `WEDGE PRESENT: True` (projection stays red, motion 0.0); with Option 3 it reports `PASS` (black, motion present). The known-good `FORCE_NULL`-everything experiment also passes, confirming the harness reproduces the documented decisive experiment.

### Gating-test results

1. **Image→video wedge** — FIXED (pixel-verified; reproducibly wedged on baseline, clean with fix).
2. **Playlist loop seamlessness** — preserved by construction (video pipelines hit the identical `set_state(READY)` path; the NULL branch is unreachable for them). `tests/e2e/test_video_e2e.py` 35/35 green incl. the loop test.
3. **Standalone stop → black** — `tests/e2e/test_video_window_e2e.py` 31/31 green (deferred-clear path unchanged).
4. **Unit suite** — `tests/plugins/gst_backend/` 234/234 green.

## Symptom B investigation (2026-07-05) — root cause CONFIRMED, not yet fixed

Symptom B is real and now **consistently reproduced and root-caused** — but the
mechanism is *not* what the handoff section guessed (it is not the deferred
clear, and not the outgoing sink retaining its context). It is the **incoming
sink's first-ever GL presentation to the shared XID rendering ~2 black frames.**

### How it was reproduced

Diagnostic harness (`scratchpad/diag_symptom_b*.py`): loads the real
`~/bronwyn_show_music/test_video_loop.lsp` (looping playlist GroupCue,
crossfade=0, two 1080p H.264 clips) and records the projection surface at 60fps
via `ffmpeg -f x11grab -window_id <render-widget-XID>` (XGetImage — occlusion
independent; a screen-region grab gave false blacks from occlusion and must not
be used). Whole-window average luma per frame; a full render-widget black drops
the average to ~0.

Result, identical across 3 runs:

```
t≈0.0s    ~0.8s DARK      (startup, before first cue shows — expected)
t≈11.1s   33ms  DARK  ←   first A→B transition: 2-frame black FLICKER
t≈21.2s   (none)          B→A transition: clean
t≈31.5s   (none)          second A→B transition: clean
```

Exactly the reported signature: **first inter-cue boundary flickers, all
subsequent transitions (incl. loop iteration 2+) are clean.**

Note: reproduction requires **loading the saved session** (sinks constructed at
session load, before the video window is fully realised). Runtime cue-add
(the E2E-helper path) does *not* reproduce it — so the permanent regression
test for this must load a session file, not add cues via the harness.

### What was refuted

- **H2 — deferred clear firing black.** Refuted by the log: on every
  transition the next child's `play()` runs 2–9 ms after the previous child's
  `stop()`, resetting `_pending_clear` long before the 100 ms `QTimer`; the
  timer then no-ops. The render widget is **never hidden** during a playlist
  transition. `_maybe_do_clear`'s window is not the cause.
- **H3 — render-widget unmap/remap.** Same evidence: widget stays mapped.
- **Pre-arm as mitigation.** `preArm.enabled` defaults to `true` and *was* on in
  both the flickering and the clean runs; the cues still play from `state=ready`
  (cold ~100–185 ms preroll), i.e. **pre-arm does not reach playlist-group
  children**, so it neither causes nor cures B.

### Root cause (confirmed)

Each `glimagesink` sharing the one projection XID paints ~2 black frames the
**first** time *it* presents to that surface (GL swapchain / surface
association setup on first swap). Ordering makes only one of them visible:

- Cue A's first present happens at group start — **masked inside the startup
  black** (nothing was on screen yet).
- Cue B's first present happens at the **first A→B transition** — A's last frame
  is already on the shared surface, so B's 2 black frames are seen as a flicker.
- Every later present by either sink is instant (context already warm) → clean.

### Decisive confirmation (warm experiment)

Pre-presenting each child sink once before starting the group (`WARM=1` in the
diagnostic) removes the first-transition black entirely — luma stays bright
through the first A→B boundary, **visually confirmed on-screen by the operator**.
This proves the fix direction: the incoming sink's first (black) present must be
absorbed at a non-visible moment (e.g. during the startup black), not at a live
transition.

### Fix — DECISION (2026-07-05): defer to the video-mixing rearchitecture

The validated fix direction is "warm each video sink's first present before it
is user-visible." But warming **cannot be made silent**, and that killed it as a
standalone fix:

- A hidden preroll does NOT warm. The existing cold-play path already prerolls
  to PAUSED with the render widget hidden, yet the first *shown* present is
  still black — so the warming present must reach a **mapped** surface.
- The projection window is already **visible with its render widget shown
  (black)** at session load, before the first GO. So a warm-at-load sweep would
  briefly **flash each video cue's first frame** on the live projection.

That trades a 33 ms first-transition flicker for a visible first-frame flurry at
load — a poor deal for a one-off cosmetic glitch, and throwaway code besides.

**The proper fix is the planned video-mixing/compositor rearchitecture**
(`docs/todo.md` → Video pipeline → video mixing): a single persistent
`glimagesink` fed by a `glvideomixer`/`compositor`, with cues as mixer pads.
That removes the shared-XID cross-sink hand-off *entirely* — there is only ever
one always-warm sink — so **both Symptom A and Symptom B disappear**, and
Symptom A's `NULL`-on-EOS hack (Option 3) plus most of the deferred-clear /
first-buffer-probe machinery become unnecessary. Symptom B is therefore left
unfixed on purpose and folded into that work.

Rejected alternatives: **Option 4** (dispose sink elements on EOS) makes *every*
transition a fresh black first-present — strictly worse. **Pre-arm** cannot
help — its `_eligible()` is audio-only by design (`pre_arm_manager.py`, excludes
video and GroupCue).

### Remaining work

- **Symptom B: root-caused, deferred to the video-mixing rearchitecture** (see
  DECISION above). No runtime change was made. Characterization test
  `tests/e2e/test_video_transition_flicker_e2e.py` reports the 33 ms flicker and
  exits 0; flip its commented assertion into a real check when the compositor
  lands.
- **Diagnostic logging** (`[FLICKER-DIAG]`) is intentionally **kept in-tree at
  DEBUG level** (demoted from INFO 2026-07-05) — useful for the mixer work. Not
  to be stripped.
- ~~**Promote the pixel reproducer** to a permanent E2E regression test — this is the only automated coverage that catches the wedge class.~~ **DONE (2026-07-05):** `tests/e2e/test_video_wedge_e2e.py`. Reconstructed from this doc (the scratchpad original was lost): adds a video cue then a red image cue (video-first ordering is load-bearing), plays the image, and on its natural EOS immediately triggers the video (cold hand-off). It captures the projection render surface by its XID (`import -window <handle>`, where the handle is `VideoOutputWindow._render_widget.winId()`) and checks two agreeing signals — mean colour (red ⇒ frozen on the image) and frame-to-frame motion (zero ⇒ frozen); the video uses a television-snow pattern for an unambiguous motion signal. `mean_rgb` forces sRGB TrueColor because ImageMagick stores an all-gray capture as single-channel, which would otherwise inflate "redness". Validated as a true detector by A/B: with `__is_image_fronted` stubbed to `return False` (fix off) it reports redness ≈ 0.75 / motion 0.0 and the three pixel checks fail; with the fix on, redness 0 / motion ≈ 0.14 and all pass. The state-level checks (Running, `current_time` advancing) pass in both modes, confirming why the existing suites never caught this.
