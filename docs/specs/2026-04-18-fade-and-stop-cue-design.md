# Fade & Stop Cue

> **Part 1 of 3 in the SCS-style pause/resume workflow.** This spec delivers a
> single-target, SFR-style Stop/Pause/Interrupt cue with its own fade duration.
> A symmetric "Fade & Resume" cue and a hibernating state (active-cues panel
> filtering) are intentionally deferred to follow-up specs.

## Context

LiSP has two existing cues that partially overlap with the SCS "SFR" (Stop /
Fade / Release) concept:

- `StopAll` stops **every** cue with a configurable `CueAction` (Stop,
  FadeOutStop, Pause, FadeOutPause, Interrupt, FadeOutInterrupt), but has no
  target selection — it's all-or-nothing.
- `VolumeControl` targets **one** cue and fades its `live_volume`, but only
  fades — it never halts playback. It's also hardcoded to `MediaCue` + the
  `Volume` element, with no path to `VideoAlpha`.

The `CueAction.FadeOut*` variants *do* fade-then-halt a single cue, but they
read fade duration and curve from the **target's** own `fadeout_duration` /
`fadeout_type`. There's no way to say "fade this cue over *my* duration, then
stop it." That limitation is what SCS's SFR subcues solve by carrying their
own fade time.

The primary use case is mid-show scene transitions on GroupCues containing
mixed media (audio + video + image). The Fade & Stop cue needs to fade
**both** `live_volume` and `live_alpha` uniformly across the target's
descendants.

## Design Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Extend existing cue or add new? | New `StopCue` | VolumeControl is `MediaCue`+Volume-only; extending it can't reach `VideoAlpha`. StopAll's all-targets semantic can't be cleanly overloaded with a single-target mode. |
| Fade duration source | SFR cue's own `duration` + `fade_type` | Matches SCS muscle memory; enables multiple SFRs targeting the same cue with different fade times. |
| Target cardinality | Single target | Groups already cascade — if the user needs to fade a scene, they point SFR at the scene's `GroupCue`. |
| Actions exposed | `Stop`, `Pause`, `Interrupt` | Three semantic verbs. "Fade" is encoded by `duration > 0`, not a separate action. |
| Fade implementation | Drive `live_volume` + `live_alpha` faders on the affected set, then call plain (non-fading) `Stop`/`Pause`/`Interrupt` | Bypasses target's own `fadeout_duration`, letting SFR own the timing. Uniform for audio + video via the shared `get_fader()` API. |
| Group cascade | Delegated to GroupCue's existing `__stop__`/`__pause__`/`__interrupt__` | Fade is SFR's job; cascade is the group's job. Clean separation. |
| Display name | "Fade & Stop" | Descriptive; fits LiSP naming (`Stop-All`, `Volume Control`). Internal class `StopCue`. |

## Architecture

### New cue: `StopCue`

**New file:** `lisp/plugins/action_cues/stop_cue.py`

