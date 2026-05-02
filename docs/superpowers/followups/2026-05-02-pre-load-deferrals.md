# Pre-load (pre-arm) — deferred follow-ups

Tracked items from the QA + code review at the end of `feat/pre-load`
(2026-05-02). None are blockers; the feature is shipped and all
Critical/High user-facing issues are fixed. These are the honest tech
debt the team should track.

## High — real but not user-blocking

### GstMedia `prearm()` ASYNC state-change branch is untested

`lisp/plugins/gst_backend/gst_media.py:196` checks
`get_state(Gst.SECOND)` and returns `False` for any non-`SUCCESS`
result. In practice, GStreamer often returns `ASYNC` for network
URIs or slow decoders. Test fixtures use a local WAV that always
succeeds synchronously. The `ASYNC → disarm → False` branch has no
coverage in the GstMedia layer.

**When it'll bite:** the moment we add network-URI input, an HTTP
streaming source, or a slow decoder (FLAC + large files).

**Fix:** add a unit test that uses a Mock pipeline returning
`Gst.StateChangeReturn.ASYNC`, asserts `prearm` returns `False`,
and asserts the pipeline is set back to `NULL`.

### `standby_changed` re-entrancy is not tested

`lisp/cues/pre_arm_manager.py:413` snapshots
`auto_armed_ids = list(self._armed.items())` then iterates calling
`_remove_reason`, which emits `armed_set_changed`. If any subscriber
synchronously calls back into the manager, behaviour is undefined.

Existing `test_standby_changed_*` tests use `MagicMock` signals that
do not re-emit, so the re-entrant pattern is not exercised.

**Fix:** add a test where an `armed_set_changed` listener calls
`manager.standby_changed(other_cue)` synchronously; verify the
manager doesn't deadlock or corrupt state.

## Medium — test coverage and code organisation

### E2E `test_t20_live_preload_toggle` uses `time.sleep(1.0)`

`tests/e2e/test_pre_arm_e2e.py` T20a uses a 1-second sleep before
calling `pre_arm.status`. T20b and T20c use `pre_arm.wait_for_armed`
correctly. T20a should match — the harness exposes the wait method
specifically so we don't have to time-tune sleeps.

### Indicator dot state-cycle test is missing

`tests/plugins/list_layout/test_indicator_dot.py` covers static
states (armed-only, failed-only, non-preload-failed, no-manager). No
test exercises the full cycle: armed → played → re-armed → played →
stopped. The `armed_set_changed` repaint hook is verified, but the
dot's *visual* state across multiple emits is only inferred.

### Batch-coalescing toast content format not asserted

`test_pre_arm_manager.py` checks the **count** of failures and **call
count** of the notify path, but not the exact wording. Spec says:

- Single failure: `Failed to preload "{cue_name}": {category}`
- Multiple: `Failed to preload {N} cues — see log for details`

Add assertions on the message strings.

### GroupCue detection is string-based

`pre_arm_manager.py:198`: `if type(cue).__name__ == "GroupCue":
return False`. A subclass of `GroupCue` (none today, but possible in
plugins) would not be detected. Use `isinstance(cue, GroupCue)`
instead — at the cost of importing `GroupCue` from
`lisp.plugins.action_cues.group_cue`, which crosses a layering
boundary the current code is avoiding. Decide which trade-off
matters more.

### `_serialize_arm_reason` placement

Lives as a nested function inside
`lisp/plugins/test_harness/handlers.py::register_all`. Cannot be
unit-tested directly — only through full RPC dispatch. Promote to a
module-level function on `pre_arm_manager.py` (next to `ArmReason`)
so it can be tested in isolation and reused if a future RPC needs the
same serialization.

### `MediaType` re-imported inside `_eligible` per call

`pre_arm_manager.py:206` does
`from lisp.backend.media_element import MediaType` inside the
function. Hoist to the module top. Pattern was originally for test
isolation, but tests use `spec=` mocks now, so the import-at-top
form is fine.

### `session_loaded` traverses `cue_model` twice

`pre_arm_manager.py` counts `preload_count` (for the log line), then
iterates again to arm. Single pass with `enumerate` or a generator
would do.

## Low — polish

### E2E latency assertion is intentionally loose

`tests/e2e/test_pre_arm_e2e.py::T21` allows up to +15 ms slowdown
because RPC overhead swamps the actual pre-arm saving on a tiny WAV
fixture. The real coverage is in
`tests/plugins/gst_backend/test_gst_media_prearm.py::test_play_from_armed_skips_paused_transition`.

If we add a longer/compressed fixture (MP3 or FLAC with a long seek
table), the E2E threshold could become a real correctness assertion.

### No manual-test checklist for the indicator dot UX

The plan listed "manual UI verification" but no checklist exists for:

- Dot visibility at different row heights / list zoom levels.
- Dot position under horizontal scroll.
- Tooltip rendering on HiDPI screens.
- Colour transitions (green → red on a re-arm that fails).

### `iterAllItems` / `_iter_all_items` duplicate (pre-existing)

`lisp/plugins/list_layout/list_view.py` has two identical generator
methods. Pre-existing — not introduced by this branch. Belongs on
its own master-based commit per the project's "pre-existing bugs get
their own branch" convention.

---

**Ownership:** none assigned. These should be tracked as Issues or a
project-board column rather than living indefinitely in this
markdown.
