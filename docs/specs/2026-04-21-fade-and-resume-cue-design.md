# Fade & Resume Cue

> **Part 2 of 3 in the SCS-style pause/resume workflow.** This spec delivers
> the symmetric counterpart to [Fade & Stop](2026-04-18-fade-and-stop-cue-design.md):
> a single-target cue that owns its own fade-in duration and dispatches
> `Resume`. Part 3 — hibernating state & active-cues panel filtering — is
> still deferred to a follow-up spec. Parts 1 and 2 together deliver the
> end-to-end intermission workflow; Part 3 only adds operator-view polish.

## Context

Part 1 added `StopCue` (Fade & Stop): a single-target cue that runs its own
`live_volume` + `live_alpha` faders, then dispatches plain `Stop`/`Pause`/
`Interrupt`. Part 2 is its symmetric partner: after the intermission, the
operator needs to bring the pre-show playlist back up from silence and
resume it.

LiSP already has `CueAction.FadeInResume`, which reads the fade-in curve +
duration from the **target's** `fadein_type` / `fadein_duration` properties.
That has the exact limitation that `CueAction.FadeOutStop` had for Part 1:
the target owns the fade timing, so you can't say "fade this cue up over
*my* duration, then resume it." The SCS "SFR" workflow depends on the
paired Resume cue owning its own fade-in time (which frequently differs
from the corresponding fade-out time — e.g. a 5s duck-out but a 10s fade
back in).

The primary use case is the same intermission workflow motivating Part 1:
a pre-show `GroupCue` (typically a playlist of background music + optional
video) is paused with Fade & Stop at "house open → show start", and
resumed with Fade & Resume at "house reopen → act two start". The cue
needs to fade both `live_volume` and `live_alpha` uniformly across the
target's descendants.

## Design Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Separate cue type or mode flag on `StopCue`? | New `ResumeCue` class | Single-responsibility naming; action dropdown diverges (StopCue has three verbs, ResumeCue has one); settings UI diverges. Matches LiSP's single-purpose cue convention (`VolumeControl`). |
| Fade duration source | ResumeCue's own `duration` + `fade_type` | Mirrors Part 1 exactly. Pre-show fade-in commonly differs from post-show fade-out. Avoids brittle cross-cue references. |
| Target cardinality | Single target | GroupCue cascade handles multi-cue scenes, same as Part 1. |
| Action | Fixed `Resume` | Only one verb makes sense — "fade" is encoded by `duration > 0`. |
| Target-state policy | Paused → happy path; Running → fade-up fallback; Stopped/Error → `_error()`; Pre/PostWait → fade-up fallback | Useful graceful behaviour when the operator hits Fade & Resume on a cue that's not perfectly in the expected state. |
| Pre-Resume zero step | Zero `live_volume`/`live_alpha` before dispatching Resume (Paused path, only when fading) | Guarantees no pop regardless of how the target was paused — makes Fade & Resume self-contained, not dependent on a prior Fade & Stop having left faders at 0. |
| Zero-when-no-fade | Skip the zero step when `duration == 0` | Otherwise we'd zero faders and never fade back up → silent cue. |
| Code organisation | Extract `_fader_coordinator.py` helper module; both StopCue and ResumeCue build on it | Removes provably-shared logic (affected-set flattening, fader collection, parallel-fader runner with abort). Avoids inheritance (semantics of stop vs resume diverge enough that a base class would obscure more than it shares). |
| Part 1 plan timing | **B-now** — update the Part 1 plan in-place to use the helper from the first commit | Part 1 is specced but not implemented; retrofitting the plan avoids a throwaway intermediate implementation. |
| Display name | "Fade & Resume" | Symmetric with "Fade & Stop". Internal class `ResumeCue`. |

## Architecture

### New helper module: `lisp/plugins/action_cues/_fader_coordinator.py`

Leading underscore so `load_classes` skips it during cue auto-registration.

