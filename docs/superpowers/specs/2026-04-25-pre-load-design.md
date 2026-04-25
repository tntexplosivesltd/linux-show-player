# Pre-Load (Pre-Arm) — Design

**Date:** 2026-04-25
**Status:** Draft

## Goal

Eliminate the GO-press latency caused by GStreamer's NULL → READY → PAUSED preroll, by transitioning eligible audio cues to PAUSED ahead of time. Pre-armed cues play with deterministic, sub-perceptual start latency on the GO press. Two complementary triggers cover the feature surface:

1. **Auto look-ahead** — the layout's standby cue is pre-armed automatically; the window slides forward on each GO.
2. **Per-cue "preload" override** — designers explicitly mark critical cues to be armed at session-load and stay armed regardless of standby position.

The feature is opt-in at runtime (config flag) and resource-bounded (configurable cap on simultaneously armed cues), so it works on hardware from a Raspberry Pi 4 to a high-end show machine.

## Non-Goals

- **Decoded-PCM-in-RAM playback.** A separate, larger architecture (a `MemoryInput` element with `appsrc`-fed pipeline) would be required for QLab-equivalent "load entire file as raw samples". This spec covers pipeline preroll only.
- **A/V cue pre-arming.** Only audio (`UriInput`) cues are eligible. A/V cues (`UriAvInput`) bring video-window negotiation, GPU resources, and disproportionate complexity for a smaller perceptual win.
- **Group cue pre-arming.** `GroupCue` is not pre-arm-eligible; the per-cue checkbox does not appear on groups. Children inside groups can still be marked individually.
- **Active mtime polling.** A pre-armed cue's source file changing silently mid-show is not detected. mtime is captured at arm time and re-checked only on subsequent arm decisions.
- **Auto-retry on failure.** Failed pre-arm does not retry on a timer. Recovery is operator-driven (fix the file, edit the cue's URI, or reload the session).
- **Removing storage from the playback path.** Pre-arm primes the GStreamer pipeline; the source file is still streamed from disk during playback. Yanking storage mid-cue still produces a dropout.
- **Mid-show file-replacement detection.** Out of scope; documented limitation.

## Locked Decisions

| # | Question | Decision |
|---|----------|----------|
| 1 | Scope | Layered: auto look-ahead **and** per-cue "preload" override. |
| 2 | Resource constraints | Soft cap with config knob. Default `maxArmed = 16`. |
| 3 | Media type | Audio cues only (`UriInput`); A/V cues excluded. |
| 4 | Group cues | Not pre-arm-eligible. |
| 5 | Visibility | Subtle indicator dot in cue list; green = armed, red = preload-marked failure, none = anything else. |
| 6 | Invalidation | Targeted: URI change → re-arm; `start_time` change → re-seek; mtime change at next visit → re-arm; everything else applies hot via existing `GstProperty`. |
| 7 | Failure handling | Best-effort, non-blocking, no retry. Failed GO falls through to the normal play path. |
| — | Hibernate | Mid-playback state, invisible to the manager. No special handling. |
| — | Notifications | Pre-arm failures of `preload=True` cues emit a `NotificationLevel.Warning` toast. Auto-arm and cap-refusal failures stay silent. |

## Architecture

The feature splits into three responsibilities mapped onto LiSP's existing layers.

```
┌────────────────────────────────────────────────────────────┐
│  Policy layer:   PreArmManager  (lisp/cues/)              │
│    • owns the armed-set                                    │
│    • enforces the cap                                      │
│    • listens to standby-changed, cue lifecycle, edits     │
│    • decides who should be armed at any moment            │
└────────────────────────────────────────────────────────────┘
                          │ calls .prearm() / .disarm()
                          ▼
┌────────────────────────────────────────────────────────────┐
│  Mechanism layer: Media / GstMedia                         │
│    • new prearm() / disarm() / reseek() methods           │
│    • new MediaState.Armed                                  │
│    • play() recognises Armed and skips redundant preroll   │
└────────────────────────────────────────────────────────────┘
                          │ drives GStreamer pipeline state
                          ▼
┌────────────────────────────────────────────────────────────┐
│  Surface layer:  MediaCue.preload property                 │
│                  list_layout indicator render hook         │
│                  settings dialog checkbox                  │
│                  Application.notify toasts                 │
│                  lisp.json config block                    │
└────────────────────────────────────────────────────────────┘
```

### Design rules

1. **`PreArmManager` is the only thing that calls `prearm()` / `disarm()`.** All other components express *intent* via signals; the manager translates intent into mechanism. Direct calls would make cap and lifecycle invariants impossible to enforce.

2. **`MediaState.Armed` is distinct from `Paused`.** They map to the same GStreamer state but mean different things to LiSP: `Paused` is "user-initiated mid-playback hold", `Armed` is "pre-loaded, never started". The state distinction prevents `play()` (`gst_media.py:88–106`) from seeking to `current_time()` instead of `start_time` when resuming an armed cue.

3. **Reconciliation, not delta-tracking.** Manager signal handlers compute "what should be armed right now" and reconcile against the current `_armed` set. Missed or duplicated signals can't desynchronise the model.

4. **No exception leaks out of the manager.** Every public method wraps its body in try/except → ERROR log → return. The manager is glue between subsystems and must never crash the show.

5. **Cap counts armed cues only.** Mid-playback cues (Playing, Paused, Hibernating) are not in `_armed` and don't consume cap budget. A user-paused or hibernated cue holds its pipeline outside the cap; this is acceptable because hibernate is rare and intentional, and tracking everything would force the manager to evict user-initiated playback.

## Components

### `Media` ABC additions — `lisp/backend/media.py`

```python
class MediaState(Enum):
    Null = ...
    Stopped = ...
    Playing = ...
    Paused = ...
    Armed = auto()        # NEW
    ...

class Media(HasProperties):
    def prearm(self) -> bool: ...    # NEW
    def disarm(self) -> None: ...    # NEW
    def reseek(self, position: int) -> None: ...   # NEW
```

`prearm()` returns `True` on success, `False` on any failure. Must not raise — failures are reported via return value plus a logged WARNING. `disarm()` and `reseek()` are idempotent on inappropriate states (e.g., `disarm()` on a NULL pipeline is a silent no-op).

Default implementations on the abstract: `prearm()` returns `False` and logs DEBUG ("backend doesn't support pre-arm"); `disarm()` and `reseek()` are no-ops. Alternative backends without pre-arm support thus refuse to arm rather than crashing.

New signals: `armed`, `disarmed`.

### `GstMedia.prearm()` / `.disarm()` / `.reseek()` — `lisp/plugins/gst_backend/gst_media.py`

```python
def prearm(self) -> bool:
    if self.state in (MediaState.Playing, MediaState.Paused, MediaState.Armed):
        return True
    if self.state == MediaState.Null:
        self.__init_pipeline()
    self.__pipeline.set_state(Gst.State.PAUSED)
    ret, *_ = self.__pipeline.get_state(Gst.SECOND)
    if ret != Gst.StateChangeReturn.SUCCESS:
        self.disarm()
        return False
    self.__seek(self.start_time)
    self._state = MediaState.Armed
    self.armed.emit(self)
    return True

def disarm(self) -> None:
    if self.state != MediaState.Armed:
        return
    self.__pipeline.set_state(Gst.State.NULL)
    self._state = MediaState.Null
    self.disarmed.emit(self)

def reseek(self, position: int) -> None:
    if self.state != MediaState.Armed:
        return
    self.__seek(position)
```

`play()` (currently `gst_media.py:88–106`) is amended:

- If state is `Armed`, skip the PAUSED transition and the `__seek(start_time)` (already done at arm time) and go straight to `set_state(PLAYING)`.
- If state is `Paused`, behaviour is unchanged (existing resume path).

`stop()` (`gst_media.py:125`) tears down to NULL as today; the manager re-arms if appropriate.

### `MediaCue.preload` property — `lisp/cues/media_cue.py`

```python
preload = Property(default=False)
```

Pure data — the manager observes `media_cue.changed("preload")` to react. The property surfaces in the cue settings dialog as a checkbox. Saved/loaded via the existing `Property` mechanism, so old session files load with `preload=False` and new sessions opened in old LiSP versions silently ignore the property.

### `PreArmManager` — `lisp/cues/pre_arm_manager.py` (new file)

```python
class ArmReason(Flag):
    Auto = 1
    Preload = 2

class PreArmManager:
    def __init__(self, app):
        self._app = app
        self._armed: dict[str, ArmReason] = {}   # cue_id → reason
        self._failed: dict[str, str] = {}         # cue_id → reason text
        self._mtime_at_arm: dict[str, float] = {}
        self._cap = app.conf.get("preArm.maxArmed", 16)
        self._lookahead = app.conf.get("preArm.lookahead", 1)
        self._enabled = app.conf.get("preArm.enabled", True)
        self.armed_set_changed = Signal()
        # subscribe to application + cue_model signals here

    # Public surface
    def session_loaded(self): ...
    def session_closing(self): ...
    def standby_changed(self, layout, new_cue): ...
    def cue_added(self, cue): ...
    def cue_removed(self, cue): ...
    def cue_executed(self, cue): ...
    def request_rearm(self, cue): ...
```

Subscriptions:

- `Application.session_created` → `session_loaded`
- `Application.session_closing` → `session_closing`
- `cue_model.item_added` / `item_removed`
- Active layout's `standby_changed` and `cue_executed`
- Per-cue: `started`, `stopped`, `interrupted`, `end`, `error`, `changed("preload")`, `changed("uri")`, `changed("start_time")`

Cue eligibility predicate:

- Cue is a `MediaCue`.
- Underlying media's `MediaType == Audio` (excludes `UriAvInput`).
- Cue is not a `GroupCue`.
- Cue is not currently in any flavour of mid-playback.
- `_enabled` is `True`.

Arm-priority order (when cap pressure exists): preload-marked cues > auto look-ahead. Preload-marked cues are armed first at session-load; auto look-ahead is best-effort.

### `list_layout` indicator hook — list view row delegate

The list view already paints per-row state using `Cue.state` colour coding. We add an 8 px circle in the row's leading margin:

- **Green dot** — cue is in `_armed` (any reason).
- **Red dot** — cue is `preload=True` and in `_failed`.
- **No dot** — anything else.

The view subscribes to `PreArmManager.armed_set_changed` and triggers a row repaint for affected indices. Hovering a red dot shows a tooltip with the `_failed[cue_id]` reason text.

### Settings UI — cue settings dialog

A single "Preload at session load" checkbox in the cue's media-input settings page. Audio cues only — hidden when the cue's media type is A/V or the cue is a GroupCue. Default unchecked. Standard settings-dialog plumbing (read on dialog open, write on apply).

### Notifications — `Application.notify`

Pre-arm failures of `preload=True` cues fire `Application.notify.emit(message, NotificationLevel.Warning)`. The existing toast widget (`lisp/ui/widgets/notification.py`) handles display. Wording:

- Single failure: `Failed to preload "{cue_name}": {category}` where `{category}` is one of `file not found`, `audio decoder error`, `audio output error`, `preload took too long`.
- Multiple failures during a single session-load batch: `Failed to preload {N} cues — see log for details`.

The full GStreamer error text goes to the WARNING log line, not the toast.

### Configuration — `lisp/default.json`

```json
"preArm": {
    "enabled": true,
    "lookahead": 1,
    "maxArmed": 16,
    "failOnCapHit": false
}
```

`failOnCapHit` controls whether refusing an arm at the cap counts as a failure (red indicator + toast) or a silent skip. Default `false`: cap-refusals are normal pressure, not errors.

### Application wiring — `lisp/application.py`

Two lines at app init, after `cue_model` and session signals exist:

```python
from lisp.cues.pre_arm_manager import PreArmManager
self.pre_arm_manager = PreArmManager(self)
```

The manager's constructor wires its own signal subscriptions; nothing else needs to know it exists except the list_layout indicator (which reads `Application().pre_arm_manager`).

## Data Flow & Lifecycle

### Per-cue arm state machine

```
                 ┌──────────────────────┐
                 │       Unarmed        │ ◀─── default
                 │   (Media in Null)    │
                 └──────────┬───────────┘
                            │ arm()
                            ▼
                 ┌──────────────────────┐
            ┌───▶│       Arming         │
            │    │  (preroll in flight) │
            │    └──────────┬───────────┘
            │               │ preroll completes
            │               ▼
            │    ┌──────────────────────┐
            │    │        Armed         │◀────┐
            │    │  (Media in Armed)    │     │ rearm
            │    └─┬──────┬─────────────┘     │
            │      │      │                   │
            │ play │      │ disarm /          │
            │      │      │ invalidate        │
            │      ▼      ▼                   │
            │  ┌────────────────┐         ┌───┴──────┐
            └──┤    Playing     │────────▶│ Stopped  │
               └────────────────┘  end of └──────────┘
                                  playback
```

The manager owns the mapping `cue_id → ArmReason`. The "Playing" state absorbs every variant of mid-playback the cue can be in (`Running`, `Pause`, `Pause | Hibernating`, `PreWait_Pause`, `PostWait_Pause`, etc.). Pause/resume/hibernate/awaken transitions are below the manager's abstraction level.

### Key scenarios

**Session load.** Manager iterates `cue_model` for eligible cues with `preload=True`, calls `prearm()` on each up to `_cap`. Failures are collected; after the loop, a single coalesced toast is emitted if ≥2 failures occurred, or a per-cue toast if exactly one. After preload-marked cues are armed, the active layout's `standby_cue()` is armed if eligible and within cap.

**Operator presses GO** (`cue_executed` emitted by layout):

1. Manager removes the just-fired cue from `_armed` (it's now Playing).
2. Layout has already advanced standby internally (`list_layout/layout.py:328`).
3. Manager fetches new `standby_cue()` and arms it if eligible. Synchronous on the main thread (typical preroll: 5–50 ms; bounded at 1 s by `get_state(Gst.SECOND)` deadline).
4. When the current cue ends (`stopped` / `interrupted` / `end` / `error`): if `preload=True`, re-arm immediately. Otherwise stay Unarmed.

**Standby moves without GO.** Manager disarms cues that are `Auto`-only, retains those whose `ArmReason` includes `Preload`, and arms the new standby. A cue with `ArmReason == Auto | Preload` (preload-marked *and* on standby) downgrades to `Preload` when standby moves away — cue stays armed because the `Preload` bit is still set.

**Edit invalidation.**

- `changed("uri")` on an armed cue → `disarm()` + `prearm()`.
- `changed("start_time")` on an armed cue → `reseek(start_time)`. No teardown.
- `changed("preload")` true → `prearm()` if eligible. False → if `ArmReason == Preload`, disarm; if `ArmReason == Auto | Preload`, downgrade to `Auto`.
- mtime check: on every "should I arm/keep-armed?" decision, compare `cue.mtime > _mtime_at_arm[cue_id]`. If true, re-arm. No active polling.
- Other property changes (volume, pan, fade settings, etc.) propagate to the live PAUSED pipeline via `GstProperty.__set__` (`gst_properties.py:35–43`); no manager involvement needed.

**Cap pressure.** Manager about to arm but `len(_armed) >= cap`:

1. Refuse the arm. `_try_arm()` returns False.
2. Log INFO. If `failOnCapHit=true` and cue is `preload=True`, paint red dot + toast.
3. Preload-marked cues take priority — order of session-load arming ensures auto-look-ahead is what gets squeezed out first.

**Cue removed mid-arm.** `cue_model.item_removed` while `prearm()` is on the stack: manager defers cleanup until `prearm()` returns, then re-checks `cue_id in cue_model`; if absent, immediately `disarm()` and drop from `_armed`.

**App shutdown.** `session_closing` → manager iterates `_armed` and calls `disarm()` synchronously on each, wrapped in try/except. A failing teardown logs ERROR and continues.

### Look-ahead depth > 1

Manager arms standby plus the next N-1 eligible cues at and after standby (skipping group cues, A/V cues, disabled cues). `cue_executed` slides the window forward by one. `standby_changed` snaps the window to the new position; auto-only cues outside the new window are disarmed. Cap still binds — preload-marked cues consume budget before look-ahead does.

### Auto-continue chains

Layout fires `cue_executed` for every cue start, including auto-continued ones (verified at `cue.py:420–421` where `next_action` triggers `TriggerAfterWait` / `TriggerAfterEnd`). The manager's window slides on each. Worst case: a fast chain of auto-continues outruns arm latency and some links play un-armed — they play exactly as today (no regression).

### Hibernate

Hibernate (`Cue.state == Pause | Hibernating`, `cue.py:46`) is mid-playback and invisible to the manager. The manager subscribes only to `started`, `stopped`, `interrupted`, `end`, `error` — not `paused`, `hibernated`, `awoken`. A `preload=True` cue that's hibernated holds its pipeline (per existing hibernate mechanism) and is re-armed when it eventually exits playback.

## Error Handling

### Failure taxonomy

| Failure | Detected via | Indicator | Toast | Log |
|---------|--------------|-----------|-------|-----|
| Source file missing | `set_state(PAUSED)` returns FAILURE / bus ERROR | red if preload | per-cue if preload (or batch summary) | WARNING with path |
| Codec/plugin missing | `decodebin` posts ERROR | red if preload | per-cue if preload (or batch summary) | WARNING with GStreamer error |
| Sink refused | `set_state(PAUSED)` returns FAILURE | red if preload | per-cue if preload (or batch summary) | WARNING with sink name |
| Preroll timeout (>1 s) | `get_state` returns ASYNC | red if preload | per-cue if preload (or batch summary) | WARNING "preroll timeout" |
| Cap reached | `len(_armed) >= cap` | red iff `failOnCapHit && preload` | toast iff `failOnCapHit && preload` | INFO |
| Cue removed during arm | `item_removed` fires while `prearm()` on stack | none (cue is gone) | — | DEBUG |
| URI changed during arm | `changed("uri")` fires while `prearm()` on stack | per re-arm result | per re-arm result | DEBUG |
| File replaced silently mid-show | not detected | — | — | — |
| App shutdown during in-flight arm | `session_closing` | — | — | ERROR if teardown fails |
| Manager throws in signal handler | Python exception via Signal | none | — | ERROR (Signal swallows, logs) |

### Design rules

1. **All `prearm()` failures look the same to the manager.** It receives `False`. The error *message* differs (carried in WARNING log); the *control flow* is one path.

2. **`disarm()` and `reseek()` are unconditionally idempotent.** Safe on NULL pipelines, safe twice, safe on never-armed cues.

3. **No retry timer.** Recovery is operator-driven (edit URI / reload session).

4. **No partial-success states.** If audio decoder succeeds but sink negotiation fails, the cue is treated as fully failed (`disarm()`, indicator red).

5. **No queue-on-cap.** Cap refusals are not retried; the next `standby_changed` or `cue_executed` will retry naturally.

### Toast batching

- `session_loaded` collects failures locally; emits exactly one toast at the end (per-cue if N=1, summary if N≥2).
- Mid-show failures emit per-cue toasts directly. The toast widget's one-at-a-time display handles any visual race; WARNING logs always carry full detail.

## Testing

Three tiers.

### Unit — `PreArmManager`

`tests/cues/test_pre_arm_manager.py`. Uses the existing `mock_app` fixture (`tests/conftest.py`); never touches a real `Application`. Mocks `Media` to satisfy `prearm`/`disarm`/`reseek` calls and signals.

Scenarios:

- Cap enforcement: 16-cap manager, 17 preload-marked cues at session_load → 16 armed, 17th refused, INFO logged.
- Preload priority over auto: preload-marked cues fill cap first, standby refused.
- Standby reconciliation: standby moves cue 5 → 8 → 5; arm reasons transition Auto → none → Auto.
- `Auto | Preload` reason: preload-marked cue is also standby; standby moves away → reason downgrades to `Preload`, cue stays armed.
- GO advances window: fire 5 GOs, assert armed set follows standby and capacity stays ≤ cap+1 transiently.
- Edit invalidation routing: URI change → `disarm`+`prearm`; `start_time` change → `reseek`; `volume` change → no manager interaction.
- Failure path: mock `prearm()` returns `False` → manager records in `_failed`, paints red only for preload, no exception leaked.
- Notification routing: assert `app.notify.emit` called with expected level for preload failures; assert NOT called for auto-only failures or cap refusals.
- Batch coalescing: ≥2 simultaneous failures during `session_loaded` → exactly one summary toast.
- Race: cue removed during arm → post-arm cleanup runs, cue not in `_armed`.
- Reconciliation idempotence: `standby_changed` twice with same target → no double-arm.
- Hibernate non-event: simulate Playing → Paused | Hibernating → Playing → manager makes no calls.

### Unit — `GstMedia.prearm()` / `.disarm()` / `.reseek()`

`tests/plugins/gst_backend/test_gst_media_prearm.py`. Uses pytest-qt's `qtbot` for QApplication; uses a generated test WAV fixture.

Scenarios:

- Successful prearm: Null → `prearm()` → Armed; `armed` signal fired exactly once.
- Disarm from armed: state back to Null; `disarmed` fired.
- Disarm from null: no-op, no signal.
- Idempotent prearm: second call is no-op.
- Play from armed skips preroll: monkeypatch `__pipeline.set_state` to record calls; assert play does NOT call `set_state(PAUSED)` again before `set_state(PLAYING)`.
- Failed prearm with bad URI: returns `False`, state is Null, WARNING logged (use `caplog`).
- `reseek` while armed: still Armed; position query returns expected offset.

### E2E — test harness

`tests/e2e/test_pre_arm.py`, run as a standalone script per project convention. Uses `lisp/plugins/test_harness/`. Two new RPC methods are added to the harness:

- `pre_arm.status` → `{"armed": {cue_id: reason}, "failed": {cue_id: text}}`.
- `pre_arm.wait_for_armed` → block until specific cue is armed (subscription-style).

Scenarios:

- Session-load preload: load fixture with three preload-marked cues → assert all three armed.
- Standby auto-arm: load fixture without preload marks → assert standby cue armed within 500 ms.
- GO advances: standby on cue 1 → fire GO → wait_for_armed cue 2 → assert cue 1 not in armed set.
- Real latency measurement: time GO operation on (a) non-preload cue, (b) preload cue. Assert preload GO is at least 50 ms faster on a slow-to-decode MP3 fixture. (The only test that *measures* the win.)
- Failed preload indicator: load session referencing missing file → assert `pre_arm.status` reports `failed` for that cue.
- Cap pressure: set `preArm.maxArmed=2` via lisp.json before launch, load session with 5 preload cues → assert exactly 2 armed and rest refused.
- Notification single failure: load session with one broken preload cue, subscribed to `app.notify` → expect one per-cue toast naming that cue, level Warning.
- Notification batch coalescing: load session with three broken preload cues → expect exactly one summary toast.
- Notification mid-show: load session with one healthy preload cue, edit URI to point at missing file via harness → expect one direct per-cue toast (no summary).
- Auto-arm failure silent: load session with no preload marks but broken file as standby cue → drain `app.notify` for 1 s → assert zero events.
- Cap refusal silent: as above for cap pressure → assert zero `app.notify` events.

### Out-of-scope for automated tests

- Multi-hour sessions / sustained hibernate behaviour. Manual rehearsal only.
- Real audio device contention (raw-ALSA exclusive, etc.). Impractical in CI.
- Session-file forward/backward compatibility — covered implicitly by `Property(default=False)`.

## Limitations & Future Work

- **Mid-show file-replacement detection** is absent. A `preArm.mtimePollSeconds` config knob with a periodic `stat()` loop is straightforward to add later if needed.
- **Synchronous `prearm()` on the main thread** can block for up to 1 s in pathological cases. Could be moved to a worker thread with `@async_in_pool` (precedent at `uri_input.py:84`) at the cost of async indicator transitions and races.
- **A/V cue audio-branch-only pre-arm** (interpretation C from the brainstorm) remains a possible future feature for designers who need video cue audio-attack timing without the video-window side effects.
- **Decoded-PCM-in-RAM playback** (`MemoryInput` element) remains the larger architectural option for full QLab-equivalent storage detachment and instant scrub.
- **System-wide pipeline cap** — currently the cap is "armed cues only", and user-paused / hibernated cues consume resources outside the cap. A future refactor could unify into a single live-pipeline budget at the cost of needing eviction logic for user-initiated playback.
