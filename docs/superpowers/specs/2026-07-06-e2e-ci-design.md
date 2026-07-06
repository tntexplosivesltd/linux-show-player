# E2E Tests in CI — Design

**Date:** 2026-07-06
**Status:** Design (validated via Docker dry-run)

## Goal

Run **all** E2E tests (`tests/e2e/test_*.py`, currently 40) on every pull
request as a **blocking / required** gate. Today CI runs only pytest unit
tests (`--ignore=tests/e2e`); the E2E suite — which exercises real
GStreamer playback, video windows, groups, fades, undo/redo, and the full
harness surface — never runs automatically, so regressions in that layer
reach `master` unguarded.

## Background: how E2E tests work

Each `tests/e2e/test_*.py` is a **standalone script**, not a pytest test.
`helpers.run_suite()` boots a real LiSP subprocess (`python -m lisp.main`),
waits for the `test_harness` plugin to answer JSON-RPC on
`127.0.0.1:8070`, runs the checks, prints a summary, and exits `0` (all
passed) / `1` (failures) / `2` (LiSP failed to start).

Consequences that shape this design:

- **Fixed port ⇒ strictly serial.** Two LiSP instances cannot both bind
  8070. Tests must run one at a time, with a stale-process kill between.
- **Needs real media backends.** Audio (PulseAudio), video (a GL sink under
  a real X server), and GStreamer plugins must be present — pytest's
  `offscreen`/no-audio environment is insufficient.
- **Per-test process isolation** already exists (each script is its own
  LiSP lifecycle), so a crash in one test cannot corrupt another.

## Decisions (locked)

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Gate type | **Blocking / required** | The whole point is to stop E2E regressions merging. |
| Python version | **Single: 3.12** | E2E validates behavior, not Python-version compat; the existing unit `test` job already covers 3.10–3.13. One version keeps the (slow, serial) job affordable. |
| Media stack | **Real virtual backends** — Xvfb + software GL (llvmpipe) + PulseAudio null-sink | No LiSP code changes; exercises the real GStreamer paths rather than stubbing them. Proven feasible in the dry-run. |
| Per-failure retry | **1× (2 attempts total)** in the runner | Absorbs rare startup jitter without masking real failures. |
| Timing-fragile tests | **Harden the tests** (poll-until, not sleep-then-assert) | A blocking gate cannot ship flaky. See "Test hardening" below. |

## Architecture

Two deliverables, independent and independently testable:

1. **`tests/e2e/run_all.py`** — a serial test runner (pure orchestration;
   no LiSP imports). Discovers, runs, retries, and aggregates.
2. **An `e2e` job in `.github/workflows/ci.yml`** — provisions the media
   stack + harness config, then invokes the runner.

Plus a supporting change:

3. **Test hardening** — a `wait_current_time()` helper in
   `tests/e2e/helpers.py` and conversion of 4 tests' timing assertions from
   `sleep(N); assert current_time > X` to poll-until.

### 1. The runner: `tests/e2e/run_all.py`

**Responsibility:** given a directory of standalone E2E scripts, run each
in its own subprocess, serially, with a timeout and one retry, and return a
single aggregate exit code.

**Interface:**

```
python tests/e2e/run_all.py [--retries N] [--timeout SECS]
                            [--filter GLOB] [--list]
```

| Flag | Default | Meaning |
|------|---------|---------|
| `--retries` | `1` | Extra attempts per failing test (2 total at default). |
| `--timeout` | `180` | Per-test wall-clock timeout (seconds). A timed-out test is a failure. |
| `--filter` | `test_*.py` | Glob to select a subset (for local iteration). |
| `--list` | — | Print the discovered test files and exit without running. |

**Behavior:**

- **Discovery:** glob `tests/e2e/test_*.py`, sorted. This intentionally
  catches the two files *without* the `_e2e` suffix
  (`test_cue_settings_reorg.py`, `test_shuffle_restart.py`) that a
  narrower `*_e2e.py` pattern would miss.
