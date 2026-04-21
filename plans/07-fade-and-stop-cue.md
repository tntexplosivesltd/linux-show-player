# Fade & Stop Cue Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `StopCue` action cue ("Fade & Stop") that targets a single cue (including `GroupCue` for cascading), runs its own `live_volume` + `live_alpha` faders over a user-supplied duration, then dispatches `Stop`/`Pause`/`Interrupt`.

**Architecture:** New file `lisp/plugins/action_cues/stop_cue.py` mirroring `volume_control.py`. Reuses LiSP's existing fader infrastructure (`Fader` from `lisp/core/fader.py`) and the `get_fader()` API on `Volume` and `VideoAlpha` GStreamer elements. No core changes — the feature composes existing pieces. A coordinator method decorated with `@async_function` spawns one sub-thread per fader, joins them, then calls `target.execute(action)` from the worker thread (matching `VolumeControl.__fade` threading semantics).

**Tech Stack:** Python 3.9+, PyQt5, LiSP `Property` / `Cue` / `Fader` / `@async_function`, GStreamer element faders, pytest + pytest-qt for unit tests, JSON-RPC test_harness for E2E.

**Spec:** `docs/specs/2026-04-18-fade-and-stop-cue-design.md`

**Roadmap:** `docs/specs/2026-04-18-sfr-workflow-roadmap.md` (Part 1 of 3)

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `lisp/plugins/action_cues/stop_cue.py` | Create | `StopCue` class, `StopCueSettings` page, registry wiring |
| `lisp/i18n/ts/*.ts` | Regenerate | New `QT_TRANSLATE_NOOP` strings for "Fade & Stop", action combo, UI labels |
| `tests/cues/test_stop_cue.py` | Create | Unit tests: properties, target resolution, affected-set, fader collection, fade-then-action coordinator, abort |
| `tests/e2e/test_fade_and_stop_e2e.py` | Create | E2E suite via `test_harness`: single-target, group fan-out, mid-fade abort, non-media target |
| `docs/specs/2026-04-18-sfr-workflow-roadmap.md` | Modify | Tick Part 1 checkboxes at the end |

---

## Task 1: Scaffold `StopCue` class with default properties

**Files:**
- Create: `lisp/plugins/action_cues/stop_cue.py`
- Create: `tests/cues/test_stop_cue.py`

- [ ] **Step 1: Write failing test for class existence and defaults**

Create `tests/cues/test_stop_cue.py`:

```python
"""Unit tests for StopCue (Fade & Stop) action cue."""
import pytest
from unittest.mock import MagicMock

from lisp.core.fade_functions import FadeOutType
from lisp.cues.cue import CueAction
from lisp.plugins.action_cues.stop_cue import StopCue


class TestStopCueDefaults:
    def test_class_display_name(self):
        assert StopCue.Name == "Fade & Stop"

    def test_class_category(self):
        assert StopCue.Category == "Action cues"

    def test_class_supported_actions(self):
        assert CueAction.Default in StopCue.CueActions
        assert CueAction.Start in StopCue.CueActions
        assert CueAction.Stop in StopCue.CueActions
        assert CueAction.Interrupt in StopCue.CueActions

    def test_default_target_id(self, mock_app):
        cue = StopCue(app=mock_app)
        assert cue.target_id is None or cue.target_id == ""

    def test_default_action(self, mock_app):
        cue = StopCue(app=mock_app)
        assert cue.action == CueAction.Stop.value

    def test_default_fade_type(self, mock_app):
        cue = StopCue(app=mock_app)
        assert cue.fade_type == FadeOutType.Linear.name

    def test_default_duration_zero(self, mock_app):
        cue = StopCue(app=mock_app)
        assert cue.duration == 0

    def test_default_icon(self, mock_app):
        cue = StopCue(app=mock_app)
        assert cue.icon == "action-stop"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `poetry run pytest tests/cues/test_stop_cue.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'lisp.plugins.action_cues.stop_cue'`

- [ ] **Step 3: Create the minimal `StopCue` class**

Create `lisp/plugins/action_cues/stop_cue.py`:

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
from threading import Thread

from PyQt5.QtCore import QT_TRANSLATE_NOOP

from lisp.core.decorators import async_function
from lisp.core.fade_functions import FadeOutType
from lisp.core.properties import Property
from lisp.cues.cue import Cue, CueAction, CueState
from lisp.cues.media_cue import MediaCue
from lisp.ui.ui_utils import translate

logger = logging.getLogger(__name__)


class StopCue(Cue):
    Name = QT_TRANSLATE_NOOP("CueName", "Fade & Stop")
    Category = QT_TRANSLATE_NOOP("CueCategory", "Action cues")

    target_id = Property()
    action = Property(default=CueAction.Stop.value)
    fade_type = Property(default=FadeOutType.Linear.name)
    icon = Property(default="action-stop")

    CueActions = (
        CueAction.Default,
        CueAction.Start,
        CueAction.Stop,
        CueAction.Interrupt,
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = translate("CueName", self.Name)

        # Faders currently running for abort support.
        self._active_faders = []
        self._aborted = False
```

- [ ] **Step 4: Run test to verify it passes**

Run: `poetry run pytest tests/cues/test_stop_cue.py -v`
Expected: PASS (all 8 tests)

- [ ] **Step 5: Commit**

