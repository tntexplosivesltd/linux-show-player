# Fade & Resume Cue Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `ResumeCue` action cue ("Fade & Resume") that targets a single cue (including `GroupCue` for cascading), zeroes `live_volume` + `live_alpha` on paused targets, dispatches `Resume`, then fades those faders back up to `1.0` over a user-supplied duration and curve — the symmetric counterpart to Part 1's `StopCue`.

**Architecture:** ResumeCue lives at `lisp/plugins/action_cues/resume_cue.py` and builds on the `_fader_coordinator` helper module established by the retrofitted Part 1 plan (`build_affected_set`, `collect_live_faders`, `ParallelFadeRunner`). `__start__` branches on target state: Paused -> zero-step + Resume dispatch + fade-up; Running/PreWait/PostWait -> fade-up fallback with no Resume; Stopped/Error -> `_error()`. The zero step is synchronous (`rsetattr` on the fader's target/attribute — the same mechanism `Fader._fade` uses at each tick) so the GStreamer pipeline reads gain=0 before any samples flow post-Resume. `__stop__` / `__interrupt__` abort the in-flight runner without rolling back target state.

**Tech Stack:** Python 3.9+, PyQt5, LiSP `Property` / `Cue` / `Fader` / `@async_function`, `_fader_coordinator` helpers (introduced in Part 1), `rsetattr` from `lisp.core.util`, GStreamer element faders, pytest + pytest-qt for unit tests, JSON-RPC test_harness for E2E.

**Spec:** `docs/specs/2026-04-21-fade-and-resume-cue-design.md`

**Roadmap:** `docs/specs/2026-04-18-sfr-workflow-roadmap.md` (Part 2 of 3)

**Depends on:** `plans/07-fade-and-stop-cue.md` — specifically that `lisp/plugins/action_cues/_fader_coordinator.py` has landed with `build_affected_set`, `collect_live_faders`, and `ParallelFadeRunner`. Part 1 must be implemented (or at least merged up to Task 5A of plan 07) before this plan runs, because ResumeCue imports the coordinator directly.

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `lisp/plugins/action_cues/resume_cue.py` | Create | `ResumeCue` class, `ResumeCueSettings` page, registry wiring. Thin — state branching + zero step + delegation to the shared coordinator. |
| `lisp/i18n/ts/*.ts` | Regenerate | New `QT_TRANSLATE_NOOP` strings for "Fade & Resume", UI labels. |
| `tests/cues/test_resume_cue.py` | Create | Unit tests for ResumeCue: state branches, zero step, Resume dispatch, abort, settings. |
| `tests/e2e/test_fade_and_resume_e2e.py` | Create | E2E suite: full intermission workflow (Stop then Resume on a MediaCue), non-media graceful path, mid-fade abort. |
| `docs/specs/2026-04-18-sfr-workflow-roadmap.md` | Modify | Tick Part 2 checkboxes at the end. |

No new helpers, no core changes — the coordinator from Part 1 is reused.

---

## Task 1: Scaffold `ResumeCue` class with default properties

**Files:**
- Create: `lisp/plugins/action_cues/resume_cue.py`
- Create: `tests/cues/test_resume_cue.py`

- [ ] **Step 1: Write failing test for class existence and defaults**

Create `tests/cues/test_resume_cue.py`:

```python
"""Unit tests for ResumeCue (Fade & Resume) action cue."""
from unittest.mock import MagicMock

from lisp.core.fade_functions import FadeInType
from lisp.cues.cue import CueAction
from lisp.plugins.action_cues.resume_cue import ResumeCue


class TestResumeCueDefaults:
    def test_class_display_name(self):
        assert ResumeCue.Name == "Fade & Resume"

    def test_class_category(self):
        assert ResumeCue.Category == "Action cues"

    def test_class_supported_actions(self):
        assert CueAction.Default in ResumeCue.CueActions
        assert CueAction.Start in ResumeCue.CueActions
        assert CueAction.Stop in ResumeCue.CueActions
        assert CueAction.Interrupt in ResumeCue.CueActions

    def test_default_target_id(self, mock_app):
        cue = ResumeCue(app=mock_app)
        assert cue.target_id is None or cue.target_id == ""

    def test_default_fade_type(self, mock_app):
        cue = ResumeCue(app=mock_app)
        assert cue.fade_type == FadeInType.Linear.name

    def test_default_duration_zero(self, mock_app):
        cue = ResumeCue(app=mock_app)
        assert cue.duration == 0

    def test_no_action_property(self, mock_app):
        """ResumeCue has no `action` property — verb is fixed to Resume."""
        cue = ResumeCue(app=mock_app)
        assert not hasattr(type(cue), "action") or \
            "action" not in type(cue).__dict__
```

- [ ] **Step 2: Run test to verify it fails**

Run: `poetry run pytest tests/cues/test_resume_cue.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'lisp.plugins.action_cues.resume_cue'`.

- [ ] **Step 3: Create the minimal `ResumeCue` class**

Create `lisp/plugins/action_cues/resume_cue.py`:

```python
# This file is part of Linux Show Player
#
# Copyright 2026 Francesco Ceruti <ceppofrancy@gmail.com>
#
# Linux Show Player is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# Linux Show Player is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Linux Show Player.  If not, see <http://www.gnu.org/licenses/>.

import logging

from PyQt5.QtCore import QT_TRANSLATE_NOOP

from lisp.core.decorators import async_function
from lisp.core.fade_functions import FadeInType
from lisp.core.properties import Property
from lisp.core.util import rsetattr
from lisp.cues.cue import Cue, CueAction, CueState
from lisp.ui.ui_utils import translate

logger = logging.getLogger(__name__)


class ResumeCue(Cue):
    Name = QT_TRANSLATE_NOOP("CueName", "Fade & Resume")
    Category = QT_TRANSLATE_NOOP("CueCategory", "Action cues")

    target_id = Property()
    fade_type = Property(default=FadeInType.Linear.name)
    icon = Property(default="action-resume")

    CueActions = (
        CueAction.Default,
        CueAction.Start,
        CueAction.Stop,
        CueAction.Interrupt,
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = translate("CueName", self.Name)

        # The in-flight ParallelFadeRunner, if any. Set by __start__,
        # cleared on completion/abort. Used by __stop__ to abort the fade.
        self._runner = None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `poetry run pytest tests/cues/test_resume_cue.py -v`
Expected: PASS (all 7 tests).

- [ ] **Step 5: Commit**

```
git add lisp/plugins/action_cues/resume_cue.py tests/cues/test_resume_cue.py
git commit -m "feat(resume-cue): scaffold ResumeCue with default properties"
```

---

## Task 2: Target resolution and missing-target error path

**Files:**
- Modify: `lisp/plugins/action_cues/resume_cue.py`
- Modify: `tests/cues/test_resume_cue.py`

- [ ] **Step 1: Write failing tests for target resolution**

Append to `tests/cues/test_resume_cue.py`:

```python
class TestTargetResolution:
    def test_missing_target_logs_and_errors(self, mock_app, caplog):
        mock_app.cue_model.get.return_value = None
        cue = ResumeCue(app=mock_app)
        cue.target_id = "does-not-exist"

        error_fired = []
        cue.error.connect(lambda *_: error_fired.append(True))

        result = cue.__start__()

        assert result is False
        assert error_fired == [True]
        assert any("target" in r.message.lower() for r in caplog.records)

    def test_empty_target_id_logs_and_errors(self, mock_app):
        mock_app.cue_model.get.return_value = None
        cue = ResumeCue(app=mock_app)
        cue.target_id = ""

        error_fired = []
        cue.error.connect(lambda *_: error_fired.append(True))

        result = cue.__start__()

        assert result is False
        assert error_fired == [True]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `poetry run pytest tests/cues/test_resume_cue.py::TestTargetResolution -v`
Expected: FAIL — the inherited `Cue.__start__` returns True.

- [ ] **Step 3: Add `__start__` stub with target resolution**

Append to `lisp/plugins/action_cues/resume_cue.py`:

```python
    def __start__(self, fade=False):
        target = self.app.cue_model.get(self.target_id)
        if target is None:
            logger.warning(
                "ResumeCue: target cue %r not found", self.target_id
            )
            self._error()
            return False

        # State branching + fade orchestration land in subsequent tasks.
        return False
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `poetry run pytest tests/cues/test_resume_cue.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```
git add lisp/plugins/action_cues/resume_cue.py tests/cues/test_resume_cue.py
git commit -m "feat(resume-cue): resolve target_id and error on missing target"
```

---

## Task 3: Stopped / Error target -> `_error()` branch

**Files:**
- Modify: `lisp/plugins/action_cues/resume_cue.py`
- Modify: `tests/cues/test_resume_cue.py`

The spec says: if `target.state` is neither `CueState.Pause` nor any flag in `CueState.IsRunning` (Running / PreWait / PostWait), we've got a Stopped or Error target — log and `_error()`. Handle that branch first; it's the simplest.

- [ ] **Step 1: Write failing tests for Stopped/Error targets**

Append to `tests/cues/test_resume_cue.py`:

```python
from lisp.cues.cue import CueState
from lisp.cues.media_cue import MediaCue


def _make_media_target(state, mock_app, cue_id="t1"):
    """Build a mock MediaCue target in the given state and wire into mock_app."""
    target = MagicMock(spec=MediaCue)
    target.id = cue_id
    target.state = state
    target.media = MagicMock()
    target.media.element.return_value = None
    mock_app.cue_model.get.return_value = target
    return target


class TestStoppedOrErrorTarget:
    def test_stopped_target_errors(self, mock_app, caplog):
        target = _make_media_target(CueState.Stop, mock_app)

        cue = ResumeCue(app=mock_app)
        cue.target_id = target.id

        error_fired = []
        cue.error.connect(lambda *_: error_fired.append(True))

        result = cue.__start__()

        assert result is False
        assert error_fired == [True]
        target.execute.assert_not_called()

    def test_error_target_errors(self, mock_app):
        target = _make_media_target(CueState.Error, mock_app)

        cue = ResumeCue(app=mock_app)
        cue.target_id = target.id

        error_fired = []
        cue.error.connect(lambda *_: error_fired.append(True))

        result = cue.__start__()

        assert result is False
        assert error_fired == [True]
        target.execute.assert_not_called()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `poetry run pytest tests/cues/test_resume_cue.py::TestStoppedOrErrorTarget -v`
Expected: FAIL — `__start__` currently returns False without firing `error`.

- [ ] **Step 3: Implement state-branching dispatch**

Replace the `__start__` stub in `lisp/plugins/action_cues/resume_cue.py`:

```python
    def __start__(self, fade=False):
        target = self.app.cue_model.get(self.target_id)
        if target is None:
            logger.warning(
                "ResumeCue: target cue %r not found", self.target_id
            )
            self._error()
            return False

        state = target.state
        if state & CueState.Pause:
            return self._paused_path(target)
        if state & CueState.IsRunning:
            return self._running_fallback(target)

        # Stopped or Error — nothing sensible to resume.
        logger.warning(
            "ResumeCue: target %r is in state %r; cannot resume",
            self.target_id, state,
        )
        self._error()
        return False

    def _paused_path(self, target):
        # Implemented in Task 5.
        return False

    def _running_fallback(self, target):
        # Implemented in Task 4.
        return False
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `poetry run pytest tests/cues/test_resume_cue.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```
git add lisp/plugins/action_cues/resume_cue.py tests/cues/test_resume_cue.py
git commit -m "feat(resume-cue): dispatch by target state, error on Stopped/Error"
```

---

## Task 4: Running-target fallback (no Resume dispatch, fade up only)

**Files:**
- Modify: `lisp/plugins/action_cues/resume_cue.py`
- Modify: `tests/cues/test_resume_cue.py`

- [ ] **Step 1: Write failing tests for the Running fallback**

Append to `tests/cues/test_resume_cue.py`:

```python
class TestRunningFallback:
    def test_running_no_resume_dispatched(self, mock_app, monkeypatch):
        """Running target: Resume is NOT dispatched (already running)."""
        target = _make_media_target(CueState.Running, mock_app)

        # Substitute a fake runner so we don't actually run threads.
        fake_runner = MagicMock()
        fake_runner.run_until_complete.return_value = True
        monkeypatch.setattr(
            "lisp.plugins.action_cues.resume_cue.ParallelFadeRunner",
            MagicMock(return_value=fake_runner),
        )
        _patch_async_function_synchronous(monkeypatch)

        # Give the target a volume fader so `will_fade` is True.
        volume_fader = MagicMock()
        volume_el = MagicMock()
        volume_el.get_fader.return_value = volume_fader
        target.media.element = lambda n: volume_el if n == "Volume" else None

        cue = ResumeCue(app=mock_app)
        cue.target_id = target.id
        cue.duration = 500

        result = cue.__start__()

        assert result is True
        target.execute.assert_not_called()  # no Resume dispatched
        fake_runner.run_until_complete.assert_called_once()

    def test_running_no_faders_is_noop(self, mock_app):
        """Running target with no faders: no-op, returns False."""
        target = _make_media_target(CueState.Running, mock_app)

        cue = ResumeCue(app=mock_app)
        cue.target_id = target.id
        cue.duration = 500

        result = cue.__start__()

        assert result is False
        target.execute.assert_not_called()

    def test_running_duration_zero_is_noop(self, mock_app):
        """Running target with duration=0: no-op (no fade needed)."""
        target = _make_media_target(CueState.Running, mock_app)
        volume_el = MagicMock()
        volume_el.get_fader.return_value = MagicMock()
        target.media.element = lambda n: volume_el if n == "Volume" else None

        cue = ResumeCue(app=mock_app)
        cue.target_id = target.id
        cue.duration = 0

        result = cue.__start__()

        assert result is False
        target.execute.assert_not_called()

    def test_prewait_treated_as_running(self, mock_app, monkeypatch):
        """PreWait/PostWait map to the Running fallback."""
        target = _make_media_target(CueState.PreWait, mock_app)

        fake_runner = MagicMock()
        fake_runner.run_until_complete.return_value = True
        monkeypatch.setattr(
            "lisp.plugins.action_cues.resume_cue.ParallelFadeRunner",
            MagicMock(return_value=fake_runner),
        )
        _patch_async_function_synchronous(monkeypatch)

        volume_el = MagicMock()
        volume_el.get_fader.return_value = MagicMock()
        target.media.element = lambda n: volume_el if n == "Volume" else None

        cue = ResumeCue(app=mock_app)
        cue.target_id = target.id
        cue.duration = 500

        cue.__start__()

        target.execute.assert_not_called()


def _patch_async_function_synchronous(monkeypatch):
    """Make @async_function run its wrapped target synchronously.

    `async_function` wraps a call in `Thread(target=..., daemon=True).start()`.
    Substituting Thread with a class that calls the target immediately on
    `start()` makes assertions deterministic.
    """
    class _SyncThread:
        def __init__(self, target=None, args=(), kwargs=None, daemon=False,
                     name=None):
            self._target = target
            self._args = args
            self._kwargs = kwargs or {}

        def start(self):
            self._target(*self._args, **self._kwargs)
    monkeypatch.setattr("lisp.core.decorators.Thread", _SyncThread)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `poetry run pytest tests/cues/test_resume_cue.py::TestRunningFallback -v`
Expected: FAIL — `_running_fallback` currently returns False unconditionally.

- [ ] **Step 3: Implement `_running_fallback`**

Add imports near the top of `lisp/plugins/action_cues/resume_cue.py` (next to the existing ones):

```python
from lisp.plugins.action_cues._fader_coordinator import (
    build_affected_set,
    collect_live_faders,
    ParallelFadeRunner,
)
```

Replace the `_running_fallback` stub with:

```python
    def _running_fallback(self, target):
        """Target is already running — fade faders up to 1.0, no Resume."""
        affected = build_affected_set(target)
        faders = collect_live_faders(affected, states=CueState.IsRunning)

        if self.duration <= 0 or not faders:
            return False  # nothing to do

        self._runner = ParallelFadeRunner(
            faders,
            to_value=1.0,
            curve=FadeInType[self.fade_type],
            duration_seconds=self.duration / 1000,
        )
        self._run_fade(target=target)
        return True

    @async_function
    def _run_fade(self, target):
        """Drive the runner to completion in a daemon thread.

        Shared by `_paused_path` (post-Resume fade-up) and
        `_running_fallback` (fade-up only). On completion or abort,
        clear `_runner` and call `_ended()`. Exceptions reach `_error()`.
        """
        try:
            completed = self._runner.run_until_complete()
            if not completed:
                return  # aborted — __stop__ handled state
        except Exception:
            logger.exception("ResumeCue: error during fade-up")
            self._error()
            return
        finally:
            self._runner = None

        self._ended()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `poetry run pytest tests/cues/test_resume_cue.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```
git add lisp/plugins/action_cues/resume_cue.py tests/cues/test_resume_cue.py
git commit -m "feat(resume-cue): running-target fallback fades up with no Resume"
```

---

## Task 5: Paused happy path — zero step, Resume dispatch, fade up

**Files:**
- Modify: `lisp/plugins/action_cues/resume_cue.py`
- Modify: `tests/cues/test_resume_cue.py`

This is the feature's main path: **target is Paused, duration > 0, faders exist**. We zero `live_volume` / `live_alpha` synchronously (so GStreamer reads gain=0 before any post-Resume samples flow), dispatch `CueAction.Resume`, then fade those same faders back up to `1.0`.

- [ ] **Step 1: Write failing tests for the Paused happy path**

Append to `tests/cues/test_resume_cue.py`:

```python
class TestPausedHappyPath:
    def _build_paused_media(self, mock_app, with_alpha=False):
        """Mock a paused MediaCue with volume (and optionally alpha) faders."""
        volume_fader = MagicMock(name="volume_fader")
        volume_fader.target = MagicMock()
        volume_fader.attribute = "live_volume"

        volume_el = MagicMock(name="volume_el")
        volume_el.get_fader.return_value = volume_fader

        alpha_fader = None
        alpha_el = None
        if with_alpha:
            alpha_fader = MagicMock(name="alpha_fader")
            alpha_fader.target = MagicMock()
            alpha_fader.attribute = "live_alpha"

            alpha_el = MagicMock(name="alpha_el")
            alpha_el.get_fader.return_value = alpha_fader

        target = MagicMock(spec=MediaCue)
        target.id = "t1"
        target.state = CueState.Pause
        target.media = MagicMock()
        target.media.element = lambda n: {
            "Volume": volume_el, "VideoAlpha": alpha_el,
        }.get(n)
        mock_app.cue_model.get.return_value = target

        return target, volume_fader, alpha_fader

    def test_paused_zero_then_resume_then_fade(self, mock_app, monkeypatch):
        """Happy path: zero live_volume, dispatch Resume, start runner."""
        target, vol_fader, _ = self._build_paused_media(mock_app)

        fake_runner = MagicMock()
        fake_runner.run_until_complete.return_value = True
        runner_cls = MagicMock()

        call_order = []

        def fake_rsetattr(obj, attr, value):
            call_order.append(("zero", obj, attr, value))
        monkeypatch.setattr(
            "lisp.plugins.action_cues.resume_cue.rsetattr", fake_rsetattr,
        )

        def fake_execute(action):
            call_order.append(("resume", action))
        target.execute.side_effect = fake_execute

        def fake_runner_init(*args, **kwargs):
            call_order.append(("runner_built",))
            return fake_runner
        runner_cls.side_effect = fake_runner_init
        monkeypatch.setattr(
            "lisp.plugins.action_cues.resume_cue.ParallelFadeRunner",
            runner_cls,
        )
        _patch_async_function_synchronous(monkeypatch)

        cue = ResumeCue(app=mock_app)
        cue.target_id = target.id
        cue.duration = 500

        result = cue.__start__()

        assert result is True
        # Zero was called before resume, resume before runner construction.
        kinds = [c[0] for c in call_order]
        assert kinds == ["zero", "resume", "runner_built"], kinds
        zero_call = call_order[0]
        assert zero_call[1] is vol_fader.target
        assert zero_call[2] == "live_volume"
        assert zero_call[3] == 0.0
        assert call_order[1] == ("resume", CueAction.Resume)
        fake_runner.run_until_complete.assert_called_once()

    def test_paused_zeros_both_volume_and_alpha(self, mock_app, monkeypatch):
        """VideoAlpha and Volume both zeroed when present."""
        target, vol_fader, alpha_fader = self._build_paused_media(
            mock_app, with_alpha=True,
        )

        fake_runner = MagicMock()
        fake_runner.run_until_complete.return_value = True
        monkeypatch.setattr(
            "lisp.plugins.action_cues.resume_cue.ParallelFadeRunner",
            MagicMock(return_value=fake_runner),
        )
        _patch_async_function_synchronous(monkeypatch)

        zero_calls = []
        monkeypatch.setattr(
            "lisp.plugins.action_cues.resume_cue.rsetattr",
            lambda obj, attr, val: zero_calls.append((obj, attr, val)),
        )

        cue = ResumeCue(app=mock_app)
        cue.target_id = target.id
        cue.duration = 500

        cue.__start__()

        assert len(zero_calls) == 2
        targets = [c[0] for c in zero_calls]
        attrs = [c[1] for c in zero_calls]
        vals = [c[2] for c in zero_calls]
        assert vol_fader.target in targets
        assert alpha_fader.target in targets
        assert set(attrs) == {"live_volume", "live_alpha"}
        assert vals == [0.0, 0.0]

    def test_paused_runner_targets_1_0_with_fade_in_curve(self, mock_app,
                                                         monkeypatch):
        """Runner is built with to_value=1.0 and FadeInType from property."""
        target, _, _ = self._build_paused_media(mock_app)

        runner_cls = MagicMock()
        fake_runner = MagicMock()
        fake_runner.run_until_complete.return_value = True
        runner_cls.return_value = fake_runner
        monkeypatch.setattr(
            "lisp.plugins.action_cues.resume_cue.ParallelFadeRunner",
            runner_cls,
        )
        _patch_async_function_synchronous(monkeypatch)
        monkeypatch.setattr(
            "lisp.plugins.action_cues.resume_cue.rsetattr",
            lambda *a, **kw: None,
        )

        cue = ResumeCue(app=mock_app)
        cue.target_id = target.id
        cue.duration = 1500
        cue.fade_type = "Quadratic"

        cue.__start__()

        runner_cls.assert_called_once()
        kwargs = runner_cls.call_args.kwargs
        assert kwargs["to_value"] == 1.0
        assert kwargs["curve"] == FadeInType.Quadratic
        assert kwargs["duration_seconds"] == 1.5

    def test_paused_group_cascade_single_resume_dispatch(self, mock_app,
                                                        monkeypatch):
        """GroupCue target: Resume dispatched once on the group, not per child."""
        from lisp.plugins.action_cues.group_cue import GroupCue

        def _make_child(cid):
            vol_fader = MagicMock()
            vol_fader.target = MagicMock()
            vol_fader.attribute = "live_volume"
            vol_el = MagicMock()
            vol_el.get_fader.return_value = vol_fader
            child = MagicMock(spec=MediaCue)
            child.id = cid
            child.state = CueState.Pause
            child.media = MagicMock()
            child.media.element = lambda n: vol_el if n == "Volume" else None
            return child, vol_fader

        child_a, _ = _make_child("a")
        child_b, _ = _make_child("b")

        group = MagicMock(spec=GroupCue)
        group.id = "g"
        group.state = CueState.Pause
        group._resolve_children.return_value = [child_a, child_b]
        mock_app.cue_model.get.return_value = group

        fake_runner = MagicMock()
        fake_runner.run_until_complete.return_value = True
        monkeypatch.setattr(
            "lisp.plugins.action_cues.resume_cue.ParallelFadeRunner",
            MagicMock(return_value=fake_runner),
        )
        _patch_async_function_synchronous(monkeypatch)
        monkeypatch.setattr(
            "lisp.plugins.action_cues.resume_cue.rsetattr",
            lambda *a, **kw: None,
        )

        cue = ResumeCue(app=mock_app)
        cue.target_id = group.id
        cue.duration = 500

        cue.__start__()

        group.execute.assert_called_once_with(CueAction.Resume)
        child_a.execute.assert_not_called()
        child_b.execute.assert_not_called()

    def test_paused_no_faders_dispatches_resume_without_fade(self, mock_app):
        """Non-media or no-volume paused target: Resume dispatched, no fade."""
        target = MagicMock(spec=MediaCue)
        target.id = "t1"
        target.state = CueState.Pause
        target.media = MagicMock()
        target.media.element.return_value = None
        mock_app.cue_model.get.return_value = target

        cue = ResumeCue(app=mock_app)
        cue.target_id = target.id
        cue.duration = 500

        result = cue.__start__()

        target.execute.assert_called_once_with(CueAction.Resume)
        assert result is False  # no async work scheduled
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `poetry run pytest tests/cues/test_resume_cue.py::TestPausedHappyPath -v`
Expected: FAIL — `_paused_path` still returns False.

- [ ] **Step 3: Implement `_paused_path`**

Replace the `_paused_path` stub in `lisp/plugins/action_cues/resume_cue.py`:

```python
    def _paused_path(self, target):
        """Target is Paused — zero faders, Resume, fade back up to 1.0."""
        affected = build_affected_set(target)
        faders = collect_live_faders(
            affected, states=CueState.Pause | CueState.IsRunning,
        )

        will_fade = self.duration > 0 and faders

        if will_fade:
            # Zero each fader's live property synchronously BEFORE dispatching
            # Resume, so the GStreamer pipeline reads gain=0 for the first
            # samples post-Resume. Prevents pops regardless of how the
            # target was paused (e.g. a plain Pause rather than a prior
            # Fade & Stop).
            for fader in faders:
                rsetattr(fader.target, fader.attribute, 0.0)

        target.execute(CueAction.Resume)

        if not will_fade:
            return False

        self._runner = ParallelFadeRunner(
            faders=faders,
            to_value=1.0,
            curve=FadeInType[self.fade_type],
            duration_seconds=self.duration / 1000,
        )
        self._run_fade(target=target)
        return True
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `poetry run pytest tests/cues/test_resume_cue.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```
git add lisp/plugins/action_cues/resume_cue.py tests/cues/test_resume_cue.py
git commit -m "feat(resume-cue): zero faders, dispatch Resume, fade up on paused target"
```

---

## Task 6: `duration == 0` on Paused target — skip zero step

**Files:**
- Modify: `tests/cues/test_resume_cue.py`

The Paused path already handles `duration == 0` correctly (via `will_fade = False` -> skip zero + dispatch Resume + return False). Lock that behaviour in with an explicit regression test so the invariant survives future refactors.

- [ ] **Step 1: Write failing test for `duration == 0` semantics**

Append to `tests/cues/test_resume_cue.py`:

```python
class TestPausedDurationZero:
    def test_paused_duration_zero_skips_zero_step(self, mock_app, monkeypatch):
        """duration=0 on a paused target: no zero step (otherwise silent cue)."""
        volume_fader = MagicMock()
        volume_fader.target = MagicMock()
        volume_fader.attribute = "live_volume"

        volume_el = MagicMock()
        volume_el.get_fader.return_value = volume_fader

        target = MagicMock(spec=MediaCue)
        target.id = "t1"
        target.state = CueState.Pause
        target.media = MagicMock()
        target.media.element = lambda n: volume_el if n == "Volume" else None
        mock_app.cue_model.get.return_value = target

        zero_calls = []
        monkeypatch.setattr(
            "lisp.plugins.action_cues.resume_cue.rsetattr",
            lambda obj, attr, val: zero_calls.append((obj, attr, val)),
        )

        cue = ResumeCue(app=mock_app)
        cue.target_id = target.id
        cue.duration = 0

        result = cue.__start__()

        # Zero step skipped — target resumes at its existing live_volume.
        assert zero_calls == []
        # Resume still dispatched.
        target.execute.assert_called_once_with(CueAction.Resume)
        # No async work.
        assert result is False
```

- [ ] **Step 2: Run test to confirm it already passes**

Run: `poetry run pytest tests/cues/test_resume_cue.py::TestPausedDurationZero -v`
Expected: PASS (this is a locked-in regression test on Task 5's logic).

If it fails, the `will_fade` guard in `_paused_path` is broken — fix before proceeding.

- [ ] **Step 3: Commit**

```
git add tests/cues/test_resume_cue.py
git commit -m "test(resume-cue): lock in duration=0 skips zero step on paused target"
```

---

## Task 7: Abort in-flight runner on `__stop__` / `__interrupt__`

**Files:**
- Modify: `lisp/plugins/action_cues/resume_cue.py`
- Modify: `tests/cues/test_resume_cue.py`

- [ ] **Step 1: Write failing tests for abort**

Append to `tests/cues/test_resume_cue.py`:

```python
class TestAbort:
    def test_stop_aborts_runner_when_present(self, mock_app):
        cue = ResumeCue(app=mock_app)
        cue._runner = MagicMock()

        result = cue.__stop__()

        cue._runner.abort.assert_called_once()
        assert result is True

    def test_interrupt_aborts_runner_when_present(self, mock_app):
        cue = ResumeCue(app=mock_app)
        cue._runner = MagicMock()

        cue.__interrupt__()

        cue._runner.abort.assert_called_once()

    def test_stop_without_runner_is_safe(self, mock_app):
        """No in-flight fade: __stop__ must not crash."""
        cue = ResumeCue(app=mock_app)
        assert cue._runner is None
        assert cue.__stop__() is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `poetry run pytest tests/cues/test_resume_cue.py::TestAbort -v`
Expected: FAIL — `__stop__` / `__interrupt__` inherit base behaviour.

- [ ] **Step 3: Add `__stop__` and `__interrupt__`**

Append to `lisp/plugins/action_cues/resume_cue.py`:

```python
    def __stop__(self, fade=False):
        """Cancel the in-flight fade, if any.

        Does NOT re-pause the target — "I changed my mind about fading in"
        does not mean "put the target back where it was". The target stays
        wherever the partial fade-up left it.
        """
        runner = self._runner
        if runner is not None:
            runner.abort()
        return True

    __interrupt__ = __stop__
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `poetry run pytest tests/cues/test_resume_cue.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```
git add lisp/plugins/action_cues/resume_cue.py tests/cues/test_resume_cue.py
git commit -m "feat(resume-cue): abort the in-flight runner on stop/interrupt"
```

---

## Task 8: Settings page (`ResumeCueSettings`) and registry

**Files:**
- Modify: `lisp/plugins/action_cues/resume_cue.py`
- Modify: `tests/cues/test_resume_cue.py`

- [ ] **Step 1: Write failing tests for the settings page**

Append to `tests/cues/test_resume_cue.py`:

```python
class TestResumeCueSettings:
    """Settings-page round-trip. Requires QApplication via qapp fixture."""

    def test_get_settings_empty_when_groups_disabled(self, qapp):
        from lisp.plugins.action_cues.resume_cue import ResumeCueSettings

        page = ResumeCueSettings()
        page.enableCheck(False)
        assert page.getSettings() == {}

    def test_load_then_get_round_trip(self, qapp, monkeypatch):
        from lisp.plugins.action_cues.resume_cue import ResumeCueSettings

        fake_target = MagicMock()
        fake_target.name = "Target Cue"
        monkeypatch.setattr(
            "lisp.plugins.action_cues.resume_cue.Application",
            lambda: MagicMock(cue_model=MagicMock(
                get=lambda _id: fake_target, filter=lambda *_: [],
            )),
        )

        page = ResumeCueSettings()
        page.enableCheck(True)
        page.loadSettings({
            "target_id": "abc",
            "duration": 2500,
            "fade_type": "Linear",
        })

        settings = page.getSettings()
        assert settings["target_id"] == "abc"
        assert settings["duration"] == 2500
        assert settings["fade_type"] == "Linear"

    def test_no_action_key_in_settings(self, qapp, monkeypatch):
        """ResumeCueSettings never stores an `action` key — verb is fixed."""
        from lisp.plugins.action_cues.resume_cue import ResumeCueSettings

        monkeypatch.setattr(
            "lisp.plugins.action_cues.resume_cue.Application",
            lambda: MagicMock(cue_model=MagicMock(
                get=lambda _id: None, filter=lambda *_: [],
            )),
        )

        page = ResumeCueSettings()
        page.enableCheck(True)
        settings = page.getSettings()
        assert "action" not in settings

    def test_registry_association(self):
        from lisp.ui.settings.cue_settings import CueSettingsRegistry
        from lisp.plugins.action_cues.resume_cue import (
            ResumeCue, ResumeCueSettings,
        )

        pages = [
            p for p, cls in CueSettingsRegistry().filter(ResumeCue)
            if cls is ResumeCueSettings
        ]
        assert pages, "ResumeCueSettings not registered for ResumeCue"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `poetry run pytest tests/cues/test_resume_cue.py::TestResumeCueSettings -v`
Expected: FAIL — `ResumeCueSettings` does not exist.

- [ ] **Step 3: Add `ResumeCueSettings` and registry wiring**

Update the imports block at the top of `lisp/plugins/action_cues/resume_cue.py` to add what the settings page needs:

```python
# Add to the existing imports:
from PyQt5.QtCore import QT_TRANSLATE_NOOP, Qt
from PyQt5.QtWidgets import QGroupBox, QLabel, QPushButton, QVBoxLayout

from lisp.application import Application
from lisp.ui.cuelistdialog import CueSelectDialog
from lisp.ui.settings.cue_settings import CueSettingsRegistry
from lisp.ui.settings.pages import SettingsPage
from lisp.ui.widgets import FadeEdit
from lisp.ui.widgets.fades import FadeComboBox
```

Append the settings class and registry call at the bottom of the file:

```python
class ResumeCueSettings(SettingsPage):
    Name = QT_TRANSLATE_NOOP("SettingsPageName", "Fade & Resume Settings")
    SortOrder = 30  # Matches StopCueSettings so both sort together.

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.setLayout(QVBoxLayout())
        self.layout().setAlignment(Qt.AlignTop)

        self.cue_id = ""
        self.cueDialog = CueSelectDialog(
            cues=Application().cue_model.filter(Cue), parent=self,
        )

        # Target-cue selector
        self.cueGroup = QGroupBox(self)
        self.cueGroup.setLayout(QVBoxLayout())
        self.layout().addWidget(self.cueGroup)

        self.cueLabel = QLabel(self.cueGroup)
        self.cueLabel.setAlignment(Qt.AlignCenter)
        self.cueLabel.setStyleSheet("font-weight: bold;")
        self.cueGroup.layout().addWidget(self.cueLabel)

        self.cueButton = QPushButton(self.cueGroup)
        self.cueButton.clicked.connect(self.select_cue)
        self.cueGroup.layout().addWidget(self.cueButton)

        # Fade settings — FadeIn mode so the combo icons match the verb.
        self.fadeGroup = QGroupBox(self)
        self.fadeGroup.setLayout(QVBoxLayout())
        self.layout().addWidget(self.fadeGroup)

        self.fadeEdit = FadeEdit(
            self.fadeGroup, mode=FadeComboBox.Mode.FadeIn,
        )
        self.fadeGroup.layout().addWidget(self.fadeEdit)

        self.retranslateUi()

    def retranslateUi(self):
        self.cueGroup.setTitle(translate("ResumeCue", "Cue"))
        self.cueButton.setText(translate("ResumeCue", "Click to select"))
        self.cueLabel.setText(translate("ResumeCue", "Not selected"))
        self.fadeGroup.setTitle(translate("ResumeCue", "Fade"))

    def select_cue(self):
        if self.cueDialog.exec() == self.cueDialog.Accepted:
            selected = self.cueDialog.selected_cue()
            if selected is not None:
                self.cue_id = selected.id
                self.cueLabel.setText(selected.name)

    def enableCheck(self, enabled):
        self.setGroupEnabled(self.cueGroup, enabled)
        self.setGroupEnabled(self.fadeGroup, enabled)

    def getSettings(self):
        settings = {}
        if self.isGroupEnabled(self.cueGroup):
            settings["target_id"] = self.cue_id
        if self.isGroupEnabled(self.fadeGroup):
            settings["duration"] = int(self.fadeEdit.duration() * 1000)
            settings["fade_type"] = self.fadeEdit.fadeType()
        return settings

    def loadSettings(self, settings):
        target = Application().cue_model.get(settings.get("target_id", ""))
        if target is not None:
            self.cue_id = settings["target_id"]
            self.cueLabel.setText(target.name)

        self.fadeEdit.setDuration(settings.get("duration", 0) / 1000)
        self.fadeEdit.setFadeType(
            settings.get("fade_type", FadeInType.Linear.name)
        )


CueSettingsRegistry().add(ResumeCueSettings, ResumeCue)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `poetry run pytest tests/cues/test_resume_cue.py -v`
Expected: PASS.

Also sanity-check the module imports cleanly:
Run: `poetry run python -c "from lisp.plugins.action_cues.resume_cue import ResumeCue, ResumeCueSettings; print('ok')"`
Expected: prints `ok` with no tracebacks.

- [ ] **Step 5: Commit**

```
git add lisp/plugins/action_cues/resume_cue.py tests/cues/test_resume_cue.py
git commit -m "feat(resume-cue): add ResumeCueSettings with target + fade-in UI"
```

---

## Task 9: Regenerate i18n translation templates

**Files:**
- Modify: `lisp/i18n/ts/*.ts` (auto-generated)

- [ ] **Step 1: Run the i18n updater**

Run: `python i18n_update.py`
Expected: updated `.ts` files containing new contexts: `CueName` ("Fade & Resume"), `SettingsPageName` ("Fade & Resume Settings"), `ResumeCue` ("Cue", "Click to select", "Not selected", "Fade").

- [ ] **Step 2: Verify only expected files changed**

Run: `git status --short` and confirm the diff touches only `lisp/i18n/ts/`.

- [ ] **Step 3: Commit**

```
git add lisp/i18n/ts/
git commit -m "i18n: regenerate translations for Fade & Resume strings"
```

---

## Task 10: E2E — full intermission workflow (Stop then Resume)

**Files:**
- Create: `tests/e2e/test_fade_and_resume_e2e.py`

- [ ] **Step 1: Confirm no LiSP is already using the harness port**

Run: `pgrep -af 'lisp.main' || echo "none"`
Expected: `none`. Port-clash detection — see memory `feedback_e2e_port_clash`.

- [ ] **Step 2: Write the E2E suite**

Create `tests/e2e/test_fade_and_resume_e2e.py`:

```python
#!/usr/bin/env python3
"""E2E tests for Fade & Resume (ResumeCue).

Covers:
    1. Full intermission workflow: media -> Fade & Stop (pause) -> Fade & Resume.
    2. Non-media target: Resume dispatched, no fade needed.
    3. Mid-fade abort on the ResumeCue.

Run:
    poetry run python tests/e2e/test_fade_and_resume_e2e.py
"""

import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from tests.e2e.helpers import (  # noqa: E402
    run_suite, call, cue_state, cue_prop, wait_state, stop_all,
    setup_with_tones, cue_signal, wait_for_signal,
)


def _add_stop_cue(target_id, duration_ms=0, fade_type="Linear"):
    return call("cue.add", {
        "type": "StopCue",
        "properties": {
            "target_id": target_id,
            "action": "Pause",
            "duration": duration_ms,
            "fade_type": fade_type,
        },
    })["id"]


def _add_resume_cue(target_id, duration_ms=0, fade_type="Linear"):
    return call("cue.add", {
        "type": "ResumeCue",
        "properties": {
            "target_id": target_id,
            "duration": duration_ms,
            "fade_type": fade_type,
        },
    })["id"]


def test_1_intermission_workflow(t, ids):
    """Media starts -> StopCue pauses it -> ResumeCue resumes and fades up."""
    print("\n=== Test 1: Intermission workflow (Stop then Resume) ===")
    stop_all()

    target = ids["tone_A"]
    sfr_stop = _add_stop_cue(target, duration_ms=300)
    sfr_resume = _add_resume_cue(target, duration_ms=500)

    call("cue.execute", {"id": target, "action": "Start"})
    assert wait_state(target, "Running"), "target failed to start"

    with cue_signal(target, "paused") as sub:
        call("cue.execute", {"id": sfr_stop, "action": "Start"})
        ev = wait_for_signal(sub, timeout=3.0)

    t.check("target paused by Fade & Stop", ev is not None)
    t.check(
        "live_volume near 0 after fade-out",
        cue_prop(target, "media.elements.Volume.live_volume") < 0.05,
    )

    with cue_signal(target, "started") as sub:
        call("cue.execute", {"id": sfr_resume, "action": "Start"})
        ev = wait_for_signal(sub, timeout=3.0)

    t.check("target received started signal from Resume", ev is not None)
    t.check("target back in Running state", cue_state(target) == "Running")

    # Poll live_volume at ~250ms and ~550ms (fade is 500ms).
    vol_mid = None
    vol_end = None
    t0 = time.time()
    while time.time() - t0 < 0.7:
        elapsed = time.time() - t0
        if vol_mid is None and elapsed >= 0.25:
            vol_mid = cue_prop(target, "media.elements.Volume.live_volume")
        if elapsed >= 0.55:
            vol_end = cue_prop(target, "media.elements.Volume.live_volume")
            break
        time.sleep(0.02)

    t.check(
        f"live_volume rising at ~250ms (got {vol_mid})",
        vol_mid is not None and 0.1 < vol_mid < 0.9,
    )
    t.check(
        f"live_volume near 1.0 after fade (got {vol_end})",
        vol_end is not None and vol_end > 0.9,
    )


def test_2_non_media_target_graceful(t, ids):
    """ResumeCue on a paused non-media target: Resume dispatched, no fade."""
    print("\n=== Test 2: Non-media target ===")
    stop_all()

    cmd = call("cue.add", {
        "type": "CommandCue",
        "properties": {"command": "sleep 30", "no_output": True},
    })["id"]

    call("cue.execute", {"id": cmd, "action": "Start"})
    assert wait_state(cmd, "Running")

    call("cue.execute", {"id": cmd, "action": "Pause"})
    assert wait_state(cmd, "Pause")

    sfr_resume = _add_resume_cue(cmd, duration_ms=200)

    with cue_signal(cmd, "started") as sub:
        call("cue.execute", {"id": sfr_resume, "action": "Start"})
        ev = wait_for_signal(sub, timeout=2.0)

    t.check("non-media target received Resume", ev is not None)

    call("cue.execute", {"id": cmd, "action": "Stop"})


def test_3_abort_midfade_keeps_target_running(t, ids):
    """Stopping the ResumeCue mid-fade leaves target running at partial volume."""
    print("\n=== Test 3: Abort mid-fade-up ===")
    stop_all()

    target = ids["tone_A"]
    sfr_stop = _add_stop_cue(target, duration_ms=100)
    sfr_resume = _add_resume_cue(target, duration_ms=3000)

    call("cue.execute", {"id": target, "action": "Start"})
    assert wait_state(target, "Running")
    with cue_signal(target, "paused") as sub:
        call("cue.execute", {"id": sfr_stop, "action": "Start"})
        wait_for_signal(sub, timeout=2.0)

    call("cue.execute", {"id": sfr_resume, "action": "Start"})
    time.sleep(0.4)  # let the fade-up begin
    call("cue.execute", {"id": sfr_resume, "action": "Stop"})
    time.sleep(0.2)

    t.check(
        "target still Running after ResumeCue abort",
        cue_state(target) == "Running",
    )
    vol = cue_prop(target, "media.elements.Volume.live_volume")
    t.check(
        f"live_volume at partial value (got {vol})",
        0.05 < vol < 0.95,
    )


# -- Entry --

def run_tests(t):
    ids = setup_with_tones()
    test_1_intermission_workflow(t, ids)
    test_2_non_media_target_graceful(t, ids)
    test_3_abort_midfade_keeps_target_running(t, ids)


if __name__ == "__main__":
    run_suite("Fade & Resume E2E", run_tests)
```

- [ ] **Step 3: Run the suite**

Run: `poetry run python tests/e2e/test_fade_and_resume_e2e.py`
Expected: all 3 tests pass; summary reports `PASSED: 3`, `FAILED: 0`.

If any test fails, diagnose and fix either the implementation or the test assertions before moving on. Do not claim the suite can't be run — it works fine in this environment (see memory `feedback_always_run_e2e`).

- [ ] **Step 4: Commit**

```
git add tests/e2e/test_fade_and_resume_e2e.py
git commit -m "test(resume-cue): e2e intermission workflow (stop-then-resume)"
```

---

## Task 11: Full regression sweep

**Files:** (none modified unless a regression surfaces)

- [ ] **Step 1: Run full unit-test suite**

Run: `poetry run pytest tests/ -v`
Expected: no failures. In particular, Part 1's `test_stop_cue.py` and `test_fader_coordinator.py` must still pass — ResumeCue is additive.

- [ ] **Step 2: Run all E2E suites that could have drifted**

```
poetry run python tests/e2e/test_fade_and_stop_e2e.py
poetry run python tests/e2e/test_fade_and_resume_e2e.py
poetry run python tests/e2e/test_volume_control_e2e.py
poetry run python tests/e2e/test_groups_e2e.py
poetry run python tests/e2e/test_global_controls_e2e.py
```

Expected: each reports `FAILED: 0`.

- [ ] **Step 3: Run Ruff on new files**

Run: `poetry run ruff check lisp/plugins/action_cues/resume_cue.py tests/cues/test_resume_cue.py tests/e2e/test_fade_and_resume_e2e.py`
Expected: clean. Fix any violations inline and commit.

---

## Task 12: QA review via subagent

**Files:** (may produce fixes as follow-up edits)

- [ ] **Step 1: Dispatch the QA expert**

Use the `Agent` tool with `subagent_type="voltagent-qa-sec:qa-expert"` and this prompt:

> Review the Fade & Resume cue implementation against its spec and roadmap,
> including the symmetry with Fade & Stop (Part 1).
>
> - Part 2 spec: `docs/specs/2026-04-21-fade-and-resume-cue-design.md`
> - Part 1 spec (for symmetry context): `docs/specs/2026-04-18-fade-and-stop-cue-design.md`
> - Roadmap: `docs/specs/2026-04-18-sfr-workflow-roadmap.md`
> - Plan: `plans/08-fade-and-resume-cue.md`
> - Implementation: `lisp/plugins/action_cues/resume_cue.py`
> - Shared helper (from Part 1): `lisp/plugins/action_cues/_fader_coordinator.py`
> - Unit tests: `tests/cues/test_resume_cue.py`
> - E2E tests: `tests/e2e/test_fade_and_resume_e2e.py`
>
> Assess:
> 1. Target-state branch coverage: all four of the spec's target-state
>    cases (Paused, Running, PreWait/PostWait, Stopped/Error) tested with
>    the right behaviour?
> 2. Zero-step correctness: is the ordering (zero -> Resume -> fade-up)
>    asserted and the skip-when-duration=0 branch covered?
> 3. Mixed-state group coverage: paused+stopped children — does the test
>    suite reflect the "best-effort" expectation from the spec?
> 4. End-to-end intermission workflow (media paused then resumed) works
>    from an operator's perspective.
> 5. Cross-plugin interactions not yet asserted (MIDI/OSC triggering the
>    ResumeCue, timecode, presets). Any missing failure modes (target
>    deleted during fade, two ResumeCues concurrent)?
>
> Report only high-confidence issues. Return a prioritised punch list
> under 300 words.

- [ ] **Step 2: Triage findings**

For each reported issue:
- Spec gap: add a TODO to the roadmap's Part 2 checklist and resolve before marking Task 14 complete.
- Missing test: add the test and re-run Task 11.
- False positive: record rationale inline; no code change.

- [ ] **Step 3: Commit any resulting changes**

```
git add <changed-files>
git commit -m "test(resume-cue): address QA review findings"
```

(Skip if no changes.)

---

## Task 13: Code review via subagent

**Files:** (may produce fixes)

- [ ] **Step 1: Dispatch the code-reviewer**

Use the `Agent` tool with `subagent_type="voltagent-qa-sec:code-reviewer"` and this prompt:

> Review the Fade & Resume cue code for correctness, convention fit, and
> thread safety. Symmetry with Fade & Stop (Part 1) matters — gratuitous
> divergence between StopCue and ResumeCue should be flagged.
>
> - Implementation: `lisp/plugins/action_cues/resume_cue.py`
> - Shared helper (for context): `lisp/plugins/action_cues/_fader_coordinator.py`
> - Reference: `lisp/plugins/action_cues/stop_cue.py` (symmetry partner),
>   `lisp/plugins/action_cues/volume_control.py` (single-target fade pattern),
>   `lisp/plugins/action_cues/group_cue.py:163-228` (Resume cascade).
> - Spec: `docs/specs/2026-04-21-fade-and-resume-cue-design.md`
>
> Specifically check:
> 1. Correctness against spec: every branch in the target-state policy
>    lands in code; zero step fires before Resume, not after; zero step
>    skipped when `duration == 0`.
> 2. LiSP conventions: signal/fader/property usage mirrors
>    `volume_control.py` and `stop_cue.py`; translation contexts sensible;
>    registry wiring correct.
> 3. Thread safety: `rsetattr` on `fader.target` before `ParallelFadeRunner`
>    — is there a race where the runner's `prepare()` (which calls
>    `fader.stop()`) could reset the value we just zeroed? Confirm the
>    sequence is safe. Any Qt-main-thread violations in `_run_fade`?
> 4. Resource cleanup: `self._runner` cleared on abort, error, and
>    natural completion. No leaks if `_run_fade` raises.
> 5. Symmetry with StopCue: is there duplicated logic that should live
>    in the coordinator instead? Is the `_run_fade` helper a near-copy
>    of StopCue's `_run_fade_then_action`? If so, is the duplication
>    acceptable (because the dispatch-then-fade ordering differs) or
>    should it be unified?
> 6. Edge cases from the spec: missing target logged+errored; mixed-state
>    group handled correctly; PreWait treated as Running; Error target
>    errors.
>
> Report only high-confidence issues. Return a prioritised punch list
> under 300 words.