Structurally mirrors `volume_control.py` (picked up automatically by
`ActionCues`' `load_classes` loop).

```python
class StopCue(Cue):
    Name = QT_TRANSLATE_NOOP("CueName", "Fade & Stop")
    Category = QT_TRANSLATE_NOOP("CueCategory", "Action cues")

    target_id = Property()
    action = Property(default=CueAction.Stop.value)  # Stop | Pause | Interrupt
    fade_type = Property(default=FadeOutType.Linear.name)
    icon = Property("action-stop")

    CueActions = (
        CueAction.Default,
        CueAction.Start,
        CueAction.Stop,
        CueAction.Interrupt,
    )
```

`duration` (fade length in ms) is inherited from `Cue`.

#### `__start__(fade=False)`

1. Resolve target from `target_id` via `self.app.cue_model.get()`. Missing →
   log + `_error()` + return `False`.
2. Build the **affected set**:
   - If target is a `GroupCue`: recursively flatten via `_resolve_children()`
     (handles nested groups).
   - Else: `[target]`.
3. Filter affected set to cues currently in `CueState.IsRunning`. Non-running
   cues are skipped in the fader phase (step 4) but still receive the action
   in step 5 via the group cascade — which itself filters by running state
   (see `group_cue.py:453-459`).
4. For each affected cue, collect faders:
   - If it's a `MediaCue`: inspect `cue.media.element("Volume")` → if present,
     `get_fader("live_volume")`.
   - And: `cue.media.element("VideoAlpha")` → if present,
     `get_fader("live_alpha")`.
   - A single cue may contribute both (e.g. a video with audio).
5. If `duration > 0` **and** the fader list is non-empty: run all faders
   concurrently to target value `0.0` over `duration / 1000` seconds using
   `FadeOutType[self.fade_type]`. Block until all complete (via the same
   `@async_function` pattern `VolumeControl.__fade` uses, coordinating
   completion across faders).
6. Call `target.execute(CueAction(self.action))` — plain `Stop`/`Pause`/
   `Interrupt`, **not** the `FadeOut*` variants. For a `GroupCue` target this
   re-enters `GroupCue.__stop__/__pause__/__interrupt__` which cascades to
   running children; their `live_volume`/`live_alpha` are already at 0, so the
   cascade is silent/invisible.

#### `__stop__(fade=False)` / `__interrupt__(fade=False)`

Aborts all in-flight faders (`fader.stop()` on each). Does **not** touch the
target's playback state — cancelling the Fade & Stop means "I changed my
mind about fading," not "bring the audio back."

#### Edge cases

- **Target deleted between save and execution:** `cue_model.get()` returns
  `None`; log and `_error()`.
- **Non-Media target with no faders** (e.g. a `CommandCue`): fader list is
  empty, step 5 is skipped, step 6 fires the action. Fade & Stop becomes a
  delayed stop. Acceptable and consistent.
- **Two Fade & Stop cues targeting the same cue concurrently:**
  `get_fader("live_volume")` returns distinct instances, but they write to
  the same live property — last-writer-wins per tick. Not worse than two
  VolumeControls competing. Code comment; not worth solving in this spec.
- **Target restarted after a Fade & Stop:** `live_volume` / `live_alpha`
  reset to configured values on the next `__start__` (standard LiSP
  behaviour), so subsequent playback isn't silent/invisible.

### Settings page: `StopCueSettings`

In the same file. Mirrors `VolumeSettings` structurally so the UI is familiar.

**Registration:** `CueSettingsRegistry().add(StopCueSettings, StopCue)` at
module bottom.

**Three groups:**

1. **Cue group** — `CueSelectDialog` picker. Filter = **all cues** (not just
   `MediaCue`), since `GroupCue` targets are first-class here. Shows selected
   cue's name in a label; "Click to select" button re-opens the picker.
2. **Action group** — `QComboBox` populated with `Stop`, `Pause`, `Interrupt`
   (translated via `translate("CueAction", action.name)`). Stores
   `CueAction.<name>.value` in settings.
3. **Fade group** — `FadeEdit` widget (the same one VolumeControl uses).
   Produces `duration` (ms) and `fade_type` (curve name).

**Stored settings keys:** `target_id`, `action`, `duration`, `fade_type`.

### No core changes

`Cue`, `MediaCue`, `GroupCue`, `CueAction`, and the fader infrastructure all
stay as-is. The feature composes existing pieces.

## Testing

### Unit tests

**New file:** `tests/plugins/action_cues/test_stop_cue.py`

Coverage:

- Default property values on a fresh `StopCue`: `action == Stop.value`,
  `duration == 0`, `fade_type == "Linear"`.
- `target_id` resolution: valid id → cue; missing id → `_error()` fires and
  `__start__` returns `False`.
- Affected-set assembly:
  - Plain `MediaCue` target → `[target]`.
  - `GroupCue` target with 3 media children → all 3 in affected set.
  - Nested group → flattened recursively.
- Fader collection:
  - `MediaCue` with Volume only → one `live_volume` fader.
  - `MediaCue` with Volume + VideoAlpha → two faders.
  - Non-Media cue (e.g. a mock with no `media`) → empty fader list.
- Action dispatch:
  - `action=Stop` → target receives plain `CueAction.Stop` (asserted via mock
    or signal spy on `target.stopped`), **not** `FadeOutStop`.
  - Same for `Pause` and `Interrupt`.
- `__stop__` on the Fade & Stop cue mid-fade: all in-flight faders are
  stopped; target's state is unchanged.
- Non-running members of the affected set are skipped in the fader phase.

Tests use the `mock_app` fixture from `tests/conftest.py`; never instantiate
the real `Application` singleton.

### E2E test via `test_harness`

**New file:** `tests/e2e/test_fade_and_stop.py` (standalone script, not
pytest — matches project E2E conventions).

One scenario:

1. `cue.add_from_uri` with a bundled test audio file → capture MediaCue id.
2. `cue.add` with `type=StopCue`, `properties={target_id, action=Pause,
   duration=500, fade_type=Linear}`.
3. `cue.execute` the MediaCue; `signals.wait_for` its `started`.
4. `cue.execute` the StopCue.
5. Subscribe to the MediaCue's `paused` signal; `signals.wait_for` with
   `timeout=2.0`.
6. Assert: `cue.get_property` reports MediaCue in a paused state and
   `live_volume == 0` after the fade completes.

## Review & QA

After the implementation passes unit tests and the E2E scenario, run two
independent review passes as part of the sign-off checklist:

1. **QA review** via the `voltagent-qa-sec:qa-expert` subagent. Input: the
   spec, the implementation diff, and the test files. Scope: test-plan
   completeness (edge cases, state transitions, group/nested-group coverage),
   verification that the manual intermission workflow works end-to-end, and
   identification of missing scenarios not yet asserted.
2. **Code review** via the `voltagent-qa-sec:code-reviewer` subagent. Input:
   the implementation diff and this spec. Scope: correctness against spec,
   LiSP conventions (signal/fader/property patterns from `volume_control.py`
   and `group_cue.py`), thread safety around Qt/fader interaction, and
   resource cleanup (fader disposal on abort).

Both passes must return with only low-confidence or acknowledged findings
before the PR is considered ready. High-confidence issues from either
subagent block merge until resolved.

## Out of scope (tracked for follow-up)

These are explicitly **not** in this spec and will be addressed in separate
brainstorming sessions:

1. **Fade & Resume cue** — symmetric counterpart that fades `live_volume` /
   `live_alpha` from 0 back up while calling `Resume`, so the SFR cue owns
   both ends of the intermission fade.
2. **Hibernating state** — a `CueState` (or flag) meaning "user-paused,
   hide from active-cues view until resumed." Needs core state machinery
   changes plus audit of every view/plugin that introspects `CueState`
   (active-cues panel, MIDI/OSC status reporting, test_harness `cue.list`).
