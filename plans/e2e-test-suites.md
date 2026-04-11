# E2E Test Suites for Existing Features

## Context

The test harness plugin exposes 40+ JSON-RPC methods for controlling LiSP programmatically. Only two E2E test files exist (`test_groups_e2e.py`, `test_notifications_e2e.py`). Many core features — GO button sequencing, session persistence, media playback, undo/redo, action cues — have zero integration coverage. These features interact across threads (GStreamer workers, Qt main loop, timer callbacks) in ways unit tests with mocks cannot exercise.

This plan adds 14 E2E test suites in 5 phases, ordered by live-show risk. Each suite is a standalone script following the existing pattern (not pytest-collected).

## Shared Infrastructure

All suites reuse the existing pattern from `test_groups_e2e.py`:
- Same `call()`, `check()`, `wait_state()`, `cue_state()`, `cue_prop()` helpers
- Same `start_lisp()` / `stop_lisp()` lifecycle with `--no-launch` option
- Same `make_tone()` audio generator (import from a shared module or inline)
- Each file added to `tests/e2e/conftest.py` `collect_ignore` list

**Extract shared helpers first** into `tests/e2e/helpers.py`:
- `call()`, `check()`, `wait_state()`, `cue_state()`, `cue_prop()`, `make_tone()`, `start_lisp()`, `stop_lisp()`, `create_test_audio()`, CLI arg parsing
- Existing suites can be updated to import from this module later (not in scope)

### Key files
- `tests/e2e/helpers.py` (new — shared helpers)
- `tests/e2e/conftest.py` (update `collect_ignore`)
- `lisp/plugins/test_harness/client.py` (existing client, `send_request()`)
- `lisp/plugins/test_harness/handlers.py` (all 40+ harness methods)

---

## Phase 1 — Critical Live-Show Paths

### Suite 1: `test_go_standby_e2e.py` — GO Button and Standby Progression
**Tests:** `lisp/plugins/list_layout/layout.py` — `go()`, `__cue_next()`, `_advance_standby_past_children()`
**Harness methods:** `layout.go`, `layout.standby`, `layout.set_standby_index`, `cue.add_from_uri`, `cue.set_property`, `cue.state`, `signals.subscribe`/`wait_for` on `layout.cue_executed`

**Scenarios:**
1. GO starts standby cue, standby advances to next
2. GO on group child at standby does nothing
3. Standby skips grouped children with auto_continue
4. `next_action=TriggerAfterEnd` chains to next non-child cue after audio ends
5. `next_action=SelectAfterEnd` moves standby only, does not execute
6. `next_action=TriggerAfterWait` with post_wait delays then fires
7. `next_action=DoNothing` — nothing happens after cue ends
8. Rapid double-GO within goDelay fires only once
9. GO on empty list does nothing
10. `auto_continue=False` — GO fires standby cue but standby does NOT advance (distinct code branch in `go()`)
11. GO with `default_start_action=FadeInStart` — verify the fade-in path is taken via state check
12. Standby at last cue + GO — standby should stay put, not wrap or crash
13. `go_key_disabled_while_playing=True` — GO should be blocked while a cue is running

**Note on scenario 8:** The harness's `layout.go` calls `app.layout.go()` directly, bypassing `__go_slot` and the `QTimer` gate. This scenario tests the model-level debounce, not the keyboard-level `goDelay` timer. The `goDelay` path requires simulated key events which the harness does not support.

### Suite 2: `test_session_e2e.py` — Session Save/Load Fidelity
**Tests:** `lisp/application.py` — `__save_to_file`, `__load_from_file`
**Harness methods:** `session.save`, `session.load`, `session.new`, `cue.add`, `cue.add_from_uri`, `cue.update`, `cue.get_property`, `cue.list`, `commands.is_saved`, `signals.subscribe`/`wait_for` on `session.session_loaded`

**Scenarios:**
1. MediaCue with custom name, volume, fades round-trips
2. SeekCue `target_id` reference preserved
3. CollectionCue `targets` list preserved
4. GroupCue `crossfade`, `loop`, `group_mode`, `children` preserved
5. Children retain `group_id` after reload
6. Cue index ordering preserved
7. `commands.is_saved()` True after save, False after mutation
8. Load with missing child ID does not crash
9. `commands.is_saved()` True immediately after `session.load` (before any mutation)
10. Save to existing path (overwrite) succeeds
11. Load from non-existent path — app does not crash, previous session not corrupted
12. Multi-level property round-trip: `fadein_type`, `fadeout_type`, `stylesheet`, `description`
13. `session.new` while cues exist — model resets cleanly, no stale signal handlers

