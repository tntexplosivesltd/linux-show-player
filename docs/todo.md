# Project TODO

Loose backlog of ideas and known gaps. Items end with `?` are
exploratory — decide scope before starting.

## UI / UX

- Light theme: disabled cues — verify contrast and strikethrough/dim
  treatment under the light theme; the dark theme is the well-tested
  path today.
- Keybinding tooltip on button hover — surface the bound shortcut in
  the tooltip for toolbar / cue-action buttons so operators don't have
  to memorise them.
- Video / image preview / thumbnail in the cue inspector — small
  preview pane for media cues so the operator can confirm the right
  file is bound without playing the cue.
- Note / comment cues? — non-playing cues that carry operator notes
  inside the cue list (cf. QLab memo cues).
- Timeline view — alternative layout showing cues against time, in
  addition to the list and cart layouts.
- Cue search / filter bar — locate by name, `cue_number`, or colour
  in shows with hundreds of cues without scrolling. Builds on the
  existing `cue_number` infrastructure.
- Goto-cue action / hotkey — jump the standby cursor to a numbered
  or labelled cue (e.g. `Q12.5`). The static `cue_number` is already
  assigned and collision-checked; this just needs UI + a layout
  action.
- Undo / redo history panel — surface `CommandsStack` so the
  operator can see the last N commands and jump back to a prior
  state (recovery from a wrong drag mid-show).
- Printable running order — PDF / HTML export of the cue list with
  numbers, names, durations, and operator notes for the SM's book.

## Cues / playback

- More group types? — beyond the current parallel / playlist modes
  (e.g. random-pick, round-robin, conditional).
- Release from loop — clean way to exit a looping cue at the next
  natural boundary rather than a hard stop.
- Slicing — split a media cue into named regions / sub-cues that can
  be triggered independently.
- Resolve missing media — on session load, collect every missing file
  and prompt once. After the user repairs the first one, auto-scan
  that directory for the rest before re-prompting.
- Pre-show readiness panel — one-click preflight that verifies every
  media file resolves, every MIDI / OSC device is reachable, every
  configured video output exists, and every targeting cue has a live
  target. Composes with the existing `TargetingCue` invalid-target
  signal and the missing-media work above.
- Auto-save + crash recovery — periodic snapshot of the session to a
  sidecar file; on next launch, prompt to recover if a crash marker
  is present. Cheap insurance for live use.
- Cue templates / show defaults — show-wide defaults for fade
  duration, fade curve, colour, and behaviour flags so a freshly
  created cue inherits the production's house style instead of
  framework defaults.
- Bulk edit on selection — explicit "apply this value to all
  selected" affordance in the inspector for fade durations, volumes,
  and colours. The multi-cue inspector already renders mixed values;
  this closes the write path.
- MIDI / OSC learn — bind the next received message to the focused
  cue / control instead of typing CC numbers and addresses by hand.
- Audition output — preview a cue on headphones (or a secondary
  output bus) without sending it to the house. Standard
  QLab / SCS pattern; the GStreamer backend can support it via a
  per-cue routing override.
