# Disable Cues Without Removing Them

## Overview

Introduce a per-cue `disabled` flag that makes a cue inert for
playback purposes without removing it from the session. A disabled
cue stays in the list and remains fully editable, but the playback
head steps over it: GO skips past it, auto-follow chains jump over
it, and playlist/parallel group children marked disabled do not
start. Disabling a group cascades to all of its descendants.

The target use case is multi-performance runs where the cue list
differs between shows (e.g. Saturday vs Sunday of a weekend run).
Instead of duplicating sessions or deleting-and-reinserting cues,
the operator toggles the differences in the inspector.

This spec covers only the per-cue flag. A larger "named show
variants" feature (where a session remembers multiple enabled-cue
profiles and switches between them) is explicitly out of scope; if
built later, it layers on top of this flag.

The feature applies equally to the list layout and the cart
layout: gating at `Cue.execute()` covers every trigger source
across both, and visual dimming is implemented for each layout's
row/cell renderer.

## User-facing behaviour

1. Each cue has an **Enabled** checkbox in the inspector's General
   page (ticked by default). Unticking it disables the cue.
2. A disabled cue is visually **dimmed** (reduced opacity) in both
   the list layout and the cart layout. It is still visible,
   selectable, and editable.
3. A disabled cue **refuses to start** from any trigger source — GO
   button, manual click, keyboard shortcut, MIDI, OSC, remote
   control, auto-follow chain, playlist group advance, parallel
   group start. The cue is inert.
4. A disabled cue can still be **stopped, paused, or interrupted**
   (including by Stop All / Interrupt All). This matters because a
   cue can be disabled while already playing.
5. Disabling a cue that is currently playing **lets it finish** —
   the disable only affects *future* triggers. Pause and stop
   actions on it still work normally.
6. **Disabling a group cascades**: all descendants of a disabled
   group become effectively disabled for playback. A child's own
   disable state is preserved independently — re-enabling the group
   leaves individually-disabled children still disabled.
7. **Auto-follow and select-after chains skip past** disabled cues
   to the next enabled cue. If nothing enabled is downstream, the
   chain ends silently.
8. The **standby indicator** can still be placed on a disabled cue
   (e.g. by clicking it). **GO from there is a no-op** — it does
   not fire the cue and does not advance standby. The operator
   must manually move standby to an enabled cue. This is more
   explicit than silently skipping, which could obscure that the
   standby had been left on a disabled row.
   Auto-continue AFTER a successful GO still skips past disabled
   cues when parking standby on the next one.
9. Toggling the flag is **undoable** through the standard Ctrl+Z
   path.
10. The flag **persists in the session file** and round-trips
    cleanly. Old sessions open with every cue enabled.

## Architecture

### Data model

Add one property to `Cue` in
[`lisp/cues/cue.py`](../../lisp/cues/cue.py):

```python
disabled = Property(default=False)
```

Add one computed accessor on `Cue`:

```python
@property
def effective_disabled(self) -> bool:
    """True if this cue or any ancestor group is disabled."""
    if self.disabled:
        return True
    gid = self.group_id
    while gid:
        parent = self.app.cue_model.get(gid)
        if parent is None:
            break
        if parent.disabled:
            return True
        gid = parent.group_id
    return False
```

Design points:

- `disabled` is the only stored bit — one per cue. `HasProperties`
  serialises it to JSON automatically; no session-file schema
  changes are needed.
- `effective_disabled` computes the cascade at read time by walking
  up the `group_id` chain. No caching, no invalidation logic. In
  practice the chain depth is 1–2 hops; the walk is cheap.
- Computing at read time is what makes the "preserve individual
  child state" semantics fall out naturally — a child's stored
  `disabled` never changes in response to a parent toggle.
- Deleting a parent group already clears `group_id` on its
  children via the existing ungrouping code, so
  `effective_disabled` falls back to the child's own flag.

### Playback gate

`Cue.execute()` at [`lisp/cues/cue.py:183`](../../lisp/cues/cue.py)
is the single public entry point through which every trigger source
flows (GO, click, MIDI, OSC, keyboard, auto-follow, group playback,
remote). Gate there:

