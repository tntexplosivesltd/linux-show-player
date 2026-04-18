# SFR-style Workflow Roadmap

Tracker for the three-part delivery of SCS-style SFR functionality in LiSP.
Each part gets its own brainstorming → spec → plan → implementation cycle.

## Part 1 — Fade & Stop cue — **in progress**

Spec: [`2026-04-18-fade-and-stop-cue-design.md`](2026-04-18-fade-and-stop-cue-design.md)

Single-target cue that runs its own `live_volume` + `live_alpha` faders over
a user-specified duration, then dispatches `Stop` / `Pause` / `Interrupt`.
Group targets fan out via the existing `GroupCue` cascade.

- [x] Brainstorm design
- [x] Write spec
- [ ] Write implementation plan
- [ ] Implement `StopCue` + `StopCueSettings`
- [ ] Unit tests
- [ ] E2E test via `test_harness`
- [ ] QA review (`voltagent-qa-sec:qa-expert`)
- [ ] Code review (`voltagent-qa-sec:code-reviewer`)

## Part 2 — Fade & Resume cue — **not started**

Symmetric counterpart to Fade & Stop. Fades `live_volume` / `live_alpha`
from 0 back up while dispatching `Resume`, so one cue owns both ends of an
intermission fade without relying on the target's own `fadein_duration`.

Open questions to brainstorm:

- [ ] Does it need its own duration + fade-in curve, or inherit from a
      paired Fade & Stop cue? (Likely: own settings, matches Part 1.)
- [ ] What happens if the target isn't in a paused state when fired?
      (Error? No-op? Start from scratch?)
- [ ] Does it set `live_volume` / `live_alpha` to `0` *before* calling
      Resume (to avoid a pop at resume-tick-0), or trust the target was left
      at 0 by the previous Fade & Stop?
- [ ] Can it target a non-Media cue (e.g. a paused Command cue)? Probably
      same graceful degradation as Part 1 — no fader, delayed Resume.
- [ ] Should it be a separate cue type or a mode flag on `StopCue`?
      (Leaning separate for clarity, matches `VolumeControl` single-purpose
      convention.)

Checklist once brainstormed:

- [ ] Brainstorm
- [ ] Spec
- [ ] Plan
- [ ] Implement
- [ ] Tests (unit + E2E)
- [ ] QA + code review

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