- Cue dependencies / triggers? — start cue X when cue Y reaches
  state Z, richer than the current next-action chain (e.g. "start
  on target reaches 3.0s remaining").
- Python / script cues? — execute a small user-supplied script on
  trigger. Powerful but security-sensitive; needs a sandboxing story
  before it ships.

## Video pipeline

- **First-cue-transition flicker in playlist groups.** The first
  hand-off between two videos in a playlist `GroupCue` shows a brief
  flicker; subsequent transitions in the same playlist (e.g. loop
  iteration 2+) flow cleanly. Suggests something is one-time-cold on
  the very first inter-cue boundary — candidates to investigate:
  GL context first-init on the new `glimagesink`, X11/compositor
  warm-up of the singleton render widget, or an asymmetry in the
  100ms deferred-clear window when the first cue's pipeline hasn't
  been reused before. The deferred-clear / deferred-show fix in
  `docs/bugs/2026-05-23-video-sink-stale-frame-bleedthrough.md` is
  the right architecture; this is a residual on top of it.
- Verify image-stop-then-video transition under the new deferred-
  clear behaviour. Original failure mode: image cue's 5-second
  duration expires, projection should clear to black after ~100ms,
  next video plays cleanly with no bleed of the image's last frame.
  The fix targets this case but it needs an operator-level pass.
- Multiple video cues at once / video mixing — compose more than one
  video stream onto the projection output (compositor element, alpha,
  positioning).
- GPU acceleration — survey what the current pipeline does on the CPU
  vs. GPU and where vaapi / nvdec / glcolorconvert would help.
- Test second screen — exercise the projection-window-on-output-2
  path. May need a less minimal WM than dwm; try openbox as a stand-in
  for a more typical desktop session.
- Native Wayland support. Today the overlay path assumes X11
  semantics: `winId()` is treated as an XID, `glimagesink` /
  `xvimagesink` are the preferred sinks, and `set_display_screen()`
  positions the window via absolute `move()`. Under
  `QT_QPA_PLATFORM=wayland` none of that holds. Work needed:
  add `waylandsink` to `_VIDEO_SINK_FACTORIES`
  (`elements/video_sink.py:31`); handle the `need-context` bus
  message to share `wl_display` with `glimagesink`; switch projection
  geometry to `VideoOverlay.set_render_rectangle()` +
  `QWindow::setScreen()` for monitor selection. Currently a native
  Wayland session silently degrades to an unembeddable
  `autovideosink` window.
- Startup warning when Qt platform and available video sinks are
  mismatched. If `QT_QPA_PLATFORM=wayland` but no Wayland-capable
  sink is installed (or vice versa), log an actionable warning at
  startup suggesting `QT_QPA_PLATFORM=xcb` (or the missing package).
  Cheap to add, prevents the operator discovering it via a broken
  projection mid-show.
- Live camera / capture cues — `v4l2src` / `pipewiresrc` source cues
  for IMAG, pre-show slates from a capture card, or webcam input.
- NDI in / out — increasingly the lingua franca for venue video
  routing; would land alongside the existing GStreamer source/sink
  factories.
- Projection-mapping primitives — keystone, corner-pin, edge-blend
  on the projection surface. Lands on the same `VideoSink` swap path
  that the stale-frame bug touches.

## Networking / external control

- Tablet / browser remote — small web UI layered on the existing
  `test_harness` JSON-RPC plugin so the SM can run cues from
  front-of-house on an iPad. Most of the surface area is already
  exposed (~42 RPC methods); the work is mostly frontend.
- Remote follower instance — a secondary LiSP that mirrors the
  primary's state for redundancy / multi-operator workflows.
- DMX / Art-Net output cues — many small productions want one tool
  for sound, projection, and a few LED washes; the cue model already
  supports the abstraction.
- LTC / MTC timecode follow — slave cue triggering to incoming
  timecode for cross-discipline shows. The timecode plugin already
  *emits* MTC; this is the read path.
- Ableton Link sync? — tempo sync for music-driven shows.

## Quality / testing

- Soak testing — long-running session run to surface leaks, fd
  exhaustion, GStreamer pipeline drift, and signal-handler regressions.
- Full show from SCS — port a real Show Cue Systems show into LiSP as
  an end-to-end realism test (covers scenarios our synthetic tests
  miss).
- Headless smoke pass in CI — extend the existing
  `tools/render_cuelistview.py` headless approach to a "load every
  fixture session, advance through every cue, assert no exceptions"
  job that runs on every PR.
- Fuzz the session-file loader — corrupted, truncated, and
  forward-version `.lsp` files are a real-world failure mode (users
  email broken sessions). Quick win for robustness.
- Qt cross-thread warnings on test teardown — the full unit test run
  finishes with `QObject::killTimer: Timers cannot be stopped from
  another thread` on stderr. Doesn't fail any test, but it's noise
  that masks real warnings and points at a real lifecycle issue
  (probably a `QtSlot` invoker QObject being GC'd off the main
  thread when its owning Signal goes away). Track down the offender
  and fix the teardown ordering, or move the cleanup into a
  main-thread `deleteLater()`.
- E2E sample-timing flakes — two assertions sample state at a
  hard-coded moment with `time.sleep()` and fail under sweep-run
  load while passing reliably in isolation:
  - `tests/e2e/test_video_e2e.py::test_7_loop` 7b
    ("Still Running during second iteration") — sleeps 2.5s then
    asserts `cue_state == "Running"`. Catches the cue in a
    momentary non-Running state across the loop seek. Fix: poll
    over a window (e.g. expect "Running" at any point between
    t=2.0s and t=3.0s) rather than sampling at exactly 2.5s.
  - `tests/e2e/test_uri_av_input_silent_eos_race_e2e.py` iter 0
    and iter 1 ("audio current_time advanced (got 0 ms)") — the
    first two iterations occasionally read `current_time == 0` on
    a cue that's transitioning to Running; iterations 2-19 are
    stable. Fix: gate the read on `current_time > 0` with a
    short polling window, or skip iter 0 as a warmup.

## Accessibility

- High-contrast / large-text operator mode — distinct from theming;
  aimed at low-light booth conditions and reduced vision. Should
  scale cue-list row height, status-icon size, and inspector typography
  in lockstep.
- Screen-reader support audit — verify the cue list, inspector, and
  layout actions expose accessible names / roles to ATs (Orca on
  Linux, NVDA / JAWS if Qt's a11y bridge is enabled on Windows).
- Keyboard-only operation audit — cross-check that every layout
  action has a discoverable shortcut; ties into the existing
  keybinding-tooltip todo.

## Docs

- Add screenshots to the user docs (see `docs/screenshots-todo.md`
  for the placeholder list).