### Suite 3: `test_media_playback_e2e.py` — MediaCue Playback Lifecycle
**Tests:** `lisp/cues/media_cue.py`, GStreamer backend pipeline
**Harness methods:** `cue.add_from_uri`, `cue.execute`, `cue.start`, `cue.stop`, `cue.pause`, `cue.resume`, `cue.interrupt`, `cue.state`, `cue.seek`, `cue.set_property`, `signals.subscribe`/`wait_for` on per-cue `started`/`stopped`/`paused`/`interrupted`

**Scenarios:**
1. Start → state=Running, `started` signal fires
2. Pause → state=Pause, `paused` signal fires
3. Resume → state=Running, `started` signal fires
4. Stop → state=Stop, `stopped` signal fires
5. FadeOutStop: cue fades then stops cleanly
6. FadeInStart: cue starts (verify state=Running)
7. Interrupt → state=Stop, `interrupted` fires immediately
8. Seek while playing: `current_time()` moves near target position
9. Cue plays to natural end: `end` signal fires, state=Stop
10. Broken URI → state=Error, `error` signal fires
11. Stop then restart (pipeline teardown/rebuild) — cue plays correctly a second time
12. FadeOutStop followed by immediate Start — cue restarts cleanly after fade

---

## Phase 2 — High-Risk Workflows

### Suite 4: `test_wait_chaining_e2e.py` — Pre/Post-wait with next_action
**Tests:** `lisp/cues/cue.py` — `start()` pre/post-wait, `lisp/plugins/list_layout/layout.py` — `__cue_next()`
**Harness methods:** `cue.add_from_uri`, `cue.set_property`, `cue.execute`, `cue.state`, `layout.standby`, `signals.subscribe`/`wait_for` on per-cue `started`/`stopped`, `layout.cue_executed`

**Scenarios:**
1. `pre_wait=1.0s`: state=PreWait for ~1s before Running
2. Stop during pre_wait → returns to Stop immediately
3. Pause during pre_wait → PreWait_Pause; resume continues wait
4. `post_wait=1.0s` + `TriggerAfterWait`: next cue starts after wait
5. `post_wait=1.0s` + `SelectAfterWait`: standby moves, no execution
6. `TriggerAfterEnd`: next cue starts only after audio ends naturally
7. `SelectAfterEnd`: standby advances, nothing runs
8. Chain of 3 cues with TriggerAfterEnd produces sequential playback
9. Pause during PostWait → PostWait_Pause state; resume continues timer
10. `TriggerAfterEnd` on last cue in list — no crash, no chain
11. `SelectAfterWait` followed by second GO during PostWait — standby already advanced, second GO starts new standby cue

### Suite 5: `test_undo_redo_e2e.py` — Undo/Redo Stack Integrity
**Tests:** `lisp/command/` — command stack, model commands, group commands
**Harness methods:** `cue.add`, `cue.add_from_uri`, `cue.remove`, `cue.update`, `cue.set_property`, `cue.get_property`, `cue.list`, `cue.count`, `layout.move_cue`, `layout.context_action`, `commands.undo`, `commands.redo`, `commands.is_saved`, `commands.clear`

**Scenarios:**
1. Add cue → undo → count=0; redo → count=1 same ID
2. Move cue: verify order, undo → original order restored
3. Update property → undo → original value; redo → updated
4. Group 3 cues → undo → ungrouped; redo → regrouped same ID
5. Ungroup → undo → group restored; redo → ungrouped
6. Sequential: add 4, group 2, move, remove child → undo 4 times all reverse
7. `commands.is_saved()` transitions correctly through mutations
8. `commands.clear()` then undo — should be no-op
9. `commands.is_saved()` after `commands.clear()` — session marked as saved
10. Undo immediately after `session.load` — should be no-op (stack was cleared)

---

## Phase 3 — Action Cue Coverage

