# Action cues

Actions cues allows to control other cues status or parameters.

## Group Cue

This cue groups other cues together, providing two playback modes. Child cues are visually indented in the list layout and are triggered by the group rather than by the GO button.

To create a group, select multiple cues in the list layout, then right-click and choose **Group selected**. To dissolve a group, right-click the group cue (or any of its children) and choose **Ungroup**.

### Options (Group Settings)

* **Mode:**
    * *Parallel:* Start all children simultaneously. The group remains running until the last child ends.
    * *Playlist:* Play children sequentially, one after another. Designed for pre-show/intermission music.
* **Crossfade:** *(Playlist mode only)* Crossfade duration in seconds between consecutive tracks. When the current child has this much time remaining, the next child starts with a fade-in while the current one fades out.
* **Loop:** *(Playlist mode only)* When the last child finishes, loop back to the first child.

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

This cue simply stop all the running cues,
the "stop" action can be configured via the **Stop Settings** tab in the cue edit dialog.

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