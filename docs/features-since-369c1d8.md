# Features delivered since `369c1d8`

**Span**: 2026-04-10 → 2026-07-05 (~12 weeks)
**Commits**: 429 since `369c1d8e61fa3b4f921cf987859f8d61915fd619`
**Merged feature branches**: 22 (plus the inspector overhaul, which
landed directly on master); 30 merges total once fix and docs passes
are counted.

This list covers user-facing features only. Pure fixes, refactors,
spacing/alignment polish, spec/plan documents, and i18n updates are
omitted — see `git log 369c1d8..HEAD` for the full record.

---

## Inspector & cue settings overhaul

Landed directly on master, roughly Apr 10–14.

- **Persistent inspector panel** — vertical splitter with multi-cue
  mixed-value rendering, replacing the modal cue-settings dialog as
  the primary editing surface.
- **Live commit-and-diff editing engine** — edits flush automatically,
  with a `commit_requested` signal for modal-driven edits.
- **Compact 3-column QLab-style General page** with reorganised
  columns (behaviour/identity swap, fades grouped, icon merged into
  the change button).
- **Cue-settings tabs reorganised** — Appearance / Behaviour / Fade /
  Exclusive merged into the General page; Timing and Media Cue tabs
  brought in line.
- **Fixed-palette colour picker** (QLab-style) replacing the freeform
  picker.
- **Cue colour stripe** shown on the running-cue widget in the list
  layout.

## New cue types — the SFR (Stop / Fade / Resume) workflow

### Fade & Stop cue (Part 1)
- New `StopCue` type that drives a parallel fade across affected
  faders, then dispatches the configured action.
- Cooperative abort on stop/interrupt.
- New `ParallelFadeRunner` and `_fader_coordinator` infrastructure
  shared with Resume.

### Fade & Resume cue (Part 2)
- New `ResumeCue` type that dispatches by target state, with a
  running-target fallback that fades up with no Resume.
- Zero-fades the target then ramps up; errors on Stopped/Error
  targets.
- Resolves `target_id` and errors on missing target.

### SFR workflow polish
- **Auto-derived names** for SFR cues from their target + action.
- **Purpose-built icons** for both Fade & Stop and Fade & Resume.

## Hibernating cue state (Part 3 of SFR)

- New **Hibernating bit** composing with Pause, with `hibernated` /
  `awoken` signals and auto-clear on pause-exit transitions.
- **Stop cue Hibernate action** — runtime hibernate dispatches Pause
  and flips the bit; cascades across `GroupCue` children.
- **Compact dimmed widget** in the playing panel for hibernated cues.
- Dedicated **hibernating status icon variant** (cool blue `#5AF`).

## Disable cues (without removing them)

- New **`disabled` property** with an `effective_disabled` cascade
  through groups.
- **Inspector Enabled checkbox** on the General page.
- **Execution gated** on `effective_disabled` — disabled cues are
  skipped by the next-action chain, standby advance, and `GroupCue`
  parallel/playlist modes.
- **Dimmed rendering** — list-layout rows and cart-layout cells
  visually dim when disabled.

## Cue volume indicator

- New **`VolumeIndicatorLabel`** widget rendering live dB next to
  running cues.
- **Live updates** wired through `CueTime.notify`.
- **Per-cue settings checkbox** + **layout-menu toggle** for
  visibility.
- Test-harness endpoints added for E2E coverage.

## Group improvements

- **Collapsible groups** in the list layout.
- **Coloured outlines** drawn around groups in the list layout, with
  viewport invalidation on mode/expand changes.
- **Exclusive mode scoped to media-only** — only blocks other media
  cues from starting (videos and similar no longer suppress unrelated
  cues).

## Media Cue waveform trimmer

- **Visual waveform** mounted in the Media Cue inspector via the live
  cue + GStreamer backend, with a timeline fallback on waveform
  failure.

## Icons

- **Image cue icon** with realigned media-cue defaults.
- Refactored base icons and recolouring code path so cue icons
  participate in the colour system.

## Testing infrastructure

