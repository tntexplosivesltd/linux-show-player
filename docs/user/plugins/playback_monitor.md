# Playback Monitor

The Playback Monitor is a standalone, resizable window that displays the elapsed and remaining
time of the most recently started cue. It is designed to be enlarged and placed on a secondary
monitor so the whole production booth can read it at a glance — useful for calling out cue
points at specific timestamps (e.g. "change to red at 1:21").

## Enabling the Plugin

The Playback Monitor plugin is disabled by default. To enable it:

1. Open `File > Preferences > Plugins`
2. Tick the checkbox next to **Playback Monitor**
3. Restart LiSP

Once enabled, the plugin adds an entry to the **Tools** menu and registers a keyboard shortcut.

## Opening the Window

* **Menu:** `Tools > Playback Monitor`
* **Shortcut:** ``[CTRL+SHIFT+M]``

Triggering the shortcut or menu entry when the window is already open brings it to the front.
Triggering it again closes the window.

## Display

The window shows three elements stacked vertically:

1. **Cue name** — the name of the currently tracked cue (shown at the top)
2. **Elapsed time** — large `MM:SS` display with an "Elapsed" sub-label
3. **Remaining time** — large `MM:SS` display with a "Remaining" sub-label

All text scales proportionally when the window is resized, making it readable from across
a production booth.

When nothing is playing, the times show `00:00` and the cue name area shows "—".
For cues with no known duration (indefinite cues), the remaining time shows `--:--`.

Time format is `MM:SS` for cues under one hour, and `HH:MM:SS` for longer cues.
No fractional seconds are shown.

## Cue Tracking

The monitor automatically tracks the **most recently started cue**. When any cue in the
session starts playing, the monitor switches to display that cue's name and time.

When the tracked cue stops, the display **freezes** at the final values rather than
resetting to zero. This allows the operator to see where playback ended. The display
resets only when a new cue starts or the session changes.

## Always on Top

By default, the window stays on top of other windows. This can be toggled via the
window's right-click context menu:

* **Right-click** the window → **Always on Top** (checkable)

## Window Geometry

The window's position and size are saved automatically when it is closed and restored
the next time it is opened. This persists across sessions.

## Session Behaviour

The monitor window persists across session load/new/close operations. When the session
changes, the display resets to the idle state (showing "—" and `00:00`).
