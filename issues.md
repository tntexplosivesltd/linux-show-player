# Code Review Issues

## Introduced by Changes (since 483e904)

### Critical

- [x] **#1 — GroupCue.__interrupt__ returns None**
  `lisp/plugins/action_cues/group_cue.py:401`
  Base class expects truthy return for state transitions. Missing `return True` means cue may get stuck in Running state after interrupt.

- [x] **#2 — GroupCue has no __resume__ override**
  `lisp/plugins/action_cues/group_cue.py`
  Resume after pause calls `__start__` which restarts children from scratch instead of resuming them. Causes audio doubling in parallel mode and playlist index reset.

- [x] **#3 — Test harness session.save/session.load accept arbitrary file paths**
  `lisp/plugins/test_harness/handlers.py:385-406`
  No path validation. Any local process on the same user can read/write arbitrary files through the session save/load mechanism.

### High

- [x] **#4 — Missing __init__.py in network/middlewares/**
  `lisp/plugins/network/middlewares/`
  Directory exists but has no `__init__.py`. Import of `RequireJSONMiddleware` will crash the Network plugin on load.

### Medium

- [x] **#10 — Crossfade mutates child fade durations permanently**
  `lisp/plugins/action_cues/group_cue.py:300-318`
  `_check_crossfade` sets `child.fadeout_duration` and `next_child.fadein_duration` as persistent Property values that get serialized to the session file.

- [x] **#11 — ExclusiveManager holds lock while iterating cue_model**
  `lisp/core/exclusive_manager.py:44-49`
  Fragile pattern. If cue state access triggers callbacks that also acquire the lock, deadlock occurs. Should copy the model list outside the lock.

- [x] **#12 — Notification toast _slide_out stacks signal connections**
  `lisp/ui/widgets/notification.py:246`
  Rapid dismiss calls stack `_anim.finished.connect()` without disconnecting previous connections, leading to double-hide.

- [x] **#13 — Test harness accesses private _CueFactory__registry**
  `lisp/plugins/test_harness/handlers.py:56`
  Uses Python name-mangling to access a private attribute. Fragile — breaks if CueFactory renames the internal attribute.

- [x] **#14 — Test harness layout selection accesses private _view.listView**
  `lisp/plugins/test_harness/handlers.py:~673`
  Accesses `app.layout._view.listView` and `app.layout._set_selection_mode`, which are private ListLayout internals. Crashes for CartLayout.

- [x] **#15 — wait_for race: notify.clear() after wait() can lose events**
  `lisp/plugins/test_harness/signal_manager.py`
  Between `wait()` return and `clear()`, a new event can arrive and be lost. Adds up to 100ms latency per missed notification.

- [x] **#16 — _disconnect_all_children duplicates logic from _disconnect_child**
  `lisp/plugins/action_cues/group_cue.py:236-267`
  Inline disconnect logic duplicates `_disconnect_child`. If a new signal is added to `_connect_child`, it must be updated in three places.

## Pre-existing Issues (before 483e904)

- [ ] **#5 — RequireJSONMiddleware crashes on None content_type**
  `lisp/plugins/network/middlewares/require_json.py:12`
  `req.content_type` can be `None` when no Content-Type header is provided. The `in` operator on `None` raises `TypeError`.

- [ ] **#6 — Network API CueActionEndPoint crashes on empty body**
  `lisp/plugins/network/api/cues.py:62`
  `request.get_media()` can return `None`, and `.get("action")` on `None` raises `AttributeError`.

- [ ] **#7 — OSC server thread not joined on stop()**
  `lisp/plugins/osc/osc_server.py:122-129`
  Thread is never joined after shutdown. Old thread may still be running when a new server starts.

- [ ] **#8 — ArtNet timecode build_packet no bounds clamping**
  `lisp/plugins/timecode/protocols/artnet.py:75-89`
  No bounds clamping on frames/seconds/minutes/hours. Bad durations could overflow.

- [ ] **#9 — 3 plugins use terminate() instead of finalize()**
  `lisp/plugins/rename_cues/rename_ui.py`, `lisp/plugins/replay_gain/replay_gain.py`, `lisp/plugins/network/network.py`
  `PluginsManager.finalize_plugins()` calls `finalize()` but these still define `terminate()`, so shutdown logic is silently skipped.