- **Execution:** for each file, `subprocess.run([sys.executable, path],
  timeout=…)`. Using `sys.executable` guarantees the child runs under the
  same (Poetry venv) interpreter — the documented failure mode is a bare
  `python` that lacks LiSP deps.
- **Retry:** on non-zero exit or timeout, `pkill -f lisp.main`, brief
  sleep, retry up to `--retries` times. A test that passes on any attempt
  counts as passed (and is reported as "flaky: passed on retry").
- **Between every test:** `pkill -f lisp.main` + short settle, so a wedged
  LiSP from a timed-out test cannot steal port 8070 from the next.
- **Aggregation:** print a summary (passed / failed / retried, with the
  failing test names), and exit `1` if any test failed after all retries,
  else `0`.
- **Output:** stream each test's stdout/stderr through (prefixed or
  sectioned) so a CI log shows exactly which check failed — no swallowing.

**Why a bespoke runner and not pytest:** these scripts own their process
lifecycle and are not pytest tests; wrapping them in pytest would fight
both the fixed-port serialization and the subprocess model. A ~100-line
runner matches the existing `docs/testing.md` mental model.

### 2. The CI job: `e2e` in `.github/workflows/ci.yml`

Added alongside the existing `lint` and `test` jobs (neither is modified).
Runs on `ubuntu-24.04`, single Python 3.12.

**System dependencies** = everything the `test` job installs, **plus** the
media stack (validated exact list):

- Headless display / GL: `xvfb`, `libgl1-mesa-dri`
- Audio: `pulseaudio`, `pulseaudio-utils`
- GStreamer: `gstreamer1.0-gl`, `gstreamer1.0-x`,
  `gstreamer1.0-plugins-bad`, `gstreamer1.0-plugins-ugly` (provides
  `x264enc`), `gstreamer1.0-libav`, `gstreamer1.0-tools` (provides
  `gst-launch-1.0`, used by 6 tests to build fixtures)
- Qt xcb runtime: `libxcb-cursor0`, `libxkbcommon-x11-0`, `libxcb-icccm4`,
  `libxcb-image0`, `libxcb-keysyms1`, `libxcb-randr0`,
  `libxcb-render-util0`, `libxcb-shape0`, `libxcb-xinerama0`, `libxcb-xkb1`

**Environment:**

- `LIBGL_ALWAYS_SOFTWARE=1`, `GALLIUM_DRIVER=llvmpipe` — force software GL.
- **Do not** set `QT_QPA_PLATFORM=offscreen` (the unit job does). Video
  tests need a real xcb platform under Xvfb; offscreen has no GL surface.
- `XDG_RUNTIME_DIR` set to a writable dir (PulseAudio needs it).

**Audio setup:** start PulseAudio in the runner's user session
(`pulseaudio --start --exit-idle-time=-1`), load a null sink, and set it
default. Confirmed to work as the non-root runner user.

**Display:** run the suite under
`xvfb-run -a --server-args="-screen 0 1280x1024x24 +extension GLX +render"`.

**Config provisioning** — write three files into
`~/.config/LinuxShowPlayer/0.6/` before launching. LiSP's config layer
**discards a user file whose `_version_` differs from the plugin default**,
so each `_version_` must match exactly:

| File | Content | Why |
|------|---------|-----|
| `test_harness.json` | `{"_version_":"1","_enabled_":true,…}` | Enables the harness. Without it, `start_lisp` times out and **all 40 fail**. |
| `midi.json` | `{"_version_":"2.1","_enabled_":false,…}` | `python-rtmidi` **segfaults** on a headless box with no `/dev/snd/seq`. No E2E test needs MIDI. |
| `playback_monitor.json` | `{"_version_":"2","_enabled_":true,…}` | Defaults off, but `test_playback_monitor_e2e.py` asserts the plugin is loaded (passes locally only because dev configs enable it). |

