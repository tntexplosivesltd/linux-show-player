# SFR-style Workflow Roadmap

Tracker for the three-part delivery of SCS-style SFR functionality in LiSP.
Each part gets its own brainstorming → spec → plan → implementation cycle.

## Part 1 — Fade & Stop cue — **complete**

Spec: [`2026-04-18-fade-and-stop-cue-design.md`](2026-04-18-fade-and-stop-cue-design.md)

Single-target cue that runs its own `live_volume` + `live_alpha` faders over
a user-specified duration, then dispatches `Stop` / `Pause` / `Interrupt`.
Group targets fan out via the existing `GroupCue` cascade.

- [x] Brainstorm design
- [x] Write spec
- [x] Write implementation plan
- [x] Implement `StopCue` + `StopCueSettings`
- [x] Unit tests
- [x] E2E test via `test_harness`
- [x] QA review (`voltagent-qa-sec:qa-expert`)
- [x] Code review (`voltagent-qa-sec:code-reviewer`)

Delivered on branch `feat/stop-cue`. Coordinator module
`lisp/plugins/action_cues/_fader_coordinator.py` landed as shared
infrastructure for Part 2. Two `&`-escape fixes in `mainwindow.py`,
`inspector/panel.py`, and `settings/pages.py` were centralised into
`ui_utils.escape_mnemonic`.

## Part 2 — Fade & Resume cue — **in progress**

Spec: [`2026-04-21-fade-and-resume-cue-design.md`](2026-04-21-fade-and-resume-cue-design.md)

Symmetric counterpart to Fade & Stop. Fades `live_volume` / `live_alpha`
from 0 back up while dispatching `Resume`, so one cue owns both ends of an
intermission fade without relying on the target's own `fadein_duration`.

Resolved brainstorming questions:

- Own `duration` + `fade_type` (mirrors Part 1; pre-show fade-in often
  differs from post-show fade-out).
- Target-state policy: Paused → happy path; Running → fade-up fallback, no
  Resume dispatched; Stopped/Error → `_error()`; Pre/PostWait → treated as
  Running.
- Zero `live_volume`/`live_alpha` before dispatching Resume (Paused happy
  path only, and only when a fade is actually going to run — skipped when
  `duration == 0`).
- Non-Media targets: graceful degradation, same as Part 1 ("delayed
  resume").
- Separate `ResumeCue` class (not a mode flag on `StopCue`).

Implementation note: Part 2 introduces `_fader_coordinator.py` as shared
infrastructure. The Part 1 plan gets retrofitted to use it from the first
commit (Part 1 is specced but not yet implemented).

Checklist:

- [x] Brainstorm
- [x] Spec
- [ ] Retrofit Part 1 plan to use `_fader_coordinator`
- [ ] Write Part 2 implementation plan
- [ ] Implement `_fader_coordinator` + `ResumeCue` + `ResumeCueSettings`
- [ ] Unit tests (coordinator + ResumeCue + updated StopCue tests)
- [ ] E2E test — full intermission workflow (Stop then Resume)
- [ ] QA review (`voltagent-qa-sec:qa-expert`)
- [ ] Code review (`voltagent-qa-sec:code-reviewer`)

## Part 3 — Hibernating state & active-cues panel filtering — **not started**

Adds "hibernating" as a first-class concept: a cue that's been paused by a
Fade & Stop with intent-to-resume is hidden from the active-cues panel until
resumed, so the show operator's view stays focused on what's actually
playing.

Open questions to brainstorm:

- [ ] New `CueState.Hibernated`, or a boolean flag on top of `CueState.Pause`?
      (Flag is less invasive; enum value is semantically cleaner.)
- [ ] Which cue triggers hibernation — Fade & Stop with a checkbox? Only
      playlist `GroupCue`s (matching SCS)? All pause-capable cues?
- [ ] Exit transitions: only Fade & Resume de-hibernates? Or does any user
      Start/Resume also clear the flag?
- [ ] Active-cues panel filter: hide entirely, or dim/collapse?
- [ ] Audit & update every consumer of `CueState`:
  - [ ] `lisp/layout/list_layout` active-cues view
  - [ ] `lisp/layout/cart_layout` state rendering
  - [ ] MIDI/OSC status reporting plugins
  - [ ] `test_harness` `cue.list` and signal subscriptions
  - [ ] Serialization — does hibernation persist across session save/load?
- [ ] Visual indicator on the hibernated cue in the main cue list (icon
      overlay? muted colour?).

Checklist once brainstormed:

- [ ] Brainstorm
- [ ] Spec (expect larger than Parts 1-2 due to `CueState` blast radius)
- [ ] Plan
- [ ] Implement
- [ ] Tests (unit + E2E + migration test for existing sessions)
- [ ] QA + code review

## Cross-cutting concerns

Things worth revisiting once all three parts land:

- [ ] Documentation update: user-facing `docs/user/cues/action_cues.md`
      section covering the pre-show → intermission → post-show workflow
      end-to-end.
- [ ] Preset templates for the common "fade out, hibernate, fade in &
      resume" pattern so operators don't rebuild it per show.
- [ ] Whether Fade & Stop + Fade & Resume should share a common base class
      (`_FaderDrivenActionCue`?) once both exist and duplication is visible.
      YAGNI until Part 2 is written.
