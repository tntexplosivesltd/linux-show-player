# Screenshot capture punch list

Nine placeholders left behind by the user-doc passes. Each is marked
inline in the source as `[screenshot: …]` so a `grep -rn '\[screenshot:'`
in `docs/user/` will find them all.

## `docs/user/editing_cues.md` (4)

| # | Suggested filename | Capture |
|---|---|---|
| 1 | `inspector_overview.png` | Main window showing the cue layout on top and the inspector panel below, with a cue selected and its General page visible. *Note*: line 7 already contains a real `{image}` block pointing at this filename — the placeholder at line 11 is descriptive duplication. Either drop the placeholder text when you replace it, or use the alternative framing for variety. |
| 2 | `inspector_single_cue.png` | Inspector bound to a single Media Cue, showing the General page (name, description, fades, exclusive, enabled) |
| 3 | `inspector_multi_cue_mixed.png` | Inspector in multi-cue mode with at least one mixed-value indicator visible (e.g. on a Fade In duration field) |
| 4 | `inspector_multi_cue_apply.png` | Multi-cue mode with one settings group's title checkbox ticked and another unticked, showing the per-group apply pattern |

## `docs/user/cues/index.md` (2)

| # | Suggested filename | Capture |
|---|---|---|
| 5 | `cue_color_picker.png` | Appearance section of the inspector with the fixed-palette colour picker open (the named-swatch grid) |
| 6 | `disabled_cue_list.png` | Enabled checkbox in the inspector, alongside a list-layout view showing one disabled cue rendered dimmed |

## `docs/user/cues/action_cues.md` (2)

| # | Suggested filename | Capture |
|---|---|---|
| 7 | `fade_stop_settings.png` | Fade & Stop Settings page in the inspector showing Target, Action and Fade groups. Capture with the Action dropdown open so the *Hibernate* option is visible — it's the most novel thing on the page and the likeliest thing a reader is looking for visual confirmation of. |
| 8 | `fade_resume_settings.png` | Fade & Resume Settings page in the inspector showing Target and Fade groups |

## `docs/user/cues/media_cues.md` (1)

| # | Suggested filename | Capture |
|---|---|---|
| 9 | `media_cue_waveform_trimmer.png` | Media Cue settings page in the inspector with the waveform trimmer visible and start/stop handles dragged partway through the file |

---

## When you do the capture pass

For each placeholder, replace the `[screenshot: …]` line with the
standard MyST image block the rest of the docs already use:

````markdown
```{image} ../_static/<filename>.png
:alt: <descriptive alt text>
:align: center
```
````

For `editing_cues.md` the path prefix is `_static/<filename>.png` (one
fewer `../` because the file lives at the docs/user root, not under
`cues/`).

Drop the captured `.png` files into `docs/user/_static/`.

## Naming convention

Filenames follow the existing `_static/` pattern — snake_case,
feature-prefixed. Examples already in the tree:

* `list_layout_main_view.png`
* `cart_layout_settings.png`
* `media_cue_options_tab.png`
* `volume_control_cue_options.png`

Match this style for new captures so future grep / find by feature
name keeps working.