**Invocation:** `poetry run python tests/e2e/run_all.py` (under
`xvfb-run`). The job fails iff the runner exits non-zero.

### 3. Test hardening

The dry-run found 4 tests that fail **only** on timing under a slow,
software-rendered runner — none are product bugs. Root cause: fixed
`sleep(N)` followed by a threshold assertion, where the GStreamer position
clock lags wall-clock during pipeline startup/decode under load.

**Fix pattern** — add to `helpers.py`, mirroring the existing
`wait_state()` / `wait_for_signal()` poll idiom:

```python
def wait_current_time(cue_id, min_ms=1, timeout=5.0):
    """Poll until a cue's current_time exceeds min_ms, or timeout."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if call("cue.state", {"id": cue_id})["current_time"] > min_ms:
            return True
        time.sleep(0.1)
    return False
```

Then convert the fragile assertions:

| Test | Checks | Change |
|------|--------|--------|
| `test_video_e2e.py` | 1d, 2c, 5e, 8c (`current_time > 0` after `sleep(0.5)`) | Replace with `wait_current_time(id, min_ms=1, timeout=5)`. |
| `test_video_window_e2e.py` | 6g (`current_time > 500` after `sleep(1)`) | `wait_current_time(id, min_ms=500, timeout=5)`. |
| `test_fade_and_stop_e2e.py` | test 2 (`elapsed < 1.5`, observed 1514ms) | Widen upper band to a generous value (e.g. `< 3.0`); the fade-ran assertion is the lower bound and the `paused` signal, both already robust. |
| `test_groups_e2e.py` | 4b, 5a, 6a, 10d (playlist auto-advance sampled once) | Poll for the transition (subscribe + `wait_for_signal`, or poll child state) instead of a single post-`sleep` sample. Outcome checks (4c, 5b) already pass, confirming the chaining itself is correct. |

These changes make the tests pass on both fast dev machines and slow CI
without loosening assertions into meaninglessness.

## Error handling & failure modes

- **LiSP fails to start (exit 2):** treated as a test failure; retried once,
  then reported. The per-test stderr is surfaced in the CI log.
- **Test hangs:** `--timeout` (180s) kills it; counted as failure.
- **Stale LiSP holds port 8070:** `pkill -f lisp.main` between every test
  (and before retry) prevents "Method not found"/silent-steal confusion.
- **Genuinely flaky pass-on-retry:** reported explicitly in the summary so
  a creeping flakiness trend is visible rather than hidden.

## Verification

The entire recipe was validated in a Docker container built **from bare
`ubuntu:24.04`, running as a non-root user** — deliberately a strict subset
of the real GitHub `ubuntu-24.04` image, so a green run there proves the
apt list is self-sufficient. Results: 36/40 green out of the box; the 4
timing-fragile tests diagnosed above (all test-only, no product bug). The
dry-run also surfaced and fixed 4 environment blockers that would each have
been red on the first real CI push (rtmidi segfault, missing
`gst-launch-1.0`, missing `x264enc`, `playback_monitor` disabled).

Acceptance: after test hardening, a full `run_all.py` pass in the dry-run
container is green (0 failures, retries allowed but not required).

## Non-goals (YAGNI)

- **Parallelism / sharding.** The fixed harness port forces serial; a
  dynamic-port scheme is a larger, separate change not justified yet.
- **Multi-OS / multi-Python E2E matrix.** One Linux + one Python.
- **Moving E2E into pytest.** Out of scope; would fight the process model.
- **Caching generated media fixtures across runs.** Regeneration is cheap
  relative to LiSP startup; skip the complexity.

## Deliverables summary

1. `tests/e2e/run_all.py` — serial runner with retry/timeout/filter/list.
2. `helpers.wait_current_time()` + hardening of 4 tests.
3. `e2e` job in `.github/workflows/ci.yml` (media stack + config + runner).
4. A short note in `docs/testing.md` pointing at `run_all.py` and the CI
   gate.