```python
def build_affected_set(target: Cue) -> list[Cue]:
    """Flatten a target cue. GroupCues recurse; other cues are the set."""

def collect_live_faders(
    cues: list[Cue],
    states: CueState = CueState.IsRunning,
) -> list[Fader]:
    """For each cue matching `states`, collect live_volume and live_alpha
    faders from its Volume/VideoAlpha elements (if any)."""

class ParallelFadeRunner:
    """Run a set of Faders concurrently to a target value over a duration.

    Supports cooperative abort via `abort()`. `run_until_complete()` blocks
    until all faders finish or abort is called; returns True on completion,
    False on abort.
    """
    def __init__(self, faders, to_value, curve, duration_seconds):
        ...
    def run_until_complete(self) -> bool:
        ...
    def abort(self) -> None:
        ...
```

Tests live in `tests/plugins/action_cues/test_fader_coordinator.py`.

### New cue: `ResumeCue`

**New file:** `lisp/plugins/action_cues/resume_cue.py`

Picked up by `ActionCues`' `load_classes` loop.

```python
class ResumeCue(Cue):
    Name = QT_TRANSLATE_NOOP("CueName", "Fade & Resume")
    Category = QT_TRANSLATE_NOOP("CueCategory", "Action cues")

    target_id = Property()
    fade_type = Property(default=FadeInType.Linear.name)
    icon = Property("action-resume")  # fallback to a stock icon if missing

    CueActions = (
        CueAction.Default,
        CueAction.Start,
        CueAction.Stop,
        CueAction.Interrupt,
    )
```

`duration` (ms) is inherited from `Cue`. No `action` property — the verb is
fixed to `Resume`.

#### `__start__(fade=False)`

1. Resolve target via `self.app.cue_model.get(self.target_id)`. Missing →
   log + `_error()` + return `False`.
2. Read `target.state`. Branch:
   - `state & CueState.Pause` → `_paused_path(target)`.
   - `state & CueState.IsRunning` → `_running_fallback(target)`.
   - else (Stopped / Error) → log + `_error()` + return `False`.

#### `_paused_path(target)`

1. `affected = build_affected_set(target)`.
2. `faders = collect_live_faders(affected, states=CueState.Pause | CueState.IsRunning)`.
3. `will_fade = self.duration > 0 and faders`.
4. If `will_fade`: for each fader, set its live property to `0.0` immediately
   (synchronous — use the fader's target's property setter, not a fade).
5. `target.execute(CueAction.Resume)`. For a GroupCue target this cascades
   via the base-class `resume()` → `start()` → `GroupCue.__start__` chain,
   which already detects paused children and dispatches Resume to each
   (both parallel and playlist modes).
6. If `will_fade`: build `ParallelFadeRunner(faders, to_value=1.0,
   curve=FadeInType[self.fade_type], duration_seconds=self.duration/1000)`,
   store on `self._runner`, and (via an `@async_function` coordinator) call
   `run_until_complete()`. On completion or abort, clear `self._runner` and
   call `self._ended()`. Return `True` (async execution).
7. If not `will_fade`: return `False` (instant execution).

#### `_running_fallback(target)`

1. `affected = build_affected_set(target)`.
2. `faders = collect_live_faders(affected, states=CueState.IsRunning)`.
3. `will_fade = self.duration > 0 and faders`.
4. No Resume dispatch (target is already running).
5. If `will_fade`: run `ParallelFadeRunner` same as step 6 above. Return
   `True`.
6. Else: return `False` (no-op — target was running, nothing to do).

#### `__stop__(fade=False)` / `__interrupt__(fade=False)`

If `self._runner` is set, call `self._runner.abort()`. Does **not** re-pause
the target — "I changed my mind about fading in" does not mean "put the
target back where it was". Same semantics as Part 1.

#### Edge cases

- **Target deleted between save and execution:** `cue_model.get()` returns
  `None`; log and `_error()`.
- **Non-Media target with no faders** (e.g. a paused Command cue): fader
  list is empty, `will_fade` is `False`, Resume is dispatched, no fade.
  "Delayed resume" — acceptable and consistent with Part 1's "delayed stop".
- **Two ResumeCues targeting the same cue concurrently:** last-writer-wins
  per tick. Documented, not solved — same as two VolumeControls.
- **User Stops the ResumeCue mid-fade:** faders abort; target stays at
  partial volume. Documented caveat — "partial state" is acceptable because
  the user explicitly cancelled, and rolling back Resume would be worse.