### Suite 6: `test_collection_cue_e2e.py` — CollectionCue Dispatch
**Tests:** `lisp/plugins/action_cues/collection_cue.py`
**Harness methods:** `cue.add_from_uri`, `cue.add`, `cue.update`, `cue.execute`, `cue.state`, `cue.remove`, `session.save`, `session.load`, `signals.subscribe`/`wait_for` on per-cue `started`/`stopped`

**Scenarios:**
1. CollectionCue with 2 targets + Start → both start
2. Target with Stop action while playing → target stops
3. Target with Resume on paused cue → cue resumes
4. Deleted target ID → remaining targets still execute
5. Save/load round-trip preserves targets list
6. CollectionCue inside a GroupCue (parallel) fires all targets
7. Target with FadeOutStop action — async fade outlives CollectionCue execution
8. CollectionCue targeting itself — silently skipped (guard: `if cue is not self`)

### Suite 7: `test_index_action_cue_e2e.py` — IndexActionCue
**Tests:** `lisp/plugins/action_cues/index_action_cue.py`
**Harness methods:** `cue.add_from_uri`, `cue.add`, `cue.update`, `cue.execute`, `cue.state`, `cue.list`, `layout.move_cue`, `session.save`, `session.load`

**Scenarios:**
1. `relative=True, target_index=1` stops the next cue
2. `relative=False, target_index=0` always targets first cue
3. After moving the IndexActionCue, relative still targets correct neighbor
4. Target index beyond list length → no crash
5. Save/load preserves `target_index` and `relative`
6. `relative=True, target_index=-1` — targets the cue before
7. `relative=True, target_index=0` — targets itself, guard prevents execution

### Suite 8: `test_seek_cue_e2e.py` — SeekCue
**Tests:** `lisp/plugins/action_cues/seek_cue.py`
**Harness methods:** `cue.add_from_uri`, `cue.add`, `cue.update`, `cue.execute`, `cue.state`, `cue.seek`, `cue.get_property`

**Scenarios:**
1. Seek while target is playing → current_time near target (within ~500ms)
2. Seek while paused → after resume, plays from seeked position
3. Seek to 0 → rewinds to start
4. Seek beyond duration → no crash
5. Save/load preserves `target_id` and `time`

### Suite 9: `test_volume_control_e2e.py` — VolumeControl Cue
**Tests:** `lisp/plugins/action_cues/volume_control.py`
**Harness methods:** `cue.add_from_uri`, `cue.add`, `cue.execute`, `cue.state`, `cue.set_property`, `cue.get_property`, `signals.subscribe`/`wait_for`

**Scenarios:**
1. Instant volume jump (`duration=0`) — cue executes and ends immediately
2. Fade-up while target is playing — cue enters Running, then ends after duration
3. Fade-down while target is playing — same lifecycle
4. Interrupt mid-fade — fade stops, cue reaches Stop
5. Target is not running — VolumeControl still executes (sets volume for next start)
6. Save/load preserves `target_id`, `volume`, `duration`, `fade_type`

### Suite 10: `test_command_cue_e2e.py` — CommandCue
**Tests:** `lisp/plugins/action_cues/command_cue.py`
**Harness methods:** `cue.add`, `cue.execute`, `cue.state`, `cue.set_property`, `signals.subscribe`/`wait_for`

**Scenarios:**
1. Successful command (`echo hello`) → cue starts, ends, state=Stop
2. Failing command (`false`) with `no_error=False` → state=Error
3. Failing command with `no_error=True` → state=Stop (no error)
4. Stop/interrupt mid-execution — subprocess terminated
5. Long-running command (`sleep 10`) → state=Running; stop → state=Stop

---

## Phase 4 — Global Controls and Model Signals

### Suite 11: `test_global_controls_e2e.py` — StopAll / Pause / Resume / Interrupt
**Tests:** `lisp/plugins/action_cues/stop_all.py`, `lisp/plugins/list_layout/layout.py` — `stop_all()`, `pause_all()`, `resume_all()`, `interrupt_all()`, `execute_all()`
**Harness methods:** `cue.add_from_uri`, `cue.add`, `cue.execute`, `cue.state`, `layout.stop_all`, `layout.pause_all`, `layout.resume_all`, `layout.interrupt_all`, `layout.execute_all`, `signals.subscribe`/`wait_for` on per-cue `stopped`/`paused`

