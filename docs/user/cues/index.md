# Cues

Cues are the main component of every show/session.

There are multiple types of cues, able to perform different tasks, we can organize them in the following categories:

* **Media cues:** used to play multimedia contents
* **Action cues:** used to trigger/alter other cues (includes Group Cue for parallel/playlist grouping)
* **Integration cues:** used to interact with external devices or application via common protocols
* **Misc cues:** cues that don't fit in others categories

```{toctree}
:hidden:
:titlesonly:

media_cues
action_cues
integration_cues
misc_cues
```

## Cue states

A cue can be in different **states**:

![stop](../_static/icons/led-off.svg){.align-middle} **Stop:** the default state, the cue is ready to be started<br>
![running](../_static/icons/led-running.svg){.align-middle} **Running:** the cue is running (e.g. audio is playing)<br>
  **Pre wait:** waiting before the task is stared<br>
  **Post wait:** waiting after the task has been completed<br>
![paused](../_static/icons/led-pause.svg){.align-middle} **Paused:** the cue has been paused (e.g. audio paused)<br>
  **Pre wait:** the pre-wait has been paused<br>
  **Post wait:** the post-wait has been paused<br>
**Hibernating:** the cue is paused and tagged as *hibernating* — see [Fade & Stop](action_cues.md#fade--stop) for how this state is entered. Resuming or stopping the cue clears the hibernating tag automatically.<br>
![error](../_static/icons/led-error.svg){.align-middle} **Error:** some error has occurred on the cue (e.g. audio file missing)

Some cue will run its task instantaneously, for those cues the "running" state will be imperceptible.

## Cue actions

A cue can perform different **actions** depending on its type and current state

* **Default:** Depending on its state and configuration the cue will choose which action to perform
* **Start:** Perform the cue task
* **Resume:** Resume a paused cue
* **Stop:** Stop the running cue
* **Pause:** Pause the running cue
* **Interrupt:** Stop the running cue "quietly"
* **Loop Release:** The cue will stop looping (until restarted) but will play util its end
* **Fade:** Decrease/Increase gradually a cue parameter (e.g. volume)

The Start, Resume, Stop, Paused and Interrupt action all have a "faded" variant that will cause a fade-in/out.

## Cues options

All cues share a set of options, here we'll cover the basic settings, more advanced ones will have their own sections.

Options are edited in the [inspector](../editing_cues.md), grouped into pages such as **General**, **Pre/Post wait** and (for media cues) **Media**:

```{image} ../_static/cue_options_tabs.png
:alt: Inspector pages
```

### Appearance

Visual options *(some of them can be ignored by the layout)*

* **Cue name:** The name that identify the cue
* **Description/Note:** A text for writing notes about the cue, interpreted as [Markdown](https://github.github.com/gfm/).

```{note}
To insert a new line in **Description/Note**, you need to insert a blank line, or add a "\\\\" at the end of the line.

line1

line2

--or--

line1\\\\\
line2
```

* **Font size:** The font used to display the name
* **Font color:** The color of the font used to display the name
* **Background color:** The background color of the cue. Pick from a fixed palette of named colours (`Red`, `Orange`, `Yellow`, …) — the chosen colour adapts automatically to the active theme. A *No colour* swatch clears the cue's colour.

[screenshot: Appearance section of the inspector with the fixed-palette colour picker open]

### Cue

General options for the cue, this section is organized the following sub-tabs:

### Behaviors

Define the _default_ actions used by the cue

* **Start:** Action used when cue is "stopped"
* **Stop:** Action used when the cue is "running"

### Pre/Post Wait

* **Pre wait:** Add a delay before the cue is started
* **Post wait:** Delay before `Next action` is executed
* **Next action:** What to do after `Post wait`
    * _Do Nothing:_ You know ...
    * _Trigger after post wait:_ Execute the next cue when `post wait` ends 
    * _Trigger after the end:_ Execute the next cue when the current cue ends
    * _Select after post wait:_ Select the next cue when `post wait` ends 
    * _Select after the end:_ Select the next cue when the current cue ends

```{warning}
Given its non-sequential nature, the _Cart Layout_ does not support the “Next action” setting.
```

### Fade In/Out

* **Fade In:**
    * **Duration:** How long the fade should last before reaching a maximum value
    * **Curve:** How the value should increase in time
* **Fade Out:**
    * **Duration:** How long the fade should last before reaching a minimum value
    * **Curve:** How the value should decrease in time

### Exclusive

Exclusive mode prevents overlapping **media** playback. When a media
cue with exclusive mode enabled is running, other media cues are
blocked from starting until it stops.

* **Exclusive:** When checked, this cue will block other media cues
  from starting while it is running. Other running media cues are
  also prevented from starting when any exclusive media cue is
  active.

Non-media cues — Action, Integration, Misc — are not affected by
exclusive mode and can still run alongside an exclusive media cue.

This is useful when overlapping playback would cause problems — for
example, ensuring only one background music track plays at a time, or
preventing sound effects from overlapping with announcements.

### Enabled

Cues can be temporarily disabled without removing them from the show.

* **Cue is enabled:** When unchecked, the cue is skipped by `GO`,
  by *next-action* / *trigger-after* chains, by standby advance, and
  by group playback (Parallel and Playlist).
* Disabling a **Group Cue** cascades to every child — disabled groups'
  children are also skipped.
* Disabling a cue mid-playback does not interrupt the cue that is
  already running; the next attempt to start it will be skipped.
* In the layout, disabled cues are rendered dimmed so the *enabled*
  set of the show is visible at a glance.

[screenshot: Enabled checkbox in the inspector, plus a list-layout view showing one disabled cue rendered dimmed]

## Editing multiple cues

Select a range of cues and edit them together in the
[inspector](../editing_cues.md). Only the options shared by every
selected cue are shown; fields whose values differ across the
selection are flagged with a mixed-value indicator. Each settings
group has its own *apply to all* checkbox so you can change one
group of properties without disturbing the others.

```{note}
You can select all cues at once using `Edit > Select All` `[CTRL+A]`,
or toggle multi-selection from the layout menu with
`Layout > Selection mode` `[CTRL+SHIFT+E]`.
```
