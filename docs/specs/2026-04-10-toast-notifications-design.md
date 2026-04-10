# Toast Notification System

## Context

LiSP has two feedback channels for runtime messages: a status bar log line
(ephemeral, easy to miss) and modal error dialogs (blocks the entire UI).
There's nothing in between for messages that need to gently interrupt the
operator without stopping them from working. The most visible gap is
`ExclusiveManager`, which silently logs "Blocked by exclusive cue" to the
status bar where the operator may never notice it.

This design adds a non-modal toast overlay that appears top-center over the
layout area, auto-dismisses after a few seconds, and supports two severity
tiers: Info and Warning.

## Design Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Position | Top-center of layout area | Visible but not blocking controls |
| Modality | Non-modal overlay | Must not interrupt a live show |
| Severity tiers | Info (4s) + Warning (6s) | Errors stay as modal dialogs; they need acknowledgement |
| Deduplication | Same message resets timer, shows "(xN)" count | Prevents visual noise under rapid-fire events |
| Animation | Slide down/up via QPropertyAnimation on pos | Lightweight; avoids opacity which is costly on some Linux compositors |
| Wiring | `Application.notify` Signal | Explicit control over what's notification-worthy vs. just a log entry |
| Different-message replacement | New message replaces current toast immediately | Low-frequency system; queuing adds complexity for no benefit |

## Architecture

### Widget: `NotificationToast`

**New file:** `lisp/ui/widgets/notification.py`

`NotificationLevel` enum: `Info`, `Warning`.

`NotificationToast(QFrame)`:
- Parented to `MainWindow.centralWidget()` (persists across session changes)
- Created eagerly in `MainWindow.__init__`, hidden by default
- Positions itself top-center; recalculates via `eventFilter` on parent
  `QEvent.Resize`
- `setProperty("level", "info"/"warning")` + `unpolish/polish` for QSS
  re-evaluation (same pattern as `ListTimeWidget`)
- `QTimer` for auto-dismiss countdown
- `QProgressBar` (thin, 2px) shows remaining time visually
- `mousePressEvent` dismisses immediately
- `adjustSize()` + reposition after dedup count changes

Layout within the toast frame:
- Icon label (left)
- Message label + optional "(xN)" count (center)
- Progress bar (bottom, spanning full width)

Dedup state:
- `_current_message: str` — text of the currently displayed notification
- `_current_count: int` — how many times this message has been emitted
- On `show_notification(message, level)`:
  - If message matches `_current_message`: increment count, update label,
    reset timer
  - Otherwise: replace text, reset count to 1, restart timer and animation

Animation handling:
- If dismiss animation is in progress when a new notification arrives:
  `QPropertyAnimation.stop()`, snap to shown position, update content

### Signal: `Application.notify`

**Modified file:** `lisp/application.py`

```python
self.notify = Signal()  # args: (message: str, level: NotificationLevel)
```

### Connection: `MainWindow`

**Modified file:** `lisp/ui/mainwindow.py`

```python
self._notification_toast = NotificationToast(self.centralWidget())
self._app.notify.connect(
    self._notification_toast.show_notification, Connection.QtQueued
)
```

`Connection.QtQueued` ensures thread safety: producers in worker threads
post to the Qt event loop via `QApplication.postEvent()`, which is
thread-safe. Events posted before `qt_app.exec()` (e.g., during plugin
loading) are queued and delivered once the event loop starts. This is the
same pattern `CacheManager` already relies on.

### Theme

**Modified file:** `lisp/ui/themes/dark/theme.qss`

```css
#NotificationToast {
    border-radius: 6px;
    font-size: 13px;
}

#NotificationToast[level="info"] {
    background: #404858;
    border: 1px solid #5a6a80;
    color: #c8d0dc;
}

#NotificationToast[level="warning"] {
    background: #504030;
    border: 1px solid #806830;
    color: #e0c880;
}

#NotificationToastProgress {
    /* Thin progress bar inside the toast */
}

#NotificationToastProgress[level="info"]::chunk {
    background: #80AAD5;
}

#NotificationToastProgress[level="warning"]::chunk {
    background: #FFAA00;
}
```

### Producers

All producers **keep their existing logging calls** and add a
`notify.emit()` alongside.

**1. ExclusiveManager** (`lisp/core/exclusive_manager.py`)

Constructor changes from `ExclusiveManager(cue_model)` to
`ExclusiveManager(app)` (derives `cue_model` from `app.cue_model`).
Wiring change in `Application.__init__`.