**Scenarios:**
1. `stop_all` with multiple running cues → all reach Stop
2. `pause_all` → all running cues reach Pause
3. `resume_all` after pause_all → all return to Running
4. `interrupt_all` → all reach Stop immediately
5. StopAll cue type with FadeOutStop → triggers fades
6. StopAll fires while cue is in PreWait → cue stopped before content runs
7. StopAll with FadeOutPause action → cues fade then pause
8. StopAll with FadeOutInterrupt action → cues fade then interrupt
9. `execute_all` → starts all cues simultaneously
10. Global controls on empty model / all stopped — no crash, no signal spam

### Suite 12: `test_model_signals_e2e.py` — CueModel Signal Fidelity
**Tests:** `lisp/cues/cue_model.py` signals, RunningCueModel rewiring
**Harness methods:** `cue.add`, `cue.add_from_uri`, `cue.remove`, `cue.count`, `cue.execute`, `session.save`, `session.load`, `signals.subscribe`/`poll`/`wait_for` on `cue_model.item_added`, `cue_model.item_removed`, `cue_model.model_reset`, `commands.undo`, `commands.redo`

**Scenarios:**
1. `cue.add` → `item_added` fires with correct cue ID
2. `cue.remove` → `item_removed` fires with correct cue ID
3. Bulk add (4 files) → 4 `item_added` events in order
4. `session.load` → `model_reset` then `item_added` per restored cue
5. After reload, starting a cue emits `started` (RunningCueModel rewired)
6. Group command undo/redo: no duplicate `item_added` events
7. `session.new` → `model_reset` fires (distinct from `session.load` path)

---

## Phase 5 — Additional Feature Coverage

### Suite 13: `test_exclusive_mode_e2e.py` — Exclusive Cue Interaction
**Tests:** `lisp/core/exclusive_manager.py`, exclusive flag on cues
**Harness methods:** `cue.add_from_uri`, `cue.execute`, `cue.state`, `cue.set_property`

**Scenarios:**
1. Exclusive cue blocks non-exclusive cue from starting
2. Non-exclusive cue running, exclusive cue starts → non-exclusive stopped
3. Two exclusive cues — second blocks first
4. Exclusive cue in PostWait state blocks another cue (PostWait is IsRunning)
5. Exclusive flag toggled off while running — subsequent cues no longer blocked
6. Group with exclusive flag — children inherit blocking behavior

### Suite 14: `test_cart_layout_e2e.py` — Cart Layout Basics
**Tests:** `lisp/plugins/cart_layout/layout.py`, `lisp/plugins/cart_layout/model.py`
**Harness methods:** `session.new`, `cue.add_from_uri`, `cue.execute`, `cue.state`, `session.save`, `session.load`, `cue.list`

**Note:** Requires starting LiSP with CartLayout. The session file should specify `"layout_type": "CartLayout"`.

**Scenarios:**
1. Add cues to cart layout — cues appear in grid
2. Execute a cue by ID — cue starts and stops
3. Session save/load round-trip preserves cue placement
4. Page navigation (if supported via harness)
5. `session.new` with layout switch from ListLayout to CartLayout

---

## Cross-Cutting Test Scenarios

These scenarios span multiple features and should be added as bonus tests within the most relevant suite, or as a dedicated `test_cross_cutting_e2e.py`:

1. **Rapid start-stop-start** (Suite 3): Fire start, then stop, then start with near-zero delay. Verify final state is deterministic (Running), not stuck due to `_st_lock` contention.
2. **Signal cleanup after reload** (Suite 12): Subscribe to `cue_model.item_added` before `session.load`. After reload, verify no duplicate signals from stale handlers.
3. **Exclusive + PostWait interaction** (Suite 13): Exclusive cue in PostWait blocks a non-exclusive start. After PostWait ends, the blocked cue should be startable.

---

## Verification

After each phase, run the new suite(s) against a running LiSP instance:
```bash
# Start LiSP with test harness enabled, then:
poetry run python tests/e2e/test_go_standby_e2e.py --no-launch

# Or let the suite auto-launch LiSP:
poetry run python tests/e2e/test_go_standby_e2e.py
```

Also run the existing suites to confirm no regressions:
```bash
poetry run python tests/e2e/test_groups_e2e.py --no-launch
```

And confirm unit tests are unaffected:
```bash
poetry run pytest tests/ --ignore=tests/e2e -q
```
