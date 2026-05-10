# Bug: `UriAvInput.__on_no_more_pads` false-positive splices silent-EOS into a real audio cue, stalling playback

**Status:** Fixed on `fix/uri-av-input-silent-eos-race` (2026-05-10) — `__on_no_more_pads` now decides via `decodebin.iterate_src_pads()` instead of the racy `_audio_linked` / `_video_linked` flags. See [Fix](#fix-2026-05-10) below.  
**Severity:** High — user-visible playback failure, data-correct but signal-missing  
**Component:** `lisp/plugins/gst_backend/elements/uri_av_input.py`  
**Introduced by:** master commit `91519a16` ("fix(gst): play video-only files instead of wedging on not-linked")  
**Discovered during:** manual smoke test of the `feat/nested-group-cues` branch (Phase 6)  
**Branching note:** Pre-existing master-side bug surfaced by feature work. Per project policy this fix gets its own branch off master, not bundled into `feat/nested-group-cues`.

## Symptom

User builds an `outer` GroupCue in **parallel** mode containing:
- a real audio cue (e.g. `*.mp3`), AND
- an `inner` GroupCue (any mode) containing video cues

Click Go on `outer`. **Expected:** audio plays simultaneously with the inner group's video. **Observed:** the video plays, the audio cue stalls — its row stays at `00:00.00`, no sound, never completes. The audio cue plays correctly **standalone** (no parallel group, or in a parallel group containing only audio cues).

## Smoking-gun log

In `-l debug`, while pre-arming the audio cue:

```
PreArmManager: _try_arm cue=475b2350-… reason=ArmReason.Auto already_armed=False
UriAvInput: no audio stream found, feeding silent EOS into audio branch
GStreamer-CRITICAL: gst_segment_to_running_time: assertion 'segment->format == format' failed
GStreamer-CRITICAL: gst_segment_to_stream_time: assertion 'segment->format == format' failed
PreArmManager: armed 475b2350-… (reason=ArmReason.Auto, total armed=1)
```

Cue `475b2350-…` is the audio file. `gst-discoverer-1.0` confirms it has an audio stream:
```
audio #1: MPEG-1 Layer 3 (MP3)
```

The harness still reports `_type_: GstMediaCue` — model-side everything is correct. The damage is internal to the cue's GStreamer pipeline.

## Root cause

`91519a16` added a "splice silent EOS into orphaned audio branch" path so video-only files don't wedge on `not-linked`:

```python
# lisp/plugins/gst_backend/elements/uri_av_input.py:172
def __on_no_more_pads(self, decodebin):
    if not self._audio_linked:
        # splice audiotestsrc num-buffers=0 → audio_queue
        ...
```

`_audio_linked` is set to `True` inside `__on_pad_added` after a successful `pad.link(...)` to the audio queue. The race window:

1. `uridecodebin` emits `pad-added` for the file's audio pad on its streaming thread.
2. `uridecodebin` emits `no-more-pads` on the same (or a sibling) streaming thread.
3. Both signal handlers acquire the GIL to enter Python code.
4. Under load (e.g. multiple cues running pipeline init concurrently because the user clicked Go on a parallel group), the Python interpreter can schedule `__on_no_more_pads` first — `_audio_linked` is still `False`, the silent-EOS testsrc gets spliced.
5. Then `__on_pad_added` runs, sees the audio pad, and links it to `audio_queue` — which now has TWO upstream sources.

The downstream sink prerolls on the testsrc's immediate EOS, then receives buffers from the real MP3 pad on a different segment format. That's exactly what the two `gst_segment_to_running_time` assertion warnings are reporting. The sink is in EOS state and rejects the real buffers; the cue stalls in `PAUSED → PLAYING`.

The race is invisible standalone because there's no contention — `__on_pad_added` reliably wins.

## Why this surfaced via nested groups

Nested groups put more work on the parallel-start path: `outer.__start__` iterates children, calling `child.execute(CueAction.Start)` for each. Each call spawns a worker thread (via `@async_function`). With `[audio_leaf, inner_group]`, the inner group's child playlist also fires another start, multiplying concurrent pipeline init work. The increased GIL contention makes the Python signal-callback ordering inside `uridecodebin` non-deterministic where it was effectively deterministic in single-cue scenarios.

This was completely dormant before nested groups because flat parallel groups containing audio + video files would also trigger it; the bug just wasn't tested or noticed.

## Reproduction

1. Have an audio file with a real audio stream (any MP3/WAV).
2. Have a video file (any MP4 — the master commit's silent-EOS code only fires for files where `_audio_linked` could be `False`, which includes video-only AND audio files under load).
3. Build outer-parallel containing `[audio_cue, video_cue]` (no nesting needed — the parallel group alone is enough to cause the race; nesting just makes it more reliable).
4. Click Go on outer.
5. Observe: video plays, audio stalls. Log shows the false-positive `UriAvInput: no audio stream found` for the audio cue.

The race is timing-sensitive; it may take several attempts on faster hardware. Adding nested groups (`[audio, inner_playlist[video1, video2]]`) makes it reproduce more reliably because it adds more concurrent pipeline init work.

## Why it's not always visible

- **Standalone audio cue:** no concurrent init, `__on_pad_added` runs first, `_audio_linked = True` before `__on_no_more_pads`, branch never fires.
- **Two audio cues in parallel:** both go through the same code path. If neither hits the race (most common), both play.
- **Audio + video in parallel:** the video's pipeline init is heavier (more decoder elements), giving the audio's `__on_pad_added` more time to be preempted before its handler completes the link. Reliable repro.

## Suggested fixes (in increasing order of cost)

### Option A — Defer the silent-EOS splice

Don't splice in `__on_no_more_pads` directly. Set a flag and run the splice from a `QTimer.singleShot(0, ...)` posted to the main thread. By the time the timer fires, all `pad-added` callbacks for already-emitted pads have run and `_audio_linked` is reliably set. Cost: small; the orphaned-sink wedging that `91519a16` fixed only matters at PAUSED-reached time, which happens after `no-more-pads + delta`.

### Option B — Use uridecodebin's `expected-streams` / `caps` query

Before splicing, query the media's stream count. `Gst.Discoverer` already lives in the codebase (`gst_uri_duration` uses it). If the file genuinely has an audio stream, skip the splice regardless of `_audio_linked`'s current value. Cost: medium; introduces a Discoverer call into the pad-handler hot path.

### Option C — Lock the splice/link decision

Wrap `_audio_linked` access in a mutex and have `__on_no_more_pads` check after a brief delay or after acquiring the lock that `__on_pad_added` would also need. Doesn't actually solve the race — it just moves the window.

**Recommendation:** Option A. Lowest cost, most reliable, matches the pattern used elsewhere in the codebase for "do this once the pipeline has settled."

## Workaround

Use the same media kind throughout the parallel group (all-audio or all-video). The race is timing-sensitive within `uridecodebin`'s emission of pad signals; homogeneous media types initialize at similar speeds and the audio handler tends to finish before `no-more-pads`.

## Verification path for the fix

Reuse this branch's `tests/e2e/test_nested_groups_e2e.py` as a template — replace the audio tones with a mix of audio + video files and assert both cues' `started` signals fire on outer parallel-start. The race is timing-sensitive; running the test 100× and asserting 0 failures is a reasonable bar (current behaviour fails ~50%+ on a loaded machine).

## Related

- The `gst_segment_to_running_time` warnings are mentioned as harmless in `91519a16`'s commit message ("They're transient (twice at start-up) and don't affect playback or EOS"). That note is correct only for genuinely video-only files — when the splice mis-fires, those same warnings ARE the audio stall.
- `feat/nested-group-cues` (the surfacing branch) is otherwise unaffected: its E2E uses all-audio tones and passes 17/17.

## 2026-05-04 follow-up: confirmed reproduction + symptom variants

Reproduced live against the user's LiSP instance using their actual session media (an MP3 + two MP4s). Bug confirmed; original analysis stands but the symptom presentation is more nuanced than first written up.

### Confirmed reproduction structure

The reliably-reproducing structure is the **nested** form, not flat parallel:

```
outer (parallel, default loop=false):
    audio_cue (.mp3)
    inner (playlist, loop=true):
        video1 (.mp4)
        video2 (.mp4)
```

UI build order that the user followed:

1. Add the two video files.
2. Select both, "Group selected" → resulting GroupCue switched to **playlist** mode with **loop=true**.
3. Add the audio file.
4. Move the audio cue above the inner group (so the layout is `[audio, inner_group]`).
5. Select audio + inner_group, "Group selected" → outer group, left in default **parallel** mode.
6. Click Go on outer.

The earlier write-up's "flat parallel `[audio, video]`" repro was attempted with synthetic gst-launch-generated media and **did not reproduce** at 5/5 and 30/30 iterations (`/tmp/repro_silent_eos_race.py`). Whether that is because flat parallel doesn't generate enough concurrent pipeline init work, or because the synthetic media decodes fast enough to win the race deterministically, was not isolated. The user's nested-config repro is the canonical one.

### Confirmed smoking-gun log

Captured live in the user's terminal at `19:30:30.353` while the test harness was driving `cue.start` on the outer group:

```
2026-05-04 19:30:30.353  UriAvInput: no audio stream found, feeding silent EOS into audio branch
(python:24498): GStreamer-CRITICAL **: 19:30:30.421: gst_segment_to_running_time: assertion 'segment->format == format' failed
(python:24498): GStreamer-CRITICAL **: 19:30:30.421: gst_segment_to_stream_time: assertion 'segment->format == format' failed
(python:24498): GStreamer-CRITICAL **: 19:30:30.503: gst_segment_to_running_time: assertion 'segment->format == format' failed
(python:24498): GStreamer-CRITICAL **: 19:30:30.503: gst_segment_to_stream_time: assertion 'segment->format == format' failed
```

The cue ID in the surrounding harness traffic resolves to the audio cue (`fd6a306f-…`, a real `.mp3`). `gst-discoverer-1.0` confirms it has an audio stream.

### Symptom variants (intermittent)

The race fires intermittently across start/stop cycles on the same session. **Two distinct downstream symptoms** were observed for what is the same root-cause race:

- **Variant A — hard stall (originally reported).** The audio cue's row stays at `00:00.00`, no audio is heard, the cue never completes. `cue.current_time()` stays at `0`. This is the case the original write-up describes.
- **Variant B — silent advance.** The audio cue's `current_time` advances linearly with wall-clock time (e.g. observed `current_time` going `4 → 4531ms` over 4.5s via the harness) — yet the smoking-gun log line and the `gst_segment_to_running_time` assertions still fire. Whether actual audio is heard in this variant is uncertain; the harness can only see `current_time`, not whether the audio sink is producing samples.

The variant likely depends on which upstream source's data reaches the audio sink first after the silent-EOS splice mis-fires:
- If the testsrc's EOS prerolls the sink before the real MP3 pad's first buffer arrives → sink is in EOS state, rejects real buffers → variant A (clock doesn't advance because there's nothing being clocked).
- If the real MP3 pad's segment + first buffer arrives first and the testsrc's EOS comes later → sink prerolls on real data, clock advances against real-pad timestamps, but the EOS may still terminate the sink prematurely or produce silence. → variant B.

This is hand-wavy; precise sink behaviour was not traced. **What matters for the fix:** in both variants the silent-EOS source has been spliced where it shouldn't be, and the GStreamer-CRITICAL assertions are firing — meaning the pipeline is in an invalid state. The fix is to prevent the spurious splice; the variant distinction is a downstream symptom of the same root cause and goes away when the splice no longer mis-fires.

### Hit rate (this hardware, this evening)

Loose observation, not a controlled experiment:

- Single harness-driven observer run: smoking-gun log line confirmed firing once during a single observer run while the user watched (`19:30:30.353` timestamp, see "Confirmed smoking-gun log" above).
- Manual UI repro on the user's hardware: smoking-gun observed multiple times across the evening, intermittent, no measured hit rate.
- **Harness `cue.start` RPC does NOT reliably trigger the race.** `/tmp/loop_observe.py` running `layout.stop_all → cue.start(outer)` in a tight loop hit 0/10 stalls on a clean run. The harness path may serialise enough on `invoke_on_main_thread` to push pad-added through deterministically before no-more-pads.
- **Manual keyboard "Go" path DOES reliably trigger it.** The user reproduced cleanly seconds after the 0/10 harness loop completed by selecting the outer group in the list layout and pressing `Space` (the keyboard Go binding). This is the most reliable trigger seen tonight. The keyboard-Go path goes through a different start dispatch (`Layout.go` / cue-list action handler) than `cue.start` RPC; whatever ordering or threading difference it introduces is where the GIL contention window opens.
- **Implication for the fix's E2E:** asserting the fix via the harness alone may be insufficient, since the harness path doesn't surface the race. The E2E should drive the start through the same path the user does (e.g. `layout.go` if exposed, or simulating the keyboard event), or accept that the fix is verified by inspection + before/after manual UI testing rather than by automated repro.

### Updated workaround

Same as before (use homogeneous media types in parallel groups), with the additional note that **even when the smoking-gun log fires, audio playback may *appear* correct** (variant B). If you see the `UriAvInput: no audio stream found` log line for any cue you know has audio, treat that cue's playback as suspect regardless of whether `current_time` is advancing in the UI.

### Verification path for the fix (refined)

The original write-up's "100x with 0 failures" test bar still applies, but the assertion needs to be on the **smoking-gun log line and the `gst_segment_to_*` assertions**, not solely on `audio.current_time` advancing. Variant B would let a current_time-only check pass while the bug is still firing.

Recommended assertions per iteration:
1. No log line matching `UriAvInput: no audio stream found.*audio` for any cue that genuinely has an audio stream.
2. No `gst_segment_to_running_time: assertion .* failed` lines emitted between iteration start and assert point.
3. Audio cue's `current_time` advances by ≥ ~80% of wall-clock between two samples taken ~1s apart.

### Minimal repro artifact (this branch)

`/tmp/repro_silent_eos_race.py` and `/tmp/observe_bug.py` were the throwaway scripts used tonight. They are NOT checked in. The eventual fix branch should land a proper E2E based on `tests/e2e/test_nested_groups_e2e.py`, using the nested-with-loop structure documented above.

## Fix (2026-05-10)

Landed on `fix/uri-av-input-silent-eos-race`. The recommendation in the original write-up was Option A (defer the splice via `QTimer.singleShot(0)`); the branch went with a stronger alternative — call it **Option D** — that avoids the timing dependency entirely.

### What changed

`__on_no_more_pads` no longer reads `_audio_linked` / `_video_linked` to decide whether to splice. It calls a new `__streams_present(decodebin)` helper that walks `decodebin.iterate_src_pads()` and classifies each pad by caps prefix (`audio/` vs `video/`). The flags remain in place to guard against duplicate-link in `__on_pad_added`, which is unrelated to the race.

The key insight is that the GStreamer `no-more-pads` contract guarantees all pads are physically present on the bin at the C level by the time the signal fires — only their Python-side `pad-added` notification callbacks may still be queued. Iterating `iterate_src_pads()` therefore observes the source of truth directly and is race-free regardless of how the interpreter schedules the pending pad-added handlers.

### Why D over A

| | Option A (defer splice via `QTimer.singleShot(0)`) | Option D (inspect `decodebin` pads) |
|---|---|---|
| Race-freeness | Timing-based: relies on the main thread's deferred slot running after pending pad-added Python callbacks | Deterministic: pads are physically attached at signal time per GStreamer contract |
| Coupling | Adds Qt timer dependency inside a GStreamer streaming-thread handler; complicates lifetime if the cue is disposed before the timer fires | Pure GStreamer; no new lifetime concerns |
| Failure mode if assumptions are wrong | Same race, narrower window | None — pads can't disappear between `no-more-pads` and the iteration that follows it on the same call frame |

Option B (`Gst.Discoverer`) was a heavier version of the same idea — re-decode the file just to count streams. The decodebin already has its pads attached; no need to re-discover.

Option C (lock around the splice/link decision) was correctly dismissed in the original write-up: locking can't make the audio pad's pad-added Python callback run *before* `no-more-pads` is processed; it can only serialise access to a flag that's still racy.

### Verification

- New unit tests in `tests/plugins/gst_backend/test_uri_av_input.py::TestNoMorePadsRaceFix` exercise the splice decision against a `Gst.Bin` populated with controlled src pads. The four cases (`audio_pad_present_no_splice_despite_flag_false`, `video_pad_present_no_splice_despite_flag_false`, `both_pads_present_no_splices`, `no_pads_both_splices`) are deterministic and *all four fail on master code* — the unit suite is the primary regression for this fix.
- Existing `TestNoMorePads` cases were migrated to use the same fake-decoder helper rather than setting the now-irrelevant `_audio_linked` flags. Behaviour expectations are unchanged.
- E2E: `tests/e2e/test_uri_av_input_silent_eos_race_e2e.py` builds the canonical reproducer (audio + nested-playlist-loop[video, video] inside a parallel group) and drives it via `layout.go` (the keyboard-Go dispatch). Empirically the harness `layout.go` path *does* trigger the race on synthetic media — running this E2E against master (uri_av_input.py reverted) reproduced variant A in 4 of 5 iterations (audio `started` signal fires, but `current_time` stays at 0). With the fix in place, the same run is 5 of 5 with `current_time ≥ 1199 ms`. The "smoking-gun" log line and the `gst_segment_to_*_time` GStreamer-CRITICAL warnings did *not* fire in that particular reproduction — those symptoms are intermittent (the bug doc's 2026-05-04 follow-up already noted this); the `current_time` assertion is the primary regression check.
- Original `91519a16` regression (`tests/e2e/test_video_e2e.py` Test 8 — video-only MP4) still passes, confirming the orphan-branch wedging that motivated the splice is still handled.

### What this fix does *not* change

- The flags `_audio_linked` / `_video_linked` are kept for `__on_pad_added`'s duplicate-pad guard. Removing them would merge two responsibilities and isn't worth the churn.
- Behaviour of files with genuinely missing audio or video streams: identical to pre-fix. The splice fires when (and only when) `iterate_src_pads()` confirms the corresponding kind is absent.

### Out of scope on this branch

- Improving the harness `cue.start` RPC to reliably reproduce the race for automated regression. The Layout.go path appears to dispatch through a different threading topology than `cue.start`; analysing that and synthesising the same contention pattern from RPC would be valuable but is bigger than this fix.
