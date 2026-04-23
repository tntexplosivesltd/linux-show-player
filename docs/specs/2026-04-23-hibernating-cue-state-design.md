# Hibernating Cue State & Playing-Panel Filtering

Part 3 of the SFR-style workflow roadmap
([`2026-04-18-sfr-workflow-roadmap.md`](2026-04-18-sfr-workflow-roadmap.md)).

## Overview

Introduces "Hibernating" as a first-class runtime cue state: a cue that
has been paused by a `Fade & Stop` cue configured with the new
`Hibernate` action is visually de-emphasised in the Playing panel and
flagged with a dedicated status icon in the main cue list. Any
successful resume (Fade & Resume, spacebar, OSC, MIDI, API) clears the
flag automatically.

The goal is SCS-style intermission workflow: during an interval the
operator's Playing panel stays focused on what is actually audible,
while hibernated cues remain in the panel as small, dimmed rows so
their presence is not lost.

## User-facing behaviour

1. `Fade & Stop`'s action combo gains a third option alongside `Stop`
   and `Pause`: `Hibernate`. Same fade settings apply.
2. When the fade completes, the target is paused and marked
   hibernating.
3. In the Playing panel the target's widget collapses to a compact,
   dimmed row — dbmeter, seek slider, and control buttons hidden. The
   cue stays in its existing position in the list.
