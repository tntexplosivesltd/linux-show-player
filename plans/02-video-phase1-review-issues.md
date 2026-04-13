# Phase 1 Video Support — Review Issues

## High Priority (fix now)

- [x] **H1**: `VideoSink.stop()` sets video sink to NULL independently of pipeline state. Fixed: removed stop() override, added dispose().
- [x] **H2**: Audio-only files through `UriAvInput` leave a dangling video branch. Fixed: `__on_no_more_pads` removes unused video branch + logs.
- [x] **H3**: Video-only files starve the audio chain. Fixed: `__on_no_more_pads` removes unused audio branch.
- [x] **QA-P0a**: `__on_pad_added` untested. Fixed: 6 unit tests covering audio/video/null/unknown/duplicate/failure.
- [x] **QA-P0b**: Full production pipeline untested. Fixed: 4 new pipeline tests including full Volume+DbMeter+VideoSink.
- [x] **QA-P0c**: E2E test video had mismatched audio/video duration. Fixed: matched buffer counts, extended to 10s.
- [x] **QA-P0d**: No EOS test. Fixed: test_4_natural_eos with 2s short video.

## Medium Priority (fix before shipping)

- [x] **M1**: Redundant `ElementType = ElementType.Input` on `UriAvInput`. Fixed: removed.
- [x] **M2**: `VideoSink.post_link()` silent when no video source. Fixed: added debug log.
- [x] **M3**: `VideoSink` missing `dispose()`. Fixed: added.
- [x] **M5**: `pad.link()` return values not checked. Fixed: checked + logged.
- [x] **M6**: Duplicate pads not guarded. Fixed: `_audio_linked`/`_video_linked` flags.
- [x] **QA-P1a**: E2E video too short (3s). Fixed: extended to 10s.
- [ ] **QA-P1b**: E2E uses `time.sleep()` polling instead of harness signal subscriptions.
- [ ] **QA-P1c**: No seek or loop E2E tests.

## Low Priority (nice to have)

- [ ] **L1**: `has_audio()`/`has_video()` unused — add TODO or remove.
- [ ] **L2**: `UriAvInputSettings.select_file` filter shows "All files" only — use video extensions.
- [ ] **L3**: No unit tests for `UriVideoCueFactory`.
- [ ] **L4**: No unit test for `GstBackend.add_video_cue_from_files`.
- [ ] **L5**: `MediaType.Unknown` added but unused — add comment or remove.
