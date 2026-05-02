# Threading Model

LiSP runs on the Qt main loop with a small but growing set of worker
threads — pre-arm pipeline init, cue start/stop, GStreamer bus
callbacks, and the test-harness JSON-RPC server. This document captures
the rules each subsystem follows and the patterns that keep them safe.

If you're adding code that emits signals, mutates cue state, or touches
GStreamer pipelines, **read this first**.

---

## Threads in play

| Thread                      | Owner                                  | Triggers work via                                              |
|-----------------------------|----------------------------------------|----------------------------------------------------------------|
| Qt main thread              | `QApplication`                         | Widget events, `QTimer`, queued slots                          |
| Cue worker threads          | `@async_function` decorator            | `cue.start()`, `cue.stop()`, `cue.fadein()`, `cue.fadeout()`   |
| Pre-arm worker threads      | Same as cue workers, plus the prearm path in `PreArmManager._try_arm` | Standby visit, edit-invalidation, post-stop re-arm |
| `Clock_33` callbacks        | `QTimer` on the main thread            | Crossfade monitor, fade tickers                                |
| GStreamer bus callbacks     | GStreamer pipeline                     | `Gst.MessageType.{EOS,ERROR,SEGMENT_DONE,...}`                 |
| `ThreadPoolExecutor`(1)     | `UriInput.__duration` and similar      | Async metadata discovery on URI change                         |
| Test-harness server thread  | `lisp.plugins.test_harness.server`     | JSON-RPC requests over a TCP socket                            |

The Qt main thread is "single-writer" for widget state, the layout's
selection cursor, the cue model's row order, and anything else read by
`paintEvent` / `QTreeWidgetItem` data. Anything else can race.

---

## Cross-thread invocations

When a worker needs to touch Qt state, it MUST hop to the main thread.
There are three idiomatic ways:

* **`Connection.QtQueued`** when connecting a `Signal` slot. The slot
  fires on the Qt main thread asynchronously regardless of where the
  emit happens. Used heavily in `GroupCue` for child end-handlers, in
  `CartLayout` for widget updates, and in `PreArmManager` for the
  crossfade-arm relay.
* **`Connection.QtDirect`** for synchronous hop where the emitter
  must wait. Rare — most emitters can't safely block.
* **`invoke_on_main_thread(fn)`** (test_harness) when a worker
  thread needs to mutate the layout / commands stack from a JSON-RPC
  handler.