```
git add lisp/plugins/action_cues/stop_cue.py tests/cues/test_stop_cue.py
git commit -m "feat(stop-cue): scaffold StopCue with default properties"
```

---

## Task 2: Target resolution and missing-target error path

**Files:**
- Modify: `lisp/plugins/action_cues/stop_cue.py`
- Modify: `tests/cues/test_stop_cue.py`

- [ ] **Step 1: Write failing tests for target resolution**

Append to `tests/cues/test_stop_cue.py`:

```python
class TestTargetResolution:
    def test_missing_target_logs_and_errors(self, mock_app, caplog):
        mock_app.cue_model.get.return_value = None
        cue = StopCue(app=mock_app)
        cue.target_id = "does-not-exist"

        error_fired = []
        cue.error.connect(lambda *_: error_fired.append(True))

        result = cue.__start__()

        assert result is False
        assert error_fired == [True]
        assert any("target" in r.message.lower() for r in caplog.records)

    def test_empty_target_id_logs_and_errors(self, mock_app):
        mock_app.cue_model.get.return_value = None
        cue = StopCue(app=mock_app)
        cue.target_id = ""

        error_fired = []
        cue.error.connect(lambda *_: error_fired.append(True))

        result = cue.__start__()

        assert result is False
        assert error_fired == [True]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `poetry run pytest tests/cues/test_stop_cue.py::TestTargetResolution -v`
Expected: FAIL — the inherited `Cue.__start__` returns True; we need to override.

- [ ] **Step 3: Add `__start__` with target resolution**

Append to `lisp/plugins/action_cues/stop_cue.py`:

```python
    def __start__(self, fade=False):
        target = self.app.cue_model.get(self.target_id)
        if target is None:
            logger.warning(
                "StopCue: target cue %r not found", self.target_id
            )
            self._error()
            return False

        # Affected-set assembly, fader collection, and fade-then-action
        # are added in subsequent tasks.
        return False
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `poetry run pytest tests/cues/test_stop_cue.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```
git add lisp/plugins/action_cues/stop_cue.py tests/cues/test_stop_cue.py
git commit -m "feat(stop-cue): resolve target_id and error on missing target"
```

---

## Task 3: Affected-set assembly (single, group, nested group)

**Files:**
- Modify: `lisp/plugins/action_cues/stop_cue.py`
- Modify: `tests/cues/test_stop_cue.py`

- [ ] **Step 1: Write failing tests for affected-set**

Append to `tests/cues/test_stop_cue.py`:

```python
from lisp.plugins.action_cues.group_cue import GroupCue


class TestAffectedSet:
    def _make_media_cue(self, cue_id="media-1"):
        cue = MagicMock(spec=MediaCue)
        cue.id = cue_id
        cue.state = CueState.Stop
        return cue

    def test_single_media_target(self, mock_app):
        target = self._make_media_cue()
        cue = StopCue(app=mock_app)
        affected = cue._build_affected_set(target)
        assert affected == [target]

    def test_group_target_flattens_children(self, mock_app):
        child_a = self._make_media_cue("a")
        child_b = self._make_media_cue("b")
        group = MagicMock(spec=GroupCue)
        group.id = "g1"
        group._resolve_children.return_value = [child_a, child_b]

        cue = StopCue(app=mock_app)
        affected = cue._build_affected_set(group)
        assert affected == [child_a, child_b]

    def test_nested_group_flattens_recursively(self, mock_app):
        leaf_a = self._make_media_cue("a")
        leaf_b = self._make_media_cue("b")

        inner = MagicMock(spec=GroupCue)
        inner.id = "inner"
        inner._resolve_children.return_value = [leaf_a, leaf_b]

        outer = MagicMock(spec=GroupCue)
        outer.id = "outer"
        outer._resolve_children.return_value = [inner]

        cue = StopCue(app=mock_app)
        affected = cue._build_affected_set(outer)
        assert affected == [leaf_a, leaf_b]

    def test_non_running_included_in_affected_set(self, mock_app):
        """_build_affected_set does NOT filter by state; the filter
        lives in the fader-collection step so the action still fires
        on all children via the group cascade."""
        child = self._make_media_cue("stopped")
        child.state = CueState.Stop
        group = MagicMock(spec=GroupCue)
        group.id = "g1"
        group._resolve_children.return_value = [child]

        cue = StopCue(app=mock_app)
        affected = cue._build_affected_set(group)
        assert affected == [child]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `poetry run pytest tests/cues/test_stop_cue.py::TestAffectedSet -v`
Expected: FAIL — `_build_affected_set` does not exist.

- [ ] **Step 3: Add `_build_affected_set`**

Append to `lisp/plugins/action_cues/stop_cue.py`:

```python
    def _build_affected_set(self, target):
        """Flatten target (and any nested GroupCues) to a list of leaf cues.

        GroupCue membership is resolved via `_resolve_children()`; nested
        groups are flattened recursively. The target itself is returned
        as a single-element list when it is not a GroupCue.
        """
        from lisp.plugins.action_cues.group_cue import GroupCue

        if not isinstance(target, GroupCue):
            return [target]

        leaves = []
        for child in target._resolve_children():
            leaves.extend(self._build_affected_set(child))
        return leaves
```

Note: the import is inside the method to avoid a circular import at module load time (`group_cue` imports from `cues.cue`; keeping this local matches patterns used elsewhere in the codebase).