- **Target restarted after a ResumeCue:** `live_volume` / `live_alpha` reset
  to configured defaults on the next `__start__` (standard LiSP behaviour).
- **Target in mid-fade from a still-running Fade & Stop:** last-writer-wins.
  If the ResumeCue's fade starts after the Fade & Stop's fade finishes,
  Resume behaviour is the normal happy path. If they overlap, whichever
  writes `live_volume` last on a given tick wins.
- **Mixed-state GroupCue target** (some children paused, some stopped):
  paused children fade in cleanly; stopped children are restarted fresh by
  `GroupCue.__start__` and snap in at their configured volume without fade.
  Best-effort — mixed-state groups are outside the happy path.
- **Target in Pre/PostWait:** treated as Running → fade-up fallback, no
  Resume dispatched.
- **Target in Error state:** neither Pause nor IsRunning → `_error()`.
- **`duration == 0` on Paused target:** skip the zero step entirely,
  dispatch Resume, no fade. (If we zeroed without fading back, the cue
  would resume silent.)

### Part 1 refactor

Update `lisp/plugins/action_cues/stop_cue.py` (not yet implemented) to use
the helper module:

- `_build_affected_set` → `build_affected_set` (imported).
- `_collect_faders` → `collect_live_faders(cues)` with default
  `states=CueState.IsRunning`.
- Parallel fader coordinator → `ParallelFadeRunner`.

The Part 1 implementation plan (`plans/07-fade-and-stop-cue.md`) needs
corresponding task-level edits: the scaffolding tasks become
helper-module tasks, and StopCue's implementation tasks reference the
helper. Done as part of Part 2's plan, before ResumeCue work begins.

### Settings page: `ResumeCueSettings`

In the same file as `ResumeCue`. Mirrors `StopCueSettings` structurally,
minus the action dropdown.

**Registration:** `CueSettingsRegistry().add(ResumeCueSettings, ResumeCue)`
at module bottom.

**Two groups:**

1. **Cue group** — `CueSelectDialog` picker. Filter = **all cues**
   (GroupCue targets are first-class; Command cues allowed per the
   non-Media graceful degradation path). Shows selected cue's name in a
   label; "Click to select" button re-opens the picker.
2. **Fade group** — `FadeEdit(self.fadeGroup, mode=FadeComboBox.Mode.FadeIn)`.
   `FadeEdit` already supports fade-in mode (see
   `lisp/ui/widgets/fades.py:75`), which swaps the combo-box icons to the
   fade-in variants. Produces `duration` (ms) and `fade_type` (curve name,
   stored as `FadeInType.<name>.name`).

**Stored settings keys:** `target_id`, `duration`, `fade_type`.

**SortOrder:** match `StopCueSettings` so both Fade cues sort together in
the settings dialog.

### No core changes

`Cue`, `MediaCue`, `GroupCue`, `CueAction`, `Fader`, and the GStreamer
elements all stay as-is. The feature composes existing pieces via the new
helper module.

## Testing

### Unit tests

**New file:** `tests/plugins/action_cues/test_resume_cue.py`

Coverage:

- Default property values: `fade_type == FadeInType.Linear.name`,
  `duration == 0`, `target_id is None`.
- Target resolution: valid id → cue; missing id → `_error()` fires and
  `__start__` returns `False`.
- State branching:
  - Paused MediaCue + `duration > 0` + faders → zero step fires, Resume
    dispatched, fade runs.
  - Paused MediaCue + `duration == 0` → zero step **skipped**, Resume
    dispatched, no fade.
  - Paused MediaCue + no faders (mock without `media`) → Resume
    dispatched, no zero, no fade.
  - Running MediaCue → no Resume dispatched, fade-up from current → 1.0.
  - Stopped target → `_error()`, no dispatch.
  - Target in `PreWait` → treated as Running (fade-up path, no Resume).
- Group cascade: Paused GroupCue target with 3 paused media children →
  zero + fade applied to all 3 faders; `target.execute` called once with
  `CueAction.Resume`, not once per child.
- Mid-fade abort: `__stop__` on ResumeCue while fade in-flight → runner
  aborted, target not rolled back.