4. In the main cue list the target's status icon changes to a
   hibernating variant (cool blue, distinct from pause's orange).
5. Any successful start or resume on the target clears the
   hibernation flag — no matter the source. The widget and status
   icon return to normal.
6. Stopping or interrupting the target also clears the flag, as does
   an error transition.
7. The flag is runtime-only: closing the session drops it.

## Architecture

### State representation

`CueState` in [`lisp/cues/cue.py`](../../lisp/cues/cue.py) is an
integer bitflag, not an enum. A hibernated cue's state is
`CueState.Pause | CueState.Hibernating`:

```python
class CueState:
    Invalid = 0
    Error   = 1
    Stop    = 2
    Running = 4
    Pause   = 8
    PreWait        = 16
    PostWait       = 32
    PreWait_Pause  = 64
    PostWait_Pause = 128
    Hibernating    = 256   # NEW

    IsRunning = Running | PreWait | PostWait
    IsPaused  = Pause | PreWait_Pause | PostWait_Pause
    IsStopped = Error | Stop
```

Because the bit composes with `Pause`, every existing
`state & CueState.Pause` call site (list widgets, cart widgets,
MediaCue, the `_fader_coordinator`, the network/OSC API, etc.)
continues to behave identically without change. Only code that wants
to act on hibernation reads `state & CueState.Hibernating`.

### No new `CueAction` enum value

`Hibernate` is a UI-level option inside `StopCueSettings.SupportedActions`,
not an addition to the `CueAction` enum. The target cue never sees a
"Hibernate" action — StopCue dispatches `CueAction.Pause` to the
target and then flips the hibernation bit after the target's
`paused` signal fires. This contains blast radius: only StopCue
needs to know about hibernation. Other cue subclasses are untouched.

If a future OSC/MIDI trigger wants to originate hibernation directly,
a `CueAction.Hibernate` value can be added then and routed through
the same `Cue._set_hibernated(True)` helper.

### Base-class ownership of the bit

`Cue` grows three additions:

- `Cue.hibernated` and `Cue.awoken` signals, created in `__init__`.
- `Cue._set_hibernated(value: bool)` — mutates the bit under
  `_st_lock`, emits `hibernated` / `awoken` outside the lock.
- Pause→Running transitions inside `Cue.start()` and `Cue.resume()`
  clear the bit (single point for all resume paths).
- `Cue.stop()`, `Cue.interrupt()`, and `Cue._error()` also clear the
  bit on their pause-exit paths, emitting `awoken` once so consumers
  have a single signal to subscribe to.

## Components & files touched

### Core — `lisp/cues/cue.py`

- New `CueState.Hibernating = 256` constant.
- New `Cue.hibernated` and `Cue.awoken` signals.
- New `Cue._set_hibernated(value: bool)` method.
- Pause→non-Pause transitions in `start()`, `resume()`, `stop()`,
  `interrupt()`, `_error()` clear the bit.

### StopCue — `lisp/plugins/action_cues/stop_cue.py`

- `SupportedActions` list gains the string `"Hibernate"` (or a small
  sentinel constant on `StopCue`). The dispatch in
  `_run_fade_then_action` branches: when `self.action == "Hibernate"`,
  call `target.execute(CueAction.Pause)` and subscribe to
  `target.paused` with a one-shot wrapper that calls
  `target._set_hibernated(True)` on fire, auto-disconnects on
  completion *or* on runner abort.
- When the target is a `GroupCue`, cascade the bit to children that
  enter Pause as part of the cascade (iterate
  `cue_model.filter_by_group_id(group.id)` and apply the same
  one-shot-subscribe pattern).
- `_derive_name` handles the new verb: `"Fade and Hibernate 'XYZ'"`.

### Playing panel

- `lisp/plugins/list_layout/playing_widgets.py`: running widget gains
  `set_hibernated(hibernated: bool)`. Toggles visibility of dbmeter,
  seek slider, control buttons; applies a compact-dimmed stylesheet;
  calls `updateGeometry()`.
- `lisp/plugins/list_layout/playing_view.py`: `RunningCuesListWidget`
  subscribes per-cue to `hibernated` / `awoken` in `_item_added` (and
  disconnects in `_item_removed`). On signal, updates the widget's
  hibernated state and refreshes the `QListWidgetItem.sizeHint` so
  Qt relays out the row in place.

### Status icon in the main cue list

- `lisp/plugins/list_layout/list_widgets.py` `updateIcon` branches
  on `CueState.Hibernating` **before** `Running`/`Pause`/`Error` — a
  hibernated cue always shows the hibernating icon.
- `lisp/plugins/cart_layout/cue_widget.py` gets the same branch for
  cart-layout parity.

### Icon system — two-stage landing

Stage 1 is cherry-picked from upstream onto master before Part 3
begins — no separate PR in this fork.

**Stage 1 (cherry-pick of upstream
[PR #367](https://github.com/FrancescoCeruti/linux-show-player/pull/367)
onto master):**

- Vendor the recolour machinery into
  `lisp/ui/icons/__init__.py`: a `_CUE_TYPE_VARIATIONS` dict mapping
  suffix → `{fill, stroke, opacity}`, `_strip_cue_suffix` helper, and
  `_load_modified_icon` which mutates the SVG root attributes and
  renders via `QSvgRenderer`.
- Refactor the base SVGs in `lisp/ui/icons/lisp/cues/*.svg` so
  `fill`/`stroke`/`opacity` live on the root element (required for
  the mutation to take effect).
- Delete all `lisp/ui/icons/lisp/cues/variations/*.svg` (~90 files).
- Pure refactor — no behaviour change for end users. Running/pause/
  error/cart variations still render identically.

**Stage 2 (this spec's branch):**

- Add one entry to `_CUE_TYPE_VARIATIONS`:
  ```python
  "-hibernating": {"stroke": "#5AF", "fill": "#5AF", "opacity": "1"},
  ```
  Colour is tunable; cool blue picked to read as "cold / sleeping"
  and to contrast with pause's orange. Running=green, pause=orange,
  hibernating=blue, error=red gives a four-way distinction suitable
  for non-colour-blind operators. Colour-blind UX is already a weak
  point of the existing three-colour scheme, not introduced here.

### Test harness — `lisp/plugins/test_harness/serializers.py`

- Add `CueState.Hibernating: "Hibernating"` to `_STATE_NAMES`.
  Composite serialisation already joins with `|`, so a hibernated
  cue reports `"Pause|Hibernating"`.

### i18n

- New translatable strings: `"Hibernate"` (action label), the
  action-combo tooltip, and the auto-derived cue-name verb. Run
  `python i18n_update.py` to regenerate `.ts` files.

### Unchanged

- `ResumeCue` — already dispatches `CueAction.Resume`, which clears
  the bit via the base-class hook.
- `GroupCue` — no internal changes; cascade is driven from the
  StopCue side.
- Session serialiser — hibernation is runtime-only, not in
  `cue.properties()`.
- `CueFactory`, MIDI/OSC plugins, network API — all read
  `cue.state` as an int; the composite `Pause|Hibernating` value is
  "paused" to them, which is what they already handle.

## Data flow

### Hibernate path

```
User triggers StopCue (action="Hibernate", fade configured)
  → StopCue.__start__
  → ParallelFadeRunner fades target's live_volume / live_alpha to 0
  → runner completes → _run_fade_then_action
  → target.execute(CueAction.Pause)                 (existing)
  → target.__pause__ runs → target emits `paused`
  → StopCue's one-shot `paused` listener fires
  → target._set_hibernated(True)
  → target._state becomes Pause | Hibernating
  → target emits `hibernated`
  → RunningCuesListWidget subscriber → widget.set_hibernated(True)
  → widget collapses + dims; row size hint updated
  → list_widgets/cart cue_widget re-render status icon (blue tint)
```

### Wake path

```
Anything calls target.start() or target.resume()
  → Cue.start() detects Pause→Running transition
  → clears Hibernating bit under _st_lock
  → emits `awoken`
  → (existing) emits `started`
  → RunningCuesListWidget subscriber → widget.set_hibernated(False)
  → widget restores prior dbmeter/seek visibility
  → status icon reverts to running variant
```

### Stop / interrupt / error paths

Same pattern: the base class clears the bit and emits `awoken` once
during the pause-exit transition, then the existing `stopped` /
`interrupted` / `error` signals flow through the usual paths
(widget removal from the panel via `RunningCueModel._remove`).

## Playing-panel widget UX

Hibernated widget state:

- Height reduced to roughly one-third (≈24 px).
- `dbmeter`, `seekSlider`, control buttons hidden.
- Stylesheet applies a muted colour palette and ~0.45 opacity. The
  final technique (stylesheet colour vs. `QGraphicsOpacityEffect`)
  is resolved at plan/implementation time — Qt opacity effects have
  known interactions with stylesheets.
- Only content shown: cue name and the hibernating status glyph
  (compact version, painted inline).

Transition mechanism is a per-widget state toggle, not a widget
swap. `set_hibernated(True/False)` updates visibility and stylesheet,
then the parent list widget updates `QListWidgetItem.sizeHint` so Qt
relays out the affected row in place. The cue's position in the
panel is preserved.

Operator preferences `dbmeter_visible` and `seek_visible` on the
panel are stored separately per widget as `_dbmeter_requested` /
`_seek_requested`, so on wake the widget restores whatever the
operator had set before hibernation — not an unconditional re-show.

## Error handling & edge cases

- **Mid-fade cancellation.** The one-shot `paused` subscription is
  registered before the fade starts and auto-disconnects when
  StopCue's `runner.abort()` is called (existing `__stop__` path).
  Bit is never set if the fade is cancelled.
- **Target already paused when StopCue dispatches Pause.** The
  target's `pause()` is guarded by
  `state & CueState.Running` — the `paused` signal never fires.
  Subscription harmlessly waits, then is cleaned up at the end of
  `_run_fade_then_action`. The current Pause is attributable to
  some other controller, so leaving the cue un-hibernated is
  correct.
- **Target stopped externally during fade.** The `stopped` signal
  fires; our subscription is on `paused` only, so nothing happens.
  Subscription cleaned up on runner exit.
- **Target errors while hibernated.** `Cue._error()` clears the
  Hibernating bit and emits `awoken` before the existing `error`
  signal; widget is removed via the standard error handler.
- **Target deleted while hibernated.** Existing `CueModel`
  deletion cascade disconnects all signals and removes the widget;
  no new code needed.
- **GroupCue cascade.** When the target is a `GroupCue`, StopCue
  iterates the group's children at fade-completion time and applies
  the same one-shot-subscribe pattern to each. Each child
  independently enters `Pause | Hibernating` and independently
  clears on resume via the base-class hook.
- **Multiple StopCues targeting the same cue.** Idempotent — the
  second StopCue's `_set_hibernated(True)` is a no-op if the bit is
  already set (no duplicate `hibernated` signal, by design of the
  helper's internal check).
- **Runtime-only.** Closing or reloading the session drops the
  flag. Confirmed: `cue.state` is not in `cue.properties()`.

## Testing strategy

### Unit tests

- `tests/core/test_cue_state.py` — bit non-overlap; composite
  `Pause | Hibernating` still matches `state & CueState.Pause`.
- `tests/cues/test_cue_hibernation.py` — base-class set/clear
  behaviour, signal emission, idempotence, thread-safety under
  `_st_lock`, clear-on-resume / stop / interrupt / error.
- `tests/plugins/action_cues/test_stop_cue_hibernate.py` — StopCue
  with `action="Hibernate"`, mid-fade abort (no bit set, listener
  cleaned), GroupCue cascade, auto-derived cue name.
- `tests/plugins/list_layout/test_running_panel_hibernation.py` —
  widget state toggling, dbmeter/seek visibility restored to
  operator preference on wake, list item size-hint updated.

### E2E test

- `tests/e2e/test_hibernation_workflow.py` — standalone script,
  launches LiSP, uses `test_harness` over the JSON-RPC socket.
  Full intermission: start media cue → Fade & Stop (Hibernate) →
  assert `cue.state` composite bits via `cue.list` → Fade & Resume
  → assert Hibernating cleared and target back to Running.
  Uses `signals.subscribe` + `signals.wait_for` for deterministic
  waits (no `sleep()`).

### Icon Stage 1 regression

- Parametrised pytest confirming `IconTheme.get(f"{icon}-{state}")`
  returns a non-blank `QIcon` for every base cue icon × every state
  suffix, after the `variations/*.svg` files are deleted. Guards
  against missing recolour mutation paths.

### Manual QA checklist

Appended to `manual_group_tests.md`:

- Session round-trip: hibernate cue, save, reload → cue is Stopped
  (confirms runtime-only).
- OSC/MIDI resume of a hibernated cue clears the flag.
- Multiple StopCues targeting the same cue behave idempotently.
- Cart layout renders the hibernating icon variant.

## Delivery workflow

- Implementation happens in a **git worktree** off master, per the
  `superpowers:using-git-worktrees` pattern — keeps the main working
  tree available while this branch is in flight and avoids polluting
  it with in-progress state.
- Branch layout follows the two-stage plan from the icon section:
  Stage 1 (icon recolour refactor) is cherry-picked from upstream
  [PR #367](https://github.com/FrancescoCeruti/linux-show-player/pull/367)
  directly onto master — no separate review PR needed since the code
  is already upstream-reviewed. Stage 2 (this spec's work) branches
  from the post-cherry-pick master inside the worktree.
- After implementation and passing tests, the branch is reviewed by
  the `voltagent-qa-sec:qa-expert` subagent (test coverage, edge
  cases, E2E completeness) and the `voltagent-qa-sec:code-reviewer`
  subagent (code quality, conventions, bugs) — same review gating
  used for Parts 1 and 2 (see the roadmap's Part 2 checklist).
- Findings from either review are addressed on the same branch
  before merging back to master.

## Out of scope / future work

- Persisting hibernation (and target pause state) across session
  save/load. Would require broader playback-state persistence —
  larger project.
- Promoting `Hibernate` to a first-class `CueAction` enum value so
  OSC/MIDI/plugins can originate hibernation directly. Deferred
  until a real consumer needs it.
- Operator-configurable colour for the hibernating status icon.
- A preset template for the "fade out, hibernate, fade in, resume"
  pattern (roadmap cross-cutting item).
- A shared `_FaderDrivenActionCue` base class between StopCue and
  ResumeCue (roadmap cross-cutting item).

## Open questions

None remaining at spec time. Colour choice for the hibernating icon
(`#5AF`) is the only aesthetic call and is trivially tunable post-
implementation.