- [ ] **Step 4: Run tests to verify they pass**

Run: `poetry run pytest tests/cues/test_stop_cue.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```
git add lisp/plugins/action_cues/stop_cue.py tests/cues/test_stop_cue.py
git commit -m "feat(stop-cue): flatten group targets into affected set"
```

---

## Task 4: Fader collection from Volume and VideoAlpha elements

**Files:**
- Modify: `lisp/plugins/action_cues/stop_cue.py`
- Modify: `tests/cues/test_stop_cue.py`

- [ ] **Step 1: Write failing tests for fader collection**

Append to `tests/cues/test_stop_cue.py`:

```python
class TestFaderCollection:
    def _make_media_with_elements(self, element_map, state=CueState.Running):
        """element_map: {'Volume': volume_el_or_None, 'VideoAlpha': ...}"""
        cue = MagicMock(spec=MediaCue)
        cue.state = state
        cue.media = MagicMock()
        cue.media.element = lambda name: element_map.get(name)
        return cue

    def test_media_with_only_volume(self, mock_app):
        volume_fader = MagicMock(name="volume_fader")
        volume_el = MagicMock()
        volume_el.get_fader.return_value = volume_fader

        cue_media = self._make_media_with_elements({"Volume": volume_el})

        cue = StopCue(app=mock_app)
        faders = cue._collect_faders([cue_media])
        assert faders == [volume_fader]
        volume_el.get_fader.assert_called_once_with("live_volume")

    def test_media_with_volume_and_alpha(self, mock_app):
        volume_fader = MagicMock(name="vf")
        alpha_fader = MagicMock(name="af")
        volume_el = MagicMock()
        volume_el.get_fader.return_value = volume_fader
        alpha_el = MagicMock()
        alpha_el.get_fader.return_value = alpha_fader

        cue_media = self._make_media_with_elements({
            "Volume": volume_el, "VideoAlpha": alpha_el,
        })

        cue = StopCue(app=mock_app)
        faders = cue._collect_faders([cue_media])
        assert volume_fader in faders
        assert alpha_fader in faders
        assert len(faders) == 2

    def test_media_with_neither_element(self, mock_app):
        cue_media = self._make_media_with_elements({})
        cue = StopCue(app=mock_app)
        assert cue._collect_faders([cue_media]) == []

    def test_non_media_cue_skipped(self, mock_app):
        non_media = MagicMock()
        non_media.state = CueState.Running
        del non_media.media  # intentionally no `media` attribute
        cue = StopCue(app=mock_app)
        assert cue._collect_faders([non_media]) == []

    def test_non_running_cues_skipped(self, mock_app):
        volume_el = MagicMock()
        cue_media = self._make_media_with_elements(
            {"Volume": volume_el}, state=CueState.Stop
        )
        cue = StopCue(app=mock_app)
        assert cue._collect_faders([cue_media]) == []
        volume_el.get_fader.assert_not_called()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `poetry run pytest tests/cues/test_stop_cue.py::TestFaderCollection -v`
Expected: FAIL — `_collect_faders` does not exist.

- [ ] **Step 3: Add `_collect_faders`**

Append to `lisp/plugins/action_cues/stop_cue.py`:

```python
    _FADEABLE_ELEMENTS = (
        ("Volume", "live_volume"),
        ("VideoAlpha", "live_alpha"),
    )

    def _collect_faders(self, cues):
        """Return a list of Fader objects for cues currently running.

        For each MediaCue in `cues` whose state is in `IsRunning`, ask
        its Volume / VideoAlpha elements for a fader on their live
        properties. Non-MediaCues and cues without the requisite
        elements contribute nothing.
        """
        faders = []
        for cue in cues:
            if not (cue.state & CueState.IsRunning):
                continue
            if not isinstance(cue, MediaCue):
                continue
            media = getattr(cue, "media", None)
            if media is None:
                continue
            for element_name, fader_prop in self._FADEABLE_ELEMENTS:
                element = media.element(element_name)
                if element is None:
                    continue
                faders.append(element.get_fader(fader_prop))
        return faders
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `poetry run pytest tests/cues/test_stop_cue.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```
git add lisp/plugins/action_cues/stop_cue.py tests/cues/test_stop_cue.py
git commit -m "feat(stop-cue): collect live_volume + live_alpha faders from targets"
```

---

## Task 5: Fade-then-action coordinator

**Files:**
- Modify: `lisp/plugins/action_cues/stop_cue.py`
- Modify: `tests/cues/test_stop_cue.py`

- [ ] **Step 1: Write failing tests for action dispatch**

Append to `tests/cues/test_stop_cue.py`:

```python
class TestFadeThenAction:
    def _setup(self, mock_app, target_id="t1"):
        target = MagicMock(spec=MediaCue)
        target.id = target_id
        target.state = CueState.Running
        target.media = MagicMock()
        target.media.element.return_value = None  # no faders
        mock_app.cue_model.get.return_value = target

        cue = StopCue(app=mock_app)
        cue.target_id = target_id
        return cue, target

    def test_instant_action_when_duration_zero(self, mock_app):
        """duration=0 + no faders ? action fires synchronously in __start__."""
        cue, target = self._setup(mock_app)
        cue.duration = 0
        cue.action = CueAction.Stop.value

        cue.__start__()

        target.execute.assert_called_once_with(CueAction.Stop)

    def test_no_faders_with_duration_still_fires_action(self, mock_app):
        """duration>0 but no faders collected ? action fires immediately."""
        cue, target = self._setup(mock_app)
        cue.duration = 1000
        cue.action = CueAction.Pause.value

        cue.__start__()
        target.execute.assert_called_once_with(CueAction.Pause)

    def test_fade_then_action_runs_async(self, mock_app, monkeypatch):
        """duration>0 with faders ? faders run, then action dispatched."""
        # Patch Thread so we can inspect scheduling without real threading
        class _FakeThread:
            def __init__(self, target=None, args=(), kwargs=None, daemon=False):
                self._target = target
                self._args = args
                self._kwargs = kwargs or {}

            def start(self):
                self._target(*self._args, **self._kwargs)

            def join(self, timeout=None):
                pass

        monkeypatch.setattr(
            "lisp.plugins.action_cues.stop_cue.Thread", _FakeThread
        )
        # @async_function also uses threading.Thread; patch at its source
        monkeypatch.setattr(
            "lisp.core.decorators.Thread", _FakeThread
        )

        volume_fader = MagicMock()
        volume_fader.fade.return_value = True
        volume_el = MagicMock()
        volume_el.get_fader.return_value = volume_fader

        target = MagicMock(spec=MediaCue)
        target.state = CueState.Running
        target.media = MagicMock()
        target.media.element = lambda n: volume_el if n == "Volume" else None
        mock_app.cue_model.get.return_value = target

        cue = StopCue(app=mock_app)
        cue.target_id = "t1"
        cue.duration = 500
        cue.action = CueAction.Interrupt.value

        cue.__start__()

        volume_fader.prepare.assert_called_once()
        volume_fader.fade.assert_called_once()
        target.execute.assert_called_once_with(CueAction.Interrupt)

    def test_action_is_non_fading_variant(self, mock_app):
        """action=Stop should dispatch the plain non-fading variant."""
        cue, target = self._setup(mock_app)
        cue.duration = 0

        for action_enum in (CueAction.Stop, CueAction.Pause, CueAction.Interrupt):
            target.reset_mock()
            cue.action = action_enum.value
            cue.__start__()
            target.execute.assert_called_once_with(action_enum)
            assert target.execute.call_args[0][0] not in (
                CueAction.FadeOutStop,
                CueAction.FadeOutPause,
                CueAction.FadeOutInterrupt,
            )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `poetry run pytest tests/cues/test_stop_cue.py::TestFadeThenAction -v`
Expected: FAIL — `__start__` currently returns without dispatching.

- [ ] **Step 3: Rewrite `__start__` and add coordinator**

Replace the stub `__start__` in `lisp/plugins/action_cues/stop_cue.py` with:

```python
    def __start__(self, fade=False):
        target = self.app.cue_model.get(self.target_id)
        if target is None:
            logger.warning(
                "StopCue: target cue %r not found", self.target_id
            )
            self._error()
            return False

        affected = self._build_affected_set(target)
        faders = self._collect_faders(affected)

        if self.duration > 0 and faders:
            self._aborted = False
            self._active_faders = list(faders)
            self._run_fade_then_action(target, faders)
            return True

        # Instant path: no fade to run, dispatch the action synchronously
        target.execute(CueAction(self.action))
        return False

    @async_function
    def _run_fade_then_action(self, target, faders):
        """Run all faders to 0 in parallel, then dispatch the action.

        Executed in a daemon thread via @async_function. Each fader
        runs in its own sub-thread because Fader.fade() is blocking;
        the coordinator joins them all, then fires the action on the
        target (plain Stop/Pause/Interrupt, not FadeOut*).
        """
        try:
            fade_seconds = self.duration / 1000
            fade_curve = FadeOutType[self.fade_type]

            threads = []
            for fader in faders:
                fader.prepare()
                t = Thread(
                    target=self._run_single_fader,
                    args=(fader, fade_seconds, fade_curve),
                    daemon=True,
                )
                t.start()
                threads.append(t)

            for t in threads:
                t.join()

            if self._aborted:
                return

            target.execute(CueAction(self.action))
        except Exception:
            logger.exception("StopCue: error during fade-and-action")
            self._error()
            return
        finally:
            self._active_faders = []

        self._ended()

    def _run_single_fader(self, fader, seconds, curve):
        try:
            fader.fade(seconds, 0.0, curve)
        except Exception:
            logger.exception("StopCue: fader raised")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `poetry run pytest tests/cues/test_stop_cue.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```
git add lisp/plugins/action_cues/stop_cue.py tests/cues/test_stop_cue.py
git commit -m "feat(stop-cue): coordinate parallel faders then dispatch action"
```

---

## Task 6: Abort in-flight faders on StopCue `__stop__` / `__interrupt__`

**Files:**
- Modify: `lisp/plugins/action_cues/stop_cue.py`
- Modify: `tests/cues/test_stop_cue.py`

- [ ] **Step 1: Write failing tests for abort behaviour**

Append to `tests/cues/test_stop_cue.py`:

```python
class TestAbort:
    def test_stop_aborts_all_active_faders(self, mock_app):
        fader_a = MagicMock()
        fader_b = MagicMock()

        cue = StopCue(app=mock_app)
        cue._active_faders = [fader_a, fader_b]

        cue.__stop__()

        fader_a.stop.assert_called_once()
        fader_b.stop.assert_called_once()
        assert cue._aborted is True

    def test_interrupt_aborts_all_active_faders(self, mock_app):
        fader = MagicMock()
        cue = StopCue(app=mock_app)
        cue._active_faders = [fader]

        cue.__interrupt__()

        fader.stop.assert_called_once()
        assert cue._aborted is True

    def test_stop_without_running_faders_is_safe(self, mock_app):
        cue = StopCue(app=mock_app)
        assert cue.__stop__() is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `poetry run pytest tests/cues/test_stop_cue.py::TestAbort -v`