```python
if self.effective_disabled and action not in (
    CueAction.Stop, CueAction.Interrupt,
    CueAction.FadeOutStop, CueAction.FadeOutInterrupt,
    CueAction.Pause, CueAction.FadeOutPause,
):
    return False
```

Stop / Pause / Interrupt actions bypass the gate so that:

- Stop All / Interrupt All continues to work on the cue if it is
  currently playing (a cue can be disabled while playing — "let it
  finish" still requires explicit stop paths to remain functional).
- In-flight fadeouts triggered as part of a stop/interrupt
  complete as normal.

Returning `False` (not `None`) matches the contract already used
by the exclusive-manager block above it, so the list layout's
`go()` logic already handles the value correctly.

The gate is deliberately placed at `execute()` — **not** at the
internal `start()`/`stop()` methods. Internal methods are also
called by fade automation and post-wait triggers on already-playing
cues; blocking there would break the "let it finish" rule.

### Playback-head skipping

Three sites in
[`lisp/plugins/list_layout/layout.py`](../../lisp/plugins/list_layout/layout.py)
need to skip disabled cues when advancing. All three already skip
grouped children; each gets an additional `effective_disabled`
check in the same continue-condition:

1. **`_advance_standby_past_children`** (line 323) — the loop that
   advances the standby pointer after GO with auto-continue. Skip
   cues where `cue.effective_disabled`.
2. **Next-action chain loop** (line 625) — when a cue ends and its
   `next_action` is `TriggerAfterEnd` / `SelectAfterEnd` /
   `TriggerAfterWait` / `SelectAfterWait`, the loop that finds the
   next non-child cue. Skip disabled cues the same way.
3. **`set_standby_index`** — no change: allow standby to land on a
   disabled cue (visual reference point). Subsequent GO skips past
   it via #1.

### Group cue playback

In
[`lisp/plugins/action_cues/group_cue.py`](../../lisp/plugins/action_cues/group_cue.py):

- **Playlist mode**: `_resolve_children()` and the playlist
  advance logic filter out children where `effective_disabled` is
  True. A playlist over [A, B(disabled), C] plays A then C.
- **Parallel mode**: at start time, skip children whose
  `effective_disabled` is True. Only enabled children start.
- **Group disabled mid-playback**: the currently-playing child is
  allowed to finish (execute-gate does not interrupt it), but the
  playlist does not advance. The running child is the last thing
  audible before the group falls silent.

### UI: inspector checkbox

In
[`lisp/ui/settings/cue_pages/cue_general.py`](../../lisp/ui/settings/cue_pages/cue_general.py)
(`CueGeneralSettingsPage`):

- Add an **Enabled** checkbox at the top of the page, above the
  Pre-wait / Post-wait rows. Ticked = enabled; unticked maps to
  `disabled=True`. Labelling as "Enabled" reads more naturally in
  a settings context than "Disabled".
- Wire it through the existing `CueSettingsPage`
  load/get-settings plumbing. The inspector's commit engine at
  [`lisp/ui/inspector/commit.py`](../../lisp/ui/inspector/commit.py)
  routes the change through the standard property-set path,
  producing an automatic undoable entry on `CommandsStack` and
  emitting `cue.changed("disabled")`.
- Multi-select with mixed values reuses the inspector's existing
  `mixed_values.py` tri-state handling — no new code.

Add the new translatable string "Enabled" to
[`lisp/i18n/ts/en/lisp.ts`](../../lisp/i18n/ts/en/lisp.ts) via the
standard `translate()` wrapping.

### UI: dimmed rows

In
[`lisp/plugins/list_layout/list_view.py`](../../lisp/plugins/list_layout/list_view.py)
(around the `css_to_dict` call at line 389):

- When rendering a row, check `cue.effective_disabled`. If true,
  apply reduced opacity (~40%) to the row's widgets via stylesheet
  (for example `color: rgba(..., 0.4)` and proportional alpha on
  backgrounds).
- Subscribe to both `cue.changed("disabled")` **and**
  `cue.changed("group_id")` on each row. The second subscription
  is essential: a cue's effective state can flip without its own
  `disabled` changing, when its parent group is toggled or when
  it is regrouped into a disabled ancestor.

The cart layout applies the same dimming rule when styling a cart
cell. A click on a dimmed cell does nothing because the
`execute()` gate rejects the start.

### Session compatibility

- A session saved by the new version loads correctly in older
  versions — unknown JSON keys are ignored by the older
  `HasProperties` loader.
- An old session loads in the new version with every cue
  defaulting to `disabled=False`, which matches user expectation.
- No migration step required.

## Edge cases

| Scenario | Behaviour |
|---|---|
| Disable a playing cue | Continues; next trigger blocked. |
| Disable a cue mid-fadeout | Fadeout completes. |
| Disabled cue is the standby target | Standby stays on it; GO skips past. |
| Disable a group with a running playlist child | Child finishes; playlist does not advance. |
| Re-parent a cue into a disabled group | Row dims immediately (via `group_id` subscription). |
| Parent group deleted while children carry stale `group_id` | Existing ungrouping clears `group_id`; `effective_disabled` falls back to the cue's own flag. |
| Stop All / Interrupt All with disabled cues playing | Still stops/interrupts them — Stop/Interrupt actions are exempt from the gate. |
| MIDI/OSC controller fires a disabled cue | `execute()` returns `False`; no effect. No controller-plugin changes required. |
| Next-action chain lands on a disabled cue | Chain skips to next enabled cue. |
| All cues downstream are disabled | Chain ends silently. |

## Test plan

### Unit tests

Under `tests/`, using the existing `mock_app` fixture:

- `tests/cues/test_cue_disabled.py`
  - New cue defaults to `disabled=False`.
  - Setting `disabled` emits a `changed("disabled")` signal.
  - `effective_disabled` walks the `group_id` chain: single
    parent, two-level nesting, missing-parent fallback.
  - `execute()` with `Start` / `FadeInStart` / `Resume` /
    `FadeInResume` returns `False` when `effective_disabled` is
    True.
  - `execute()` with `Stop` / `Pause` / `Interrupt` (and their
    fade variants) proceeds even when `effective_disabled` is
    True.
  - Session round-trip: serialise a disabled cue, deserialise,
    flag survives.

- `tests/plugins/list_layout/test_disabled_skip.py`
  - `_advance_standby_past_children` skips disabled cues.
  - `TriggerAfterEnd` chain jumps past a disabled follower to the
    next enabled cue.
  - `SelectAfterEnd` lands standby on the next enabled cue.
  - Chain runs off the end when everything downstream is disabled
    — no-op, no exception.

- `tests/plugins/action_cues/test_group_cue_disabled.py`
  - Playlist group with [A, B(disabled), C] plays A then C.
  - Parallel group with children [A(disabled), B] starts only B.
  - Disabling the group mid-playback lets the current child
    finish and does not advance.

### E2E tests

Under `tests/e2e/`, run as standalone scripts via the
`test_harness` plugin (`python tests/e2e/<name>.py`), following
the project convention (they launch LiSP themselves; not invoked
via pytest):

- `tests/e2e/test_disabled_cue.py`
  - Create two StopAll cues; disable one; call `layout.go`;
    subscribe to `started` signals via `signals.subscribe` +
    `signals.wait_for`; assert only the enabled one fires.
  - Disable a group containing two MediaCues; call
    `cue.execute` on each child; assert neither plays (no
    `started` signal within timeout). Re-enable the group; repeat
    and assert both play.
  - Save session with disabled flags → reload → assert flags
    restored by reading cue properties via `cue.list`.

### Manual UI verification

The project convention requires UI features to be exercised in a
real browser / window before being marked complete. For this
feature, manually verify:

- Dimmed row appearance in the list layout (disabled cue is
  legible but visibly de-emphasised).
- Dimmed cell appearance in the cart layout.
- Inspector tri-state **Enabled** checkbox with multi-selected
  cues of mixed state.
- Re-parent a cue into a disabled group → row dims immediately
  without requiring a reload.
- Toggle via inspector → Ctrl+Z undoes, Ctrl+Shift+Z redoes.

## Out of scope (v1)

- Keyboard shortcut for toggle. (Easy to add later; the commit
  engine accepts property sets from any source.)
- Context-menu "Disable / Enable" entries.
- Dedicated column / badge / status icon on the row.
- Per-cue "disabled reason" annotation.
- Named show variants, tagging, or session-level filters. Any of
  these can layer on top of the `disabled` flag later.
