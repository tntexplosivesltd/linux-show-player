1. Creating Groups

- Group via context menu: Enable selection mode (Ctrl+Alt+S), select 3 cues, right-click → "Group selected". A bold "Group Cue" row should appear above the selected cues, and the children should show indented names.
- Group single cue: Right-click one cue → "Group selected". Should create a group with one child.
- Group icon: The group row should show a folder icon, not the default LED.
- Undo group (Ctrl+Z): The group cue disappears, children return to normal (no indent, no bold).
- Redo group (Ctrl+Shift+Z): Same group cue reappears (same position).

2. Ungrouping

- Right-click the GroupCue → "Ungroup". Group disappears, children become top-level (no indent).
- Undo the ungroup — group reappears in the correct position with children re-indented.

3. Parallel Mode (default)

- Select the GroupCue, press GO. All children should start simultaneously.
- The group row icon should turn green (running state).
- When the last child finishes, the group should return to stopped state.
- While group is running, stop it (right-click → Stop or select and press GO again). All children should stop.

4. Playlist Mode

- Edit the GroupCue (Shift+Space or double-click), go to "Group Settings" tab, change mode to Playlist.
- Press GO on the group. Only the first child should start.
- When the first child ends, the second child should automatically start, and so on.
- The group stays Running until the last child finishes.
- Stop the group mid-playlist — the currently playing child should stop.

5. Playlist + Loop

- Enable "Loop" in group settings.
- Start the group. After the last child finishes, it should wrap back to the first child.
- Stop the group manually to exit the loop.

6. Playlist + Crossfade

- Set crossfade to e.g. 3.0 seconds, ensure children have enough duration (>5s each).
- Start the group. About 3 seconds before the current child ends, the next child should start playing (overlap).
- The current child should fade out as the next fades in.

7. GO Button Behavior

- Place standby cursor on a child cue (indented one). Press GO. It should skip to the next non-child cue (or the group itself if above).
- With auto-continue on, pressing GO on the GroupCue should advance the standby past the group and all its children.

8. Exclusive + Groups

- Mark a GroupCue as exclusive. Start it. Try to start another cue — it should be blocked.
- Mark a non-group cue as exclusive, start it, then try to start a GroupCue — the group should be blocked.

9. Save/Load

- Save the session with groups. Close and reopen the file. Groups, modes, crossfade settings, and child relationships should all be preserved.
- Children should still show as indented after reload.

10. Edge Cases

- Delete a child cue that belongs to a group — the group should still work with remaining children.
- Delete the GroupCue directly (not via Ungroup) — children become normal cues (no crash).
- Empty group (all children deleted) — starting it should do nothing (no crash).
- GroupCue with next_action set to "Trigger after end" — should chain to the next cue in the main list after the group finishes.

## Hibernation workflow (Part 3)

- [ ] Create a Fade & Stop cue, action=Hibernate, targeting a
      playing media cue. Trigger it — target fades, pauses, and
      renders dim/compact in the Playing panel.
- [ ] While target is hibernating, its status icon in the main cue
      list is the cool-blue `-hibernating` variant (not pause
      orange).
- [ ] Resume the target via spacebar — widget restores to full size
      and opacity; status icon reverts to running green.
- [ ] Resume via a Fade & Resume cue — same outcome.
- [ ] Session round-trip: hibernate a cue, save, reopen — cue is
      Stopped. Runtime-only behaviour confirmed.
- [ ] Target a GroupCue with Hibernate — every running child gains
      the hibernating icon. Resume one child (spacebar on that
      child) — only that child wakes; siblings stay hibernating.
- [ ] OSC/MIDI resume of a hibernated cue clears the flag.
- [ ] Multiple StopCues targeting the same cue — second firing is
      idempotent (no double hibernation, no state corruption).
- [ ] Cart layout: a hibernated cue shows the led-hibernating icon
      variant.