Expected: FAIL — `__stop__` / `__interrupt__` inherit base behaviour which doesn't touch faders.

- [ ] **Step 3: Add `__stop__` and `__interrupt__`**

Append to `lisp/plugins/action_cues/stop_cue.py`:

```python
    def __stop__(self, fade=False):
        self._aborted = True
        for fader in self._active_faders:
            fader.stop()
        return True

    __interrupt__ = __stop__
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `poetry run pytest tests/cues/test_stop_cue.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```
git add lisp/plugins/action_cues/stop_cue.py tests/cues/test_stop_cue.py
git commit -m "feat(stop-cue): abort active faders on stop/interrupt"
```

---

## Task 7: Settings page (`StopCueSettings`) and registry

**Files:**
- Modify: `lisp/plugins/action_cues/stop_cue.py`
- Modify: `tests/cues/test_stop_cue.py`

- [ ] **Step 1: Write failing tests for settings page**

Append to `tests/cues/test_stop_cue.py`:

```python
class TestStopCueSettings:
    """Settings-page round-trip. Requires QApplication via qapp fixture."""

    def test_get_settings_empty_when_groups_disabled(self, qapp):
        from lisp.plugins.action_cues.stop_cue import StopCueSettings

        page = StopCueSettings()
        page.enableCheck(False)
        assert page.getSettings() == {}

    def test_load_then_get_round_trip(self, qapp, monkeypatch):
        from lisp.plugins.action_cues.stop_cue import StopCueSettings

        fake_target = MagicMock()
        fake_target.name = "Target Cue"
        monkeypatch.setattr(
            "lisp.plugins.action_cues.stop_cue.Application",
            lambda: MagicMock(cue_model=MagicMock(
                get=lambda _id: fake_target, filter=lambda *_: [],
            )),
        )

        page = StopCueSettings()
        page.enableCheck(True)
        page.loadSettings({
            "target_id": "abc",
            "action": CueAction.Pause.value,
            "duration": 2500,
            "fade_type": "Linear",
        })

        settings = page.getSettings()
        assert settings["target_id"] == "abc"
        assert settings["action"] == CueAction.Pause.value
        assert settings["duration"] == 2500
        assert settings["fade_type"] == "Linear"

    def test_registry_association(self):
        from lisp.ui.settings.cue_settings import CueSettingsRegistry
        from lisp.plugins.action_cues.stop_cue import (
            StopCue, StopCueSettings,
        )

        pages = [
            p for p, cls in CueSettingsRegistry().filter(StopCue)
            if cls is StopCueSettings
        ]
        assert pages, "StopCueSettings not registered for StopCue"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `poetry run pytest tests/cues/test_stop_cue.py::TestStopCueSettings -v`
Expected: FAIL — `StopCueSettings` does not exist.

- [ ] **Step 3: Add `StopCueSettings` and registry wiring**

Update the imports block at the top of `lisp/plugins/action_cues/stop_cue.py` to read:

```python
import logging
from threading import Thread

from PyQt5.QtCore import QT_TRANSLATE_NOOP, Qt
from PyQt5.QtWidgets import (
    QComboBox, QGroupBox, QLabel, QPushButton, QVBoxLayout,
)

