# Phase 2 Image Support — Review Issues

## Fixed (this commit)

- [x] **H1**: `MediaCue._on_eos()` / `_on_error()` crash when `__fader` is None (image pipelines have no Volume). Fixed: added None guard.
- [x] **H2**: `UriImageCueFactory` set `stop_time` but not `ImageInput.duration`, so the EOS timer used the wrong duration (always 5000ms). Fixed: factory now sets `ImageInput.duration` directly.
- [x] **H3**: `_on_timer_expired` could access stale pipeline after finalization. Fixed: local ref + None guard.
- [x] **H4**: Waveform generation attempted for image cues (no audio), producing warning logs. Fixed: `GstBackend.media_waveform()` returns None when source element has no audio; playing widget handles None.
- [x] **H5**: `VideoSink.post_link()` didn't remove unused audio sink for image-only pipelines. Fixed: detects no audio source and removes autoaudiosink.

## Medium Priority (fix before shipping)

- [ ] **M1**: `add_cue_from_urls()` (drag-and-drop) ignores image extensions — only checks audio+video. → Tracked in Phase 4 Step 4.1.
- [ ] **M2**: Image cue looping silently does nothing (timer posts EOS, bypassing SEGMENT_DONE loop mechanism). → Tracked in Phase 4 Step 4.5.
- [x] **M3**: ~~`ImageInput.duration` is a plain attribute, not a Property with `changed()` signal.~~ **Not a bug.** `duration` is inherited as a `Property(default=0)` from `GstSrcElement`. `self.duration = 5000` in `ImageInput.__init__` goes through the `Property` descriptor (`HasProperties.__setattr__` intercepts it). It serializes correctly and has a working `changed("duration")` signal.

## Low Priority (nice to have)

- [ ] **L1**: No E2E test for image cue pause/resume cycle.
- [ ] **L2**: No E2E test for invalid/missing image file (error path).
- [ ] **L3**: `VideoSink.dispose()` conditional logic untested (double-dispose, removed branches).
- [ ] **L4**: E2E uses `time.sleep()` polling instead of harness signal subscriptions.
- [ ] **L5**: `start_time` property has no effect on image cues but no guard or documentation.
- [ ] **L6**: Per-cue duration not configurable from file dialog (needs Phase 3 settings page).