- Mixed-state group: 2 paused + 1 stopped child → faders collected from
  the 2 paused only, stopped child is not zeroed.

**New file:** `tests/plugins/action_cues/test_fader_coordinator.py`

Coverage:

- `build_affected_set` on plain cue, single group, nested group (3-deep).
- `collect_live_faders` with default `states` (IsRunning only) and with
  `states=Pause|IsRunning`.
- `collect_live_faders` handles cue with only Volume, only VideoAlpha,
  both, neither.
- `ParallelFadeRunner.run_until_complete()` → `True` when all faders
  finish.
- `ParallelFadeRunner.abort()` mid-run → `run_until_complete()` returns
  `False`; all fader `stop()` methods called.

**Updates:** `tests/plugins/action_cues/test_stop_cue.py` shrinks — the
shared affected-set / fader-collection / coordinator tests move to
`test_fader_coordinator.py`. StopCue tests retain only StopCue-specific
assertions (action dispatch, `duration > 0` fade path, abort semantics
for Stop/Pause/Interrupt verbs).

All tests use `mock_app` from `tests/conftest.py`; never instantiate the
real `Application` singleton.

### E2E test

**New file:** `tests/e2e/test_fade_and_resume.py` — standalone script,
matches the Part 1 E2E style.

End-to-end intermission workflow in one scenario:

1. `cue.add_from_uri` bundled test audio → capture MediaCue id.
2. `cue.add` a `StopCue` with `target_id=media, action=Pause, duration=300,
   fade_type=Linear`.
3. `cue.add` a `ResumeCue` with `target_id=media, duration=500,
   fade_type=Linear`.
4. `cue.execute` the media cue; `signals.wait_for` its `started`.
5. `cue.execute` the StopCue; `signals.wait_for` MediaCue `paused`;
   assert `live_volume == 0` and state includes `Pause`.
6. `cue.execute` the ResumeCue.
7. `signals.wait_for` MediaCue `started` (Resume re-enters the start
   pipeline via the base class).
8. Poll `cue.get_property` for `live_volume` at 0s, 250ms, 500ms + 50ms
   buffer; assert monotonically rising from 0 → 1.0.

This single scenario validates the **full intermission workflow** — the
user-facing "why we built this" story.

## Review & QA

After the implementation passes unit tests and the E2E scenario, run two
independent review passes as part of the sign-off checklist:

1. **QA review** via the `voltagent-qa-sec:qa-expert` subagent. Input:
   this spec, the Part 1 spec (for symmetry context), the ResumeCue diff,
   the helper module diff, the refactored Part 1 StopCue diff, and all
   test files. Scope: state-branch coverage (all four of the Target-state
   policy cases tested), mixed-state group coverage, verification that
   the end-to-end intermission workflow works, identification of missing
   scenarios not yet asserted.
2. **Code review** via the `voltagent-qa-sec:code-reviewer` subagent.
   Input: the ResumeCue diff, the helper module diff, the StopCue
   refactor diff, and this spec. Scope: correctness against spec,
   symmetry with StopCue (no gratuitous divergence), fader disposal on
   abort, the zero-step ordering (zeroed before Resume dispatch, not
   after), thread safety around Qt/fader interaction, and LiSP
   conventions (signal / fader / property patterns).

Both passes must return only low-confidence or acknowledged findings
before the PR is considered ready. High-confidence issues from either
subagent block merge until resolved.

## Out of scope (tracked for follow-up)

Part 3 — **hibernating state & active-cues panel filtering**. After Parts
1 and 2 ship, a paused cue is still visible in the active-cues panel. Part
3 adds a way to mark a cue as "hibernating" (user-paused with
intent-to-resume) and filter it out of the operator's active-cues view.
This requires core `CueState` changes plus an audit of every view/plugin
that introspects `CueState` (active-cues panel, MIDI/OSC status
reporting, `test_harness` `cue.list`, serialization). See the roadmap
([`2026-04-18-sfr-workflow-roadmap.md`](2026-04-18-sfr-workflow-roadmap.md))
for open brainstorming questions.

Parts 1 and 2 together deliver a fully functional intermission workflow;
Part 3 is operator-view polish.