from lisp.application import Application
from lisp.core.decorators import async_function
from lisp.core.fade_functions import FadeOutType
from lisp.core.properties import Property
from lisp.cues.cue import Cue, CueAction, CueState
from lisp.cues.media_cue import MediaCue
from lisp.ui.cuelistdialog import CueSelectDialog
from lisp.ui.settings.cue_settings import CueSettingsRegistry
from lisp.ui.settings.pages import SettingsPage
from lisp.ui.ui_utils import translate
from lisp.ui.widgets import FadeEdit
```

Then append the settings page and registry call at the bottom of the file:

```python
class StopCueSettings(SettingsPage):
    Name = QT_TRANSLATE_NOOP("SettingsPageName", "Fade & Stop Settings")
    SortOrder = 30

    SupportedActions = [
        CueAction.Stop,
        CueAction.Pause,
        CueAction.Interrupt,
    ]

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

        # Action combo
        self.actionGroup = QGroupBox(self)
        self.actionGroup.setLayout(QVBoxLayout(self.actionGroup))
        self.layout().addWidget(self.actionGroup)

        self.actionCombo = QComboBox(self.actionGroup)
        for a in self.SupportedActions:
            self.actionCombo.addItem(
                translate("CueAction", a.name), a.value,
            )
        self.actionGroup.layout().addWidget(self.actionCombo)

        # Fade settings
        self.fadeGroup = QGroupBox(self)
        self.fadeGroup.setLayout(QVBoxLayout())
        self.layout().addWidget(self.fadeGroup)

        self.fadeEdit = FadeEdit(self.fadeGroup)
        self.fadeGroup.layout().addWidget(self.fadeEdit)

        self.retranslateUi()

    def retranslateUi(self):
        self.cueGroup.setTitle(translate("StopCue", "Cue"))
        self.cueButton.setText(translate("StopCue", "Click to select"))
        self.cueLabel.setText(translate("StopCue", "Not selected"))
        self.actionGroup.setTitle(translate("StopCue", "Action"))
        self.fadeGroup.setTitle(translate("StopCue", "Fade"))

    def select_cue(self):
        if self.cueDialog.exec() == self.cueDialog.Accepted:
            selected = self.cueDialog.selected_cue()
            if selected is not None:
                self.cue_id = selected.id
                self.cueLabel.setText(selected.name)

    def enableCheck(self, enabled):
        self.setGroupEnabled(self.cueGroup, enabled)
        self.setGroupEnabled(self.actionGroup, enabled)
        self.setGroupEnabled(self.fadeGroup, enabled)

    def getSettings(self):
        settings = {}
        if self.isGroupEnabled(self.cueGroup):
            settings["target_id"] = self.cue_id
        if self.isGroupEnabled(self.actionGroup):
            settings["action"] = self.actionCombo.currentData()
        if self.isGroupEnabled(self.fadeGroup):
            settings["duration"] = int(self.fadeEdit.duration() * 1000)
            settings["fade_type"] = self.fadeEdit.fadeType()
        return settings

    def loadSettings(self, settings):
        target = Application().cue_model.get(settings.get("target_id", ""))
        if target is not None:
            self.cue_id = settings["target_id"]
            self.cueLabel.setText(target.name)

        action_value = settings.get("action", CueAction.Stop.value)
        index = self.actionCombo.findData(action_value)
        if index >= 0:
            self.actionCombo.setCurrentIndex(index)

        self.fadeEdit.setDuration(settings.get("duration", 0) / 1000)
        self.fadeEdit.setFadeType(
            settings.get("fade_type", FadeOutType.Linear.name)
        )


CueSettingsRegistry().add(StopCueSettings, StopCue)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `poetry run pytest tests/cues/test_stop_cue.py -v`
Expected: PASS

Also sanity-check the module imports cleanly under headless Qt:
Run: `poetry run python -c "from lisp.plugins.action_cues.stop_cue import StopCue, StopCueSettings; print('ok')"`
Expected: prints `ok` with no tracebacks.

- [ ] **Step 5: Commit**

```
git add lisp/plugins/action_cues/stop_cue.py tests/cues/test_stop_cue.py
git commit -m "feat(stop-cue): add StopCueSettings with target/action/fade UI"
```

---

## Task 8: Regenerate i18n translation templates

**Files:**
- Modify: `lisp/i18n/ts/*.ts` (auto-generated)

- [ ] **Step 1: Run the i18n updater**

Run: `python i18n_update.py`
Expected: updated `.ts` files containing new contexts: `CueName` ("Fade & Stop"), `SettingsPageName` ("Fade & Stop Settings"), `StopCue` ("Cue", "Click to select", "Not selected", "Action", "Fade").

- [ ] **Step 2: Verify only expected files changed**

Run: `git status --short` and confirm the diff touches only `lisp/i18n/ts/`.

- [ ] **Step 3: Commit**

```
git add lisp/i18n/ts/
git commit -m "i18n: regenerate translations for Fade & Stop strings"
```

---

## Task 9: E2E test suite via test_harness

**Files:**
- Create: `tests/e2e/test_fade_and_stop_e2e.py`

- [ ] **Step 1: Confirm no LiSP is already using the harness port**

Run: `pgrep -af 'lisp.main' || echo "none"`
Expected: `none`. Port-clash detection guard — see memory `feedback_e2e_port_clash`.

- [ ] **Step 2: Write the E2E suite**

Create `tests/e2e/test_fade_and_stop_e2e.py`:

```python
#!/usr/bin/env python3
"""E2E tests for Fade & Stop (StopCue).

Covers:
    1. Instant dispatch when duration=0 on a running target.
    2. Fade then pause on a single MediaCue target.
    3. Fade then stop on a parallel GroupCue (cascade works).
    4. Abort mid-fade via Stop on the StopCue itself (target stays running).
    5. Non-media target (no fader) still receives the action after 0ms.

Run:
    poetry run python tests/e2e/test_fade_and_stop_e2e.py
"""

import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from tests.e2e.helpers import (  # noqa: E402
    run_suite, call, cue_state, cue_prop, wait_state, stop_all,
    setup_with_tones, cue_signal, wait_for_signal,
)


def _add_stop_cue(target_id, action="Stop", duration_ms=0, fade_type="Linear"):
    """Create a StopCue; return its id."""
    return call("cue.add", {
        "type": "StopCue",
        "properties": {
            "target_id": target_id,
            "action": action,
            "duration": duration_ms,
            "fade_type": fade_type,
        },
    })["id"]


def test_1_instant_stop(t, ids):
    """duration=0: StopCue dispatches Stop to a running target immediately."""
    print("\n=== Test 1: Instant stop (duration=0) ===")
    stop_all()

    target = ids["tone_A"]
    sfr = _add_stop_cue(target, action="Stop", duration_ms=0)

    call("cue.execute", {"id": target, "action": "Start"})
    assert wait_state(target, "Running"), "target failed to start"

    with cue_signal(target, "stopped") as sub:
        call("cue.execute", {"id": sfr, "action": "Start"})
        ev = wait_for_signal(sub, timeout=3.0)

    t.check("target received stopped signal", ev is not None)
    t.check("target is Stop state", cue_state(target) == "Stop")


def test_2_fade_then_pause(t, ids):
    """duration=500ms + action=Pause: volume fades to 0, target pauses."""
    print("\n=== Test 2: Fade 500ms then Pause ===")
    stop_all()

    target = ids["tone_A"]
    sfr = _add_stop_cue(target, action="Pause", duration_ms=500)

    call("cue.execute", {"id": target, "action": "Start"})
    assert wait_state(target, "Running")

    with cue_signal(target, "paused") as sub:
        call("cue.execute", {"id": sfr, "action": "Start"})
        ev = wait_for_signal(sub, timeout=3.0)

    t.check("target received paused signal", ev is not None)
    t.check("target is Pause state", cue_state(target) == "Pause")

    vol = cue_prop(target, "media.elements.Volume.live_volume")
    t.check(f"live_volume near 0 after fade (got {vol})", vol < 0.05)


def test_3_group_fan_out(t, ids):
    """StopCue on a parallel GroupCue stops every running child."""
    print("\n=== Test 3: Group fan-out ===")
    stop_all()

    a, b = ids["tone_A"], ids["tone_B"]
    call("layout.select_cues", {"indices": [0, 1]})
    call("layout.context_action", {
        "action": "Group selected",
        "cue_ids": [a, b],
    })
    cues = call("cue.list")
    group = next(c for c in cues if c["_type_"] == "GroupCue")
    group_id = group["id"]

    sfr = _add_stop_cue(group_id, action="Stop", duration_ms=400)

    call("cue.execute", {"id": group_id, "action": "Start"})
    assert wait_state(a, "Running") and wait_state(b, "Running"), \
        "group children failed to start"

    with cue_signal(a, "stopped") as sub_a, \
         cue_signal(b, "stopped") as sub_b:
        call("cue.execute", {"id": sfr, "action": "Start"})
        ev_a = wait_for_signal(sub_a, timeout=3.0)
        ev_b = wait_for_signal(sub_b, timeout=3.0)

    t.check("child A stopped", ev_a is not None)
    t.check("child B stopped", ev_b is not None)


def test_4_abort_midfade(t, ids):
    """Stopping the StopCue mid-fade leaves target running."""
    print("\n=== Test 4: Abort mid-fade ===")
    stop_all()

    target = ids["tone_A"]
    sfr = _add_stop_cue(target, action="Stop", duration_ms=3000)

    call("cue.execute", {"id": target, "action": "Start"})
    assert wait_state(target, "Running")

    call("cue.execute", {"id": sfr, "action": "Start"})
    time.sleep(0.3)  # let the fade begin
    call("cue.execute", {"id": sfr, "action": "Stop"})
    time.sleep(0.2)

    t.check(
        "target still Running after SFR abort",
        cue_state(target) == "Running",
    )


def test_5_non_media_target_graceful(t, ids):
    """StopCue on a target without faders still dispatches the action."""
    print("\n=== Test 5: Non-media target ===")
    stop_all()

    cmd = call("cue.add", {
        "type": "CommandCue",
        "properties": {"command": "true", "no_output": True},
    })["id"]
    sfr = _add_stop_cue(cmd, action="Stop", duration_ms=200)

    with cue_signal(sfr, "end") as sub_end:
        call("cue.execute", {"id": sfr, "action": "Start"})
        ev = wait_for_signal(sub_end, timeout=2.0)

    t.check("StopCue itself ended cleanly on non-media target", ev is not None)


# -- Entry --

def run_tests(t):
    ids = setup_with_tones()
    test_1_instant_stop(t, ids)
    test_2_fade_then_pause(t, ids)
    test_3_group_fan_out(t, ids)
    test_4_abort_midfade(t, ids)
    test_5_non_media_target_graceful(t, ids)


if __name__ == "__main__":
    run_suite("Fade & Stop E2E", run_tests)
```

- [ ] **Step 3: Run the suite**

Run: `poetry run python tests/e2e/test_fade_and_stop_e2e.py`
Expected: all 5 tests pass; summary reports `PASSED: 5`, `FAILED: 0`.

If any test fails, diagnose and fix either the implementation or the test assertions before moving on.

- [ ] **Step 4: Commit**

```
git add tests/e2e/test_fade_and_stop_e2e.py
git commit -m "test(stop-cue): e2e coverage for instant/fade/group/abort/non-media"
```

---

## Task 10: Full regression sweep

**Files:** (none modified unless a regression surfaces)

- [ ] **Step 1: Run full unit-test suite**

Run: `poetry run pytest tests/ -v`
Expected: no failures. If any pre-existing test was affected by the new action cue registration, fix and re-run before proceeding.

- [ ] **Step 2: Run full E2E suite**

Run each E2E script that might be affected:

```
poetry run python tests/e2e/test_fade_and_stop_e2e.py
poetry run python tests/e2e/test_volume_control_e2e.py
poetry run python tests/e2e/test_groups_e2e.py
poetry run python tests/e2e/test_global_controls_e2e.py
```