- [ ] **Step 2: Triage findings**

Same triage rules as Task 12. Fixes go into `lisp/plugins/action_cues/resume_cue.py`; re-run Task 11 after each.

- [ ] **Step 3: Commit any resulting changes**

```
git add lisp/plugins/action_cues/resume_cue.py tests/
git commit -m "refactor(resume-cue): address code review findings"
```

(Skip if no changes.)

---

## Task 14: Close out Part 2 and update roadmap

**Files:**
- Modify: `docs/specs/2026-04-18-sfr-workflow-roadmap.md`

- [ ] **Step 1: Tick Part 2 boxes**

In `docs/specs/2026-04-18-sfr-workflow-roadmap.md`, mark Part 2 complete:

```
- [x] Brainstorm
- [x] Spec
- [x] Retrofit Part 1 plan to use `_fader_coordinator`
- [x] Write Part 2 implementation plan
- [x] Implement `_fader_coordinator` + `ResumeCue` + `ResumeCueSettings`
- [x] Unit tests (coordinator + ResumeCue + updated StopCue tests)
- [x] E2E test — full intermission workflow (Stop then Resume)
- [x] QA review (`voltagent-qa-sec:qa-expert`)
- [x] Code review (`voltagent-qa-sec:code-reviewer`)
```

Also change the Part 2 status line from `— **in progress**` to `— **complete**`.

- [ ] **Step 2: Verify the full test sweep still passes**

Run:
```
poetry run pytest tests/ -q
poetry run python tests/e2e/test_fade_and_stop_e2e.py
poetry run python tests/e2e/test_fade_and_resume_e2e.py
```
Expected: all green.

- [ ] **Step 3: Final commit**

```
git add docs/specs/2026-04-18-sfr-workflow-roadmap.md
git commit -m "docs(spec): mark Part 2 (Fade & Resume) complete in SFR roadmap"
```

- [ ] **Step 4: Push and (optionally) open a PR — only if the user explicitly requests it**

Skip unless the user explicitly asks. If requested:

```
git push -u origin <branch>
gh pr create --title "feat: Fade & Resume cue (Part 2/3 of SFR workflow)" --body "..."
```