- **14 E2E test suites** in the initial drop, since expanded
  substantially (the suite is now ~38 files).
- **Test Harness `inspector.*` namespace** for driving inspector
  edits over JSON-RPC.
- **Testing guide** at `docs/testing.md` covering the unit/E2E split,
  harness extension, and signal-wait patterns.

---

# Second wave (May 2–3)

A cluster of seven feature branches merged over two days, dominated by
a theming overhaul and a media pre-load system.

## Media pre-load / pre-arm

- New **`MediaCue.preload` property** and a **`PreArmManager`** that
  warms eligible cues' GStreamer pipelines ahead of GO, with a
  cap-enforced arm/disarm lifecycle and batch-coalesced failure
  notifications.
- **mtime-based invalidation** and session-teardown cleanup so a
  changed or removed source re-arms correctly.
- **Preload checkbox** on the media cue settings page (gated via
  flat-group in multi-select).
- **Pre-arm indicator dot** in the list-layout row margin, with a
  hit-tested tooltip.
- New **`standby_changed`** layout signal and **`pre_arm.*`
  test-harness namespace** (`status`, `wait_for_armed`) for E2E
  coverage.

## Theming — Light, System, Solarized & live switching

- **Real Light theme** (replacing the stub) plus a **System
  pass-through theme** that follows the desktop palette.
- **Solarized Light and Dark** themes.
- **Live theme switching** via a new `theme_changed` signal — no
  restart required.
- **Theme-aware icons** — grayscale SVG fills invert per theme and
  themed icons scale to any requested size.
- **Name-keyed cue colour palette** with theme-aware hex resolution
  (`color_name` property), replacing raw hex storage while preserving
  legacy custom hex on save, plus **theme-controlled cue-colour alpha**
  and a themeable **standby indicator**.

## Nested group cues

- **`GroupCue`s can now be nested** inside other groups (grouping
  selection accepts groups).
- **Ungroup promotes children to the grandparent**, not to top level;
  removing a group promotes its children's `group_id` accordingly.
- **List-view rendering made depth-aware** — group outlines span nested
  expanded descendants, the status-icon column auto-sizes to nesting
  depth, and nested groups insert/reparent under the correct parent.
- Runtime **stop/disable cascades** verified across nested levels.

## Static cue numbers

- New **static `cue_number` identifier** (QLab-style "Q#"), independent
  of a cue's row position.

## Invalid-target warnings

- New **`TargetingCue` mixin** tracking whether a cue's target still
  resolves, inherited by Stop, Resume, Seek, Volume, and Collection
  cues (with list semantics for Collection).
- **Invalid-target badge** on the list-layout status icon and the
  cart-layout cue widget (custom-painted), plus a **`TargetWarningRow`**
  summary in each affected inspector page — all reactive to target
  add/remove.

---

## Notes on the delivery process

Two delivery shapes are visible in the history:

- The inspector overhaul (Apr 10–14) landed as a series of small
  commits directly on master, with no merge commits — `git log
  --first-parent` shows them inline.
- Later work (Apr 14 onward) shifted to per-feature branches with
  `--no-ff` merges, which is why `git log --merges 369c1d8..HEAD`
  cleanly enumerates the deliveries.
- The May 2–3 second wave kept the same per-branch `--no-ff` shape but
  bundled tightly: seven branches in ~36 hours, most carrying their own
  QA + code-review follow-up commits.

From ~May 10 onward the work turned to **video-pipeline hardening** —
three branches (`fix/uri-av-input-silent-eos-race`,
`fix/video-sink-stale-frame-bleedthrough`,
`fix/video-playlist-first-transition-flicker`). These are pure fixes,
so they're omitted from the feature list above, but they represent the
bulk of the June–July commit volume and are documented under
`docs/bugs/`.

The SFR cue family is the thematic centrepiece — Stop, Resume, and
Hibernate were always one workflow split into three deliverable
parts, which is why hibernate cascade lives inside the stop-cue path
and why both new cue types share `ParallelFadeRunner` and the
auto-derived-name behaviour.