Expected: each reports `FAILED: 0`.

- [ ] **Step 3: Run Ruff**

Run: `poetry run ruff check lisp/plugins/action_cues/stop_cue.py tests/cues/test_stop_cue.py tests/e2e/test_fade_and_stop_e2e.py`
Expected: clean. Fix any violations inline and commit.

---

## Task 11: QA review via subagent

**Files:** (may produce fixes as follow-up edits)

- [ ] **Step 1: Dispatch the QA expert**

Use the `Agent` tool with `subagent_type="voltagent-qa-sec:qa-expert"` and this prompt:

> Review the Fade & Stop cue implementation against its spec and roadmap.
>
> - Spec: `docs/specs/2026-04-18-fade-and-stop-cue-design.md`
> - Plan: `plans/07-fade-and-stop-cue.md`
> - Implementation: `lisp/plugins/action_cues/stop_cue.py`
> - Unit tests: `tests/cues/test_stop_cue.py`
> - E2E tests: `tests/e2e/test_fade_and_stop_e2e.py`
>
> Assess:
> 1. Test-plan completeness. Are the spec's edge cases all covered (missing target, non-media target, concurrent SFRs, nested groups, mid-fade abort)?
> 2. Verification that the target workflow (intermission-style fade+pause on a playlist GroupCue) would actually work end-to-end from an operator's perspective.
> 3. Missing scenarios not asserted anywhere — cross-plugin interactions (MIDI/OSC triggering the SFR, timecode, presets), failure modes (target deleted during fade), etc.
>
> Keep reporting to high-confidence issues only. Return a prioritised punch list under 300 words.

- [ ] **Step 2: Triage findings**

For each reported issue:
- If it identifies a spec-level gap: add a TODO to the roadmap's Part 1 checklist and resolve before marking Task 13 complete.
- If it identifies a missing test: add the test and re-run Task 10.
- If it's a false positive: record rationale inline; no code change.

- [ ] **Step 3: Commit any resulting changes**

```
git add <changed-files>
git commit -m "test(stop-cue): address QA review findings"
```

(Skip if no changes.)

---

## Task 12: Code review via subagent

**Files:** (may produce fixes)

- [ ] **Step 1: Dispatch the code-reviewer**

Use the `Agent` tool with `subagent_type="voltagent-qa-sec:code-reviewer"` and this prompt:

> Review the Fade & Stop cue code for correctness, convention fit, and thread safety.
>
> - Implementation: `lisp/plugins/action_cues/stop_cue.py`
> - Spec (for intent): `docs/specs/2026-04-18-fade-and-stop-cue-design.md`
> - Reference patterns to match: `lisp/plugins/action_cues/volume_control.py` (single-target fade), `lisp/plugins/action_cues/stop_all.py` (action combo), `lisp/plugins/action_cues/group_cue.py:449-485` (child cascade).
>
> Specifically check:
> 1. Correctness against spec: does every behaviour described in the Architecture section land in the code?
> 2. LiSP conventions: signal/fader/property usage matches `volume_control.py`; translation contexts are sensible; registry wiring is correct.
> 3. Thread safety: the `@async_function` coordinator spawns per-fader threads — is `_active_faders` / `_aborted` mutation safe? Any Qt-main-thread violations?
> 4. Resource cleanup: faders released on abort, error, and natural completion. No leaks if `_run_fade_then_action` raises.
> 5. Edge cases from the spec: missing target logged+errored; non-Media target takes the instant path; concurrent SFRs on the same target don't corrupt state.
>
> Report only high-confidence issues. Return a prioritised punch list under 300 words.

- [ ] **Step 2: Triage findings**

Apply the same triage rules as Task 11. Fixes go into `lisp/plugins/action_cues/stop_cue.py`; re-run Task 10 after each.

- [ ] **Step 3: Commit any resulting changes**

```
git add lisp/plugins/action_cues/stop_cue.py tests/
git commit -m "refactor(stop-cue): address code review findings"
```

(Skip if no changes.)

---

## Task 13: Close out Part 1 and update roadmap

**Files:**
- Modify: `docs/specs/2026-04-18-sfr-workflow-roadmap.md`

- [ ] **Step 1: Tick Part 1 boxes**

In `docs/specs/2026-04-18-sfr-workflow-roadmap.md`, change the Part 1 section so completed items become `[x]`:

```
- [x] Brainstorm design
- [x] Write spec
- [x] Write implementation plan
- [x] Implement `StopCue` + `StopCueSettings`
- [x] Unit tests
- [x] E2E test via `test_harness`
- [x] QA review (`voltagent-qa-sec:qa-expert`)
- [x] Code review (`voltagent-qa-sec:code-reviewer`)
```

- [ ] **Step 2: Verify the full test sweep still passes**

Run:
```
poetry run pytest tests/ -q
poetry run python tests/e2e/test_fade_and_stop_e2e.py
```
Expected: all green.

- [ ] **Step 3: Final commit**

```
git add docs/specs/2026-04-18-sfr-workflow-roadmap.md
git commit -m "docs(spec): mark Part 1 (Fade & Stop) complete in SFR roadmap"
```

- [ ] **Step 4: Push and (optionally) open a PR — only if the user explicitly requests it**

```
git push -u origin <branch>
gh pr create --title "feat: Fade & Stop cue (Part 1/3 of SFR workflow)" --body "..."
```