In `is_start_blocked()`, after the existing `logger.info(...)`:
```python
self._app.notify.emit(message, NotificationLevel.Info)
```

**2. CacheManager** (`lisp/plugins/cache_manager/cache_manager.py`)

Replace `QMessageBox.warning(...)` in `_show_threshold_warning` with:
```python
logger.warning(message)
self.app.notify.emit(message, NotificationLevel.Warning)
```

Remove the `threshold_warning` Signal, `_show_threshold_warning` method,
and `Connection.QtQueued` bridge — the toast system handles thread-safe
delivery.

**3. GstWaveform failures** (`lisp/plugins/gst_backend/gst_backend.py`)

Do NOT pass `app` into `GstWaveform` or the `Waveform` base class.
Instead, connect at the `GstBackend` level where the waveform is created:

```python
# In GstBackend.uri_waveform():
waveform = GstWaveform(uri, duration, cache_dir=...)
waveform.failed.connect(
    lambda: self.app.notify.emit(
        f'Cannot generate waveform for "{uri.unquoted_uri}"',
        NotificationLevel.Warning
    )
)
return waveform
```

The existing `logger.warning` in `GstWaveform._on_bus_message` stays.

**4. PluginsManager** (`lisp/core/plugins_manager.py`)

After existing `logger.error(...)` / `logger.exception(...)` calls during
plugin loading, emit:
```python
app.notify.emit(message, NotificationLevel.Warning)
```

Notifications emitted before the event loop starts are queued by
`postEvent` and delivered once `qt_app.exec()` begins.

## Edge Cases

| Scenario | Handling |
|---|---|
| Session finalized while toast visible | Toast is parented to `centralWidget()`, not the layout view. Survives session transitions. |
| No session active yet | `MainWindow` and `centralWidget()` exist before any notifications can fire. |
| `Application.finalize()` called | Event loop is already stopped at this point; no queued events will be processed. Safe. |
| Rapid same-message notifications | Dedup: increment count, reset timer. |
| Different message while toast showing | Replace immediately: cancel timer, update content, reset animation. |
| Dismiss animation in progress + new notification | `QPropertyAnimation.stop()`, snap to shown position, update. |
| Toast text grows from dedup count | `adjustSize()` + `_reposition()` after label update. |
| Window resize while toast visible | `eventFilter` on `centralWidget()` catches `QEvent.Resize`, calls `_reposition()`. |

## Files Modified

| File | Change |
|---|---|
| `lisp/ui/widgets/notification.py` | **New.** `NotificationLevel` enum + `NotificationToast` widget. |
| `lisp/application.py` | Add `notify` Signal. Change `ExclusiveManager` construction to pass `app`. |
| `lisp/ui/mainwindow.py` | Create toast widget, connect to `app.notify`. |
| `lisp/ui/themes/dark/theme.qss` | Add toast styling rules. |
| `lisp/core/exclusive_manager.py` | Accept `app` instead of `cue_model`. Emit notification. |
| `lisp/plugins/cache_manager/cache_manager.py` | Replace `QMessageBox` modal with toast + logger.warning. |
| `lisp/plugins/gst_backend/gst_backend.py` | Connect waveform.failed to notification in `uri_waveform()`. |
| `lisp/core/plugins_manager.py` | Emit notification on plugin load failures. |

## Verification

### Unit Tests

Test `NotificationToast` in isolation using `pytest-qt` with the existing
`mock_app` fixture pattern:
- Show notification, verify widget is visible
- Show same message twice, verify dedup count updates to "(x2)"
- Show different message while one is visible, verify text replacement
- Verify timer reset on dedup

### E2E Tests (test harness)

Use the existing test harness signal subscription system to verify
notifications end-to-end. `Application.notify` is a standard LiSP Signal,
so `signals.subscribe` / `signals.wait_for` work with zero harness changes.

Test cases:
1. **Exclusive cue blocking:** Add two cues, mark one exclusive, start it,
   attempt to start the other via `cue.execute`. Subscribe to `app.notify`
   and `wait_for` the blocked notification.
2. **Deduplication:** Rapidly trigger the same blocked-start scenario
   multiple times. Verify only one notification is active (the signal fires
   each time, but the toast deduplicates — the E2E test verifies the signal
   emissions, the unit test verifies the dedup behavior).

### Manual Verification

1. Set cache threshold to 0 MB, restart LiSP — verify warning toast appears
   instead of modal dialog.
2. Point a MediaCue at a non-existent file — verify waveform failure toast.
3. Show a toast, resize the window — verify it stays centered.
4. Click a toast — verify it dismisses immediately.
