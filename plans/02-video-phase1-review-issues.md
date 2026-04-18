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
- [x] **QA-P1b**: E2E uses `time.sleep()` polling instead of harness signal subscriptions. Fixed: `tests/e2e/helpers.py` gained signal-based helpers (`subscribe_cue`, `subscribe`, `wait_for_signal`, `unsubscribe`, and two context managers `cue_signal`/`signal_sub`). `test_video_e2e.py` rewritten to subscribe-before-action for all state-change waits (`started`, `paused`, `stopped`, `end`), removing fragile 200ms polling. Also fixed `start_lisp` which used to proceed when the harness returned a `result` for `session.info` even while `has_session` was still false.
- [x] **QA-P1c**: No seek or loop E2E tests. Added `test_6_seek` (seeks a running video to 5000ms and asserts `current_time >= 4500` plus state=Running after flush) and `test_7_loop` (sets `media.loop=1` on a 2s clip, asserts Running at t=2.5s mid-second-iteration, then natural stop by t=6.5s).

## Low Priority (nice to have)

- [x] **L1**: `has_audio()`/`has_video()` unused — removed (along with their stale tests). Production code checks for presence of `VideoSink` element instead.
- [x] **L2**: `UriAvInputSettings.select_file` filter shows "All files" only — use video extensions. Fixed: now uses `qfile_filters` with video extensions from `get_backend().supported_extensions()`.
- [x] **L3**: No unit tests for `UriVideoCueFactory`. Added: `tests/plugins/gst_backend/test_gst_cue_factory.py` covers input element, pipeline composition, cue construction, icon assignment, URI propagation, and an audio-factory regression guard.
- [x] **L4**: No unit test for `GstBackend.add_video_cue_from_files`. Added: `tests/plugins/gst_backend/test_gst_backend_add_cues.py` verifies factory input, icon, URI propagation, name derivation from filename, and command-stack submission for both video and image backends.
- [x] **L5**: `MediaType.Unknown` added but unused — removed. `UriAvInput` no longer needed it once pad detection was moved to `__on_pad_added`.
