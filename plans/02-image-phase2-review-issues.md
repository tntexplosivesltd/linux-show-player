# Phase 2 Image Support — Review Issues

## Fixed (this commit)

- [x] **H1**: `MediaCue._on_eos()` / `_on_error()` crash when `__fader` is None (image pipelines have no Volume). Fixed: added None guard.
- [x] **H2**: `UriImageCueFactory` set `stop_time` but not `ImageInput.duration`, so the EOS timer used the wrong duration (always 5000ms). Fixed: factory now sets `ImageInput.duration` directly.
- [x] **H3**: `_on_timer_expired` could access stale pipeline after finalization. Fixed: local ref + None guard.
- [x] **H4**: Waveform generation attempted for image cues (no audio), producing warning logs. Fixed: `GstBackend.media_waveform()` returns None when source element has no audio; playing widget handles None.
- [x] **H5**: `VideoSink.post_link()` didn't remove unused audio sink for image-only pipelines. Fixed: detects no audio source and removes autoaudiosink.

## Medium Priority (fix before shipping)

- [x] **M1**: `add_cue_from_urls()` (drag-and-drop) ignores image extensions — only checks audio+video. Fixed in Phase 4 Step 4.1 (commit `0273cb5`): extension-based routing now creates image/video/audio cues as appropriate.
- [x] **M2**: Image cue looping silently does nothing (timer posts EOS, bypassing SEGMENT_DONE loop mechanism). Fixed in Phase 4 Step 4.5 (commit `0273cb5`): Option C — looping is disabled for image cues (`GstMedia` returns loop=0 when source element has no audio).
- [x] **M3**: ~~`ImageInput.duration` is a plain attribute, not a Property with `changed()` signal.~~ **Not a bug.** `duration` is inherited as a `Property(default=0)` from `GstSrcElement`. `self.duration = 5000` in `ImageInput.__init__` goes through the `Property` descriptor (`HasProperties.__setattr__` intercepts it). It serializes correctly and has a working `changed("duration")` signal.

## Low Priority (nice to have)

- [x] **L1**: No E2E test for image cue pause/resume cycle. Added `test_8_pause_resume` in `tests/e2e/test_image_e2e.py`: starts an 8s image cue, lets `current_time` advance to >500ms, pauses it, parks for 2s, and asserts the timer is frozen (drift <400ms). Then resumes and asserts `current_time` advances again. Verified live: frozen samples were 1003→1005ms (2ms drift across a 2s pause) and post-resume reached 1709ms.
- [x] **L2**: No E2E test for invalid/missing image file (error path). Added `test_9_missing_file` in `tests/e2e/test_image_e2e.py`: creates a cue pointing at a deliberately absent path, subscribes to both `error` and `stopped` before starting, and asserts the cue surfaces an error signal (or immediately reaches Stop) instead of wedging in Running. Verified: the cue lands in state=Error.
- [x] **L3**: `VideoSink.dispose()` conditional logic untested (double-dispose, removed branches). Fixed: `TestVideoSinkDispose` in `tests/plugins/gst_backend/test_video_sink.py` adds 5 tests (full branch removal, audio-sink removal when not already removed, skip audio when `_audio_removed=True`, skip video when `_video_removed=True`, idempotent double-dispose). Also hardened `dispose()` to be fully idempotent: guards the bus disconnect with a None-check, nulls the handler after disconnecting, and sets `_video_removed`/`_audio_removed` once their branches are torn down so a second call is a no-op (eliminates a GObject "no handler with id" warning).
- [x] **L4**: E2E uses `time.sleep()` polling instead of harness signal subscriptions. Fixed alongside Phase 1 QA-P1b: `tests/e2e/helpers.py` now exposes `subscribe_cue`, `subscribe`, `wait_for_signal`, `unsubscribe`, plus `cue_signal`/`signal_sub` context managers. `test_image_e2e.py` migrated — every state-change wait subscribes before the triggering call. Also corrected a subtle mix-up where natural EOS was waited on via the `stopped` signal: natural-EOS paths emit `end` (via `Cue._ended()`), so tests 1d/3d/4e now wait on `end`; explicit `cue.stop()` still emits `stopped`.
- [x] **L5**: `start_time` property has no effect on image cues but no guard or documentation. Fixed: added a note to `ImageInput`'s docstring explaining that still frames have no seekable position; display duration is controlled solely by the element's `duration` property. (Hiding the control in the settings panel would be a larger UX change and is deferred.)
- [ ] **L6**: Per-cue duration not configurable from file dialog (needs Phase 3 settings page).
