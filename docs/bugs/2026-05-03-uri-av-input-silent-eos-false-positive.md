# Bug: `UriAvInput.__on_no_more_pads` false-positive splices silent-EOS into a real audio cue, stalling playback

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
