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

## Part 2 — Fade & Resume cue — **complete**

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

Implementation note: `_fader_coordinator.py` landed with Part 1 rather
than being introduced here, so Part 2 built directly on it — no
retrofit needed.

Checklist:

- [x] Brainstorm
- [x] Spec
- [x] Retrofit Part 1 plan to use `_fader_coordinator` (landed with Part 1)
- [x] Write Part 2 implementation plan
- [x] Implement `ResumeCue` + `ResumeCueSettings`
- [x] Unit tests (ResumeCue + mixed-state group + session round-trip)
- [x] E2E test — full intermission workflow (Stop then Resume)
- [x] QA review (`voltagent-qa-sec:qa-expert`)
- [x] Code review (`voltagent-qa-sec:code-reviewer`)

Delivered on branch `feat/resume-cue`. Also landed a Part 1 symmetry
fix: `StopCueSettings` now also excludes `ResumeCue` instances from
its target picker.

## Part 3 — Hibernating state & active-cues panel filtering — **complete**

Spec: [`2026-04-23-hibernating-cue-state-design.md`](2026-04-23-hibernating-cue-state-design.md)

Adds "hibernating" as a first-class concept: a cue that's been paused by a
Fade & Stop with action=Hibernate renders compact + dimmed in the Playing
panel, so the show operator's view stays focused on what's actually playing.

Resolved brainstorming questions:

- State representation: new `CueState.Hibernating = 256` composing with
  `Pause` — idiomatic for the bitflag pattern. Every existing
  `state & CueState.Pause` callsite keeps working unchanged.
- Trigger: new `Hibernate` option in Fade & Stop's action combo (StopCue-
  local sentinel — NOT a new `CueAction` enum value).
- Clear: any pause-exit transition (start/resume/stop/interrupt/error)
  in the base `Cue` class. One hook covers every resume path.
- Playing panel: in-place dim + collapse (widget stays in the list, size
  hint shrinks, dbmeter/seek/controls hidden, muted palette).
- Main list indicator: `-hibernating` colour variation via the upstream
  recolour dict (cool blue `#5AF`) — cherry-picked PR #367 as the
  precursor. Cart layout uses a new `led-hibernating.svg`.
- Persistence: runtime-only. Session saves unchanged.

Checklist:

- [x] Brainstorm
- [x] Spec
- [x] Plan
- [x] Implement
- [x] Tests (unit + E2E — runtime-only, no session migration needed)
- [x] QA + code review

Delivered on branch `feat/hibernating-cues`. Landed with a cherry-pick of
upstream PR #367 (icon recolour refactor) as a precursor commit on master.
Post-review fixes: `_set_hibernated` guards against setting Hibernating on
non-Paused cues; group cascade iterates a `list()` snapshot of `cue_model`
to avoid concurrent-mutation races.

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