If a slot reads or writes a `QWidget`, `QListWidgetItem`, the cue model's
ordering, or any property whose setter rebuilds Qt items
(`group_id`, `index`, `collapsed`, `disabled`), it MUST be connected as
`QtQueued` (or invoked through the harness's main-thread hop).

---

## `lisp.core.signal` — the custom signal/slot bus

LiSP does **not** use Qt's signal/slot for non-widget events. The
`Signal` class in `lisp/core/signal.py` is a weak-ref-based dispatcher
with four delivery modes (Direct, Async, QtDirect, QtQueued).

Two invariants that have been bug-load-bearing:

1. **`emit()` snapshots before iterating.** It takes the slot lock, copies
   `__slots.values()` into a list, releases the lock, and invokes from
   the snapshot. The reasons:
   * The lock is an `RLock`. Weak-ref finalizer callbacks run during GC
     on the same thread — they can re-enter `__remove_slot` and mutate
     `__slots` mid-iteration. Iterating the live dict crashes with
     `RuntimeError: dictionary changed size during iteration`.
   * Slots are free to call `connect`/`disconnect` while running — they
     do this in production (e.g. `_restore_fadein` in `GroupCue`
     disconnects itself after firing).
   * Slot calls happen lock-free, so two threads emitting concurrently
     can interleave their slot invocations. Slots are responsible for
     their own thread-safety.

2. **Slots must be reachable strongly somewhere.** `Signal.connect`
   stores the slot via `weakref.WeakMethod` (for bound methods) or
   `weakref.ref` (for plain callables). A `lambda` passed at the call
   site has no other strong reference and is GC'd before any emit
   reaches it. Patterns to follow:
   * Connect bound methods: `signal.connect(self.handler)`.
   * For per-call closures (e.g. one-shot stop handlers in crossfade),
     hold a strong ref in a class attribute or a module-level dict
     keyed by lifetime owner. `PreArmManager._cue_handlers` is the
     canonical example.

---

## `GstMedia.__init_pipeline` — the serialised path

`__init_pipeline` rebuilds the GStreamer pipeline. It can be called
from at least three vectors:

* `media.play()` when state is Null
* `media.prearm()` when state is Null
* `media.__on_pipe_changed()` when `pipe` is reassigned

Before the lock fix, two vectors firing concurrently for the same media
(typically `PreArmManager.prearm` on the standby cue + the
parallel-mode `GroupCue.start` firing the same cue from a worker
thread) would each clear `self.elements`, build into different
`Gst.Pipeline` instances, and end up with elements linked across
pipelines. Symptoms: silent reset of `UriInput.uri` and `duration` to
defaults, GStreamer warnings about cross-pipeline links, and a CPU
core pegged on the GStreamer state machine churning on a tangled
pipeline.

The fix wraps the rebuild in `self.__init_lock`
(`threading.Lock`, deliberately non-reentrant). There is also a
skip-if-coherent fast path at the top of `__init_pipeline_locked`: if
the live pipeline already matches `pipe` and is in a usable state
(READY/PAUSED/PLAYING), the second thread bails out instead of tearing
down a perfectly good pipeline.

**DO NOT** connect a slot to `media.elements_changed` or to
`media.changed("duration")` that mutates `media.pipe`,
`media.start_time`, or otherwise loops back into `__init_pipeline`.
The non-reentrant lock will deadlock — that is intentional. Reentrant
rebuild is always a bug.

---

## `PreArmManager` and the standby cursor

`PreArmManager` owns a small set of cues that are pre-armed (pipeline
in PAUSED, ready to drop straight into PLAYING). It auto-arms the
layout's standby cue and any cue marked `preload=True`.

Hot paths that fire on the main thread:

* `session_loaded` — sweeps preload-marked cues + standby
* `standby_changed` — disarms previous standby (if Auto-only), arms new
* `cue_added` / `cue_removed` — wires per-cue listeners
* `cue_executed` — drops the cue from the armed set without disarming
  the pipeline (it's about to play)
* `on_uri_changed`, `on_start_time_changed`, `on_preload_changed` —
  edit invalidation

Hot paths that fire off the main thread:

* `media.prearm()` itself runs on whichever thread `_try_arm` was
  called from. Today that's the main thread (signal handlers above) —
  but `_try_arm` does no main-thread-only work, so this isn't load-bearing.

The race that motivated the `__init_lock`: standby moves to a cue at
the same instant a parallel `GroupCue` fires it. PreArmManager's
`_try_arm` calls `media.prearm()` on the main thread, while
`GroupCue._start_parallel` calls `child.execute(Start)` which spawns a
worker thread that lands in `media.play()`. Both reach
`__init_pipeline` concurrently. The lock now serialises them.

If you add a path that calls `media.prearm()` or `media.play()` from a
new thread, check whether it can race with an existing one. The lock
will save you from corruption, but redundant rebuilds are still wasted
CPU; hit the fast path by checking `media.state` first.

---

## Testing concurrency code

* Unit tests can drive concurrency directly with `threading.Thread` +
  `Barrier`. See
  `tests/plugins/gst_backend/test_gst_media_init_pipeline_race.py` for
  the pattern: barrier-synchronised workers + monkeypatch of the
  critical body to widen the race window with `time.sleep`.
* Don't rely on Python's GIL to make races impossible — the GIL
  releases on I/O, on C extension calls (most GStreamer ops), and on
  every `sys.setswitchinterval()` boundary.
* For race tests, verify they FAIL when the synchronisation primitive
  is removed. A test that passes both with and without the lock is
  testing nothing.
* E2E tests can drive UI-style concurrency through the test harness,
  but the harness can't reproduce every UI-thread scheduling pattern
  (e.g. the standby-cursor / parallel-start race that motivated the
  `__init_lock` does not reproduce purely via JSON-RPC). Cover what
  the harness can and use unit tests for the rest.
