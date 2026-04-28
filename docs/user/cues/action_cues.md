# Action cues

Actions cues allows to control other cues status or parameters.

## Group Cue

This cue groups other cues together, providing two playback modes. Child cues are visually nested under the group in the list layout and are triggered by the group rather than by the GO button.

To create a group, select multiple cues in the list layout, then right-click and choose **Group selected**. To dissolve a group, right-click the group cue (or any of its children) and choose **Ungroup**.

### Collapsible Groups (List Layout)

In the list layout, groups can be collapsed and expanded by clicking the arrow next to the group name. This hides or reveals the child cues, keeping the cue list tidy during complex shows.

* **Collapse/expand a group:** Click the expand arrow on the group row
* **Collapse all groups:** `Layout > Collapse all groups` or ``[CTRL+SHIFT+[]``
* **Expand all groups:** `Layout > Expand all groups` or ``[CTRL+SHIFT+]]``
* **Auto-expand on play:** When a group starts playing, it automatically expands to show its children (configurable in layout settings)
* **Persistent state:** Collapse/expand state is saved with the session

### Options (Group Settings)

* **Mode:**
    * *Parallel:* Start all children simultaneously. The group remains running until the last child ends.
    * *Playlist:* Play children sequentially, one after another. Designed for pre-show/intermission music.
* **Crossfade:** *(Playlist mode only)* Crossfade duration in seconds between consecutive tracks. When the current child has this much time remaining, the next child starts with a fade-in while the current one fades out.
* **Loop:** *(Playlist mode only)* When the last child finishes, loop back to the first child.
* **Shuffle:** *(Playlist mode only)* Randomize the order of children when the option is toggled on, and again each time the session is loaded. Useful for pre-show music playlists where you want a different running order each performance. The shuffled order is visible in the cue list. Once set, the order stays stable for the duration of the show — starting, pausing, resuming, and looping all preserve the current order.

### Behavior

| Action | Parallel | Playlist |
|---|---|---|
| **Start** | Starts all children | Starts first child |
| **Stop** | Stops all running children | Stops current child |
| **Pause** | Pauses all running children | Pauses current child |
| **Interrupt** | Interrupts all running children | Interrupts current child |

In playlist mode, when a child ends naturally the next child starts automatically. If a child is manually stopped or interrupted, the entire group stops.

## Collection Cue

This cue allow to tigger multiple cues at once, for each cue a different action can be specified.<br>
The execution is instantaneous, it doesn't keep track of the status of triggered cues.

### Options (Edit Collection)

```{image} ../_static/collection_cue_options.png
:alt: Collection cue options
:align: center
```

You can Add cues to the collection via the `Add` button, and remove the selected one with the `Remove` button.
To edit a value (Cue, Action) `Double-Click` on it.

## Stop All

This cue simply stops all the running cues. The "stop" action is
configured on the **Stop Settings** page in the [inspector](../editing_cues.md).

## Fade & Stop

Stops a single target cue with an optional fade. Use this when a
specific cue should ramp down rather than stop instantly.

If the cue has no name set, its display name is derived automatically
from its target and chosen action — e.g. *Stop "Music"*, *Pause "VO 1"*.

### Options (Fade & Stop Settings)

* **Target:** The cue to act on. Click *Click to select* to choose; the
  current target is shown next to the button.
* **Action:** What to do once the fade completes:
    * *Stop* — stop the target.
    * *Pause* — pause the target. The target can be resumed later.
    * *Hibernate* — pause the target and tag it as *hibernating*. The
      cue stays in the playing panel (rendered compactly and dimmed)
      so it can be brought back later. Resuming or stopping the cue
      clears the tag automatically. If the target is a Group Cue, the
      hibernation cascades to its running children.
    * *Interrupt* — stop the target "quietly" (no Stop fade).
* **Fade:**
    * **Duration:** Fade duration in seconds (0 to dispatch the action
      instantly with no fade).
    * **Curve:** Fade curve.

[screenshot: Fade & Stop Settings page in the inspector showing Target, Action and Fade groups]

## Fade & Resume

Resumes a single target cue with an optional fade. Pairs with
Fade & Stop for time-based pause/resume workflows.

If the cue has no name set, its display name is derived automatically
from its target — e.g. *Resume "Music"*.

The cue dispatches different behaviours based on the target's state:

* **Paused** — dispatches *Resume* and fades the volume up to its
  previous level.
* **Hibernating** — same as Paused, with the *hibernating* tag cleared
  on resume.
* **Running** — fades the volume up from its current level (no
  *Resume* action is needed; the cue is already playing).
* **Stopped / Error** — Fade & Resume reports an error and does
  nothing.

### Options (Fade & Resume Settings)

* **Target:** The cue to resume. Click *Click to select* to choose;
  the current target is shown next to the button.
* **Fade:**
    * **Duration:** Fade-in duration in seconds (0 to resume instantly
      with no fade).
    * **Curve:** Fade curve.

[screenshot: Fade & Resume Settings page in the inspector showing Target and Fade groups]

## Seek Action

This cue allow to seek a media-cue to a specific point in time.

### Options (Seek Settings)

* **Cue:** The target media-cue (can be changed via the button labelled `Click to select`)
* **Seek:** The point in time to reach

## Volume Control

This cue allows to trigger a volume change or fade-in/out on a selected media-cue.  

### Options (Volume Settings)

```{image} ../_static/volume_control_cue_options.png
:alt: Volume Control cue options
:align: center
```

* **Cue:** The target media-cue (can be changed via the button labelled `Click to select`)
* **Volume:** The volume to reach (in % or dB)
* **Fade:** Fading options
    * **Duration:** Fade duration in seconds (0 to disable fade)
    * **Curve:** The fade curve

## Index Action

This cue triggers another cue in a specific position (index) in the layout.

### Options (Action Settings)

```{image} ../_static/index_action_cue_options.png
:alt: Index Action cue options
:align: center
```

* **Index**
    * **Use a relative index:** When toggled the position is considered relative to the
      current cue position
    * **Target index:** The position of the target (the UI will enforce a valid index)
* **Action:** The action to execute
* **Suggested cue name:** you can copy this value and use it as the cue name