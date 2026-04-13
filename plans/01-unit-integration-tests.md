# Plan: Unit/Integration Tests ✅ Complete

## Context

LiSP has zero test infrastructure — no pytest, no test dirs, no CI test steps. Almost every module imports PyQt5 (even `signal.py`, `configuration.py`), so a `QApplication` must exist even for "pure logic" tests. The Singleton pattern used by `Application`/`MainWindow` makes isolation tricky.

## Setup

### Dependencies

Add to `[tool.poetry.group.dev.dependencies]` in `pyproject.toml`:

```
pytest = "^8.0"
pytest-cov = "^5.0"
pytest-qt = "^4.4"
pytest-mock = "^3.14"
pytest-timeout = "^2.3"
```

### Pytest Config

Add to `pyproject.toml`:

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
timeout = 10
markers = [
    "qt: tests requiring a Qt event loop",
    "gstreamer: tests requiring GStreamer",
    "slow: slow-running tests",
]
```

## Root `tests/conftest.py` — Critical Fixtures

```python
import pytest
from unittest.mock import MagicMock
from lisp.core.configuration import DummyConfiguration


@pytest.fixture(scope="session", autouse=True)
def qapp_session(qapp):
    """QApplication must exist before any lisp module import.

    Many modules call translate() at class level, which calls
    QApplication.translate(). Without a QApplication, imports crash.
    """
    return qapp


@pytest.fixture
def mock_app():
    """Lightweight mock — never instantiate the real Singleton Application."""
    app = MagicMock()
    app.conf = DummyConfiguration(root={
        "cue": {
            "interruptFade": 0,
            "interruptFadeType": "Linear",
            "fadeAction": 0,
            "fadeActionType": "Linear",
        }
    })
    return app
```

## Directory Structure

```
tests/
    __init__.py
    conftest.py
    core/
        __init__.py
        test_util.py
        test_fade_functions.py
        test_dicttree.py
        test_properties.py
        test_class_based_registry.py
        test_decorators.py
        test_signal.py
        test_configuration.py
        test_has_properties.py
        test_rwait.py
    cues/
        __init__.py
        test_cue_model.py
        test_cue_factory.py
    command/
        __init__.py
        test_command_stack.py
        test_model_commands.py
```

## Test Priority Tiers

### Tier 1 — Pure logic (easiest, highest value)

No mocks needed beyond QApp.

| File to create | Module under test | What to test | ~Tests |
|---|---|---|---|
| `tests/core/test_util.py` | `lisp/core/util.py` | `dict_merge`, `dict_merge_diff`, `time_tuple`, `strtime`, `compose_url`, `natural_keys`, `rgetattr`/`rsetattr`/`rhasattr`, `EqEnum`, `FunctionProxy` | ~20 |
| `tests/core/test_fade_functions.py` | `lisp/core/fade_functions.py` | `fade_linear`, `fadein_quad`, `fadeout_quad`, `fade_inout_quad`, `ntime` — boundary values, midpoints | ~10 |
| `tests/core/test_dicttree.py` | `lisp/core/dicttree.py` | `DictNode` get/set/pop/path/contains, error on invalid path | ~12 |
| `tests/core/test_properties.py` | `lisp/core/properties.py` | `Property` default/set/get, `WriteOnceProperty`, `ProxyProperty`, `InstanceProperty`, isolation between instances | ~10 |
| `tests/core/test_class_based_registry.py` | `lisp/core/class_based_registry.py` | add/filter, subclass_filter, remove, clear, duplicate_add | ~8 |
| `tests/core/test_decorators.py` | `lisp/core/decorators.py` | `memoize`, `locked_function` (concurrent access), `locked_method` | ~6 |

### Tier 2 — Core patterns (need QApp but no GUI)

| File to create | Module under test | What to test | ~Tests |
|---|---|---|---|
| `tests/core/test_signal.py` | `lisp/core/signal.py` | connect/emit function, connect/emit method, disconnect specific/all, weak-ref cleanup (dead refs removed), no-args slot with signal that emits args, duplicate connect ignored, `slot_id` function vs method | ~15 |
| `tests/core/test_configuration.py` | `lisp/core/configuration.py` | `ConfDict` get/set/nested/pop/contains/update, `DummyConfiguration` signals, `JSONFileConfiguration` (using `tmp_path` for temp JSON files) | ~15 |
| `tests/core/test_has_properties.py` | `lisp/core/has_properties.py` | `properties_names`, `properties_defaults`, `class_defaults`, serialization, `update_properties`, `changed` signal, `property_changed` signal, inheritance (subclass gets parent properties) | ~12 |
| `tests/core/test_rwait.py` | `lisp/core/rwait.py` | `RWait` wait/stop/pause/resume, current_time, is_waiting, is_paused | ~6 |

### Tier 3 — Domain model (need `mock_app` fixture)

| File to create | Module under test | What to test | ~Tests |
|---|---|---|---|
| `tests/cues/test_cue_model.py` | `lisp/cues/cue_model.py` | add/remove/pop/get/reset/filter, `item_added`/`item_removed`/`model_reset` signals, len/contains/iter, add duplicate raises | ~12 |
| `tests/cues/test_cue_factory.py` | `lisp/cues/cue_factory.py` | register/create, `has_factory`, `remove_factory`, create unregistered raises, clone_cue | ~8 |
| `tests/command/test_command_stack.py` | `lisp/command/stack.py` | do executes command, undo_last, redo_last, do clears redo stack, clear, is_saved/set_saved, signals (done, undone, redone, saved) | ~10 |
| `tests/command/test_model_commands.py` | `lisp/command/model.py` | `ModelAddItemsCommand` do/undo, `ModelRemoveItemsCommand` do/undo, `ModelMoveItemCommand` do/undo | ~8 |

**Total: ~140-160 tests across 14 modules.** No GStreamer tests initially.

## CI Integration

Add a test job to `.circleci/config.yml` that runs before the Flatpak build:

```yaml
run-tests:
  docker:
    - image: cimg/python:3.12
  steps:
    - checkout
    - run:
        name: Install system dependencies
        command: |
          sudo apt-get update
          sudo apt-get install -y python3-pyqt5 libglib2.0-0 libgl1
    - run:
        name: Install Poetry and dependencies
        command: |
          pip install poetry
          poetry install --with dev
    - run:
        name: Run tests
        command: |
          export QT_QPA_PLATFORM=offscreen
          poetry run pytest --cov=lisp --cov-report=xml -v
```

Gate Flatpak build on tests passing:

```yaml
workflows:
  build:
    jobs:
      - run-tests
      - build-flatpak:
          requires:
            - run-tests
```

## Key Challenges

| Challenge | Mitigation |
|---|---|
| `translate()` at module import time — many modules call `QApplication.translate()` at class level | Session-scoped `qapp` fixture from pytest-qt handles this automatically |
| Singletons (`Application`, `MainWindow`) — can't instantiate twice | Never instantiate real Application in unit tests; use `mock_app` fixture |
| `@async_function` threading — `Cue.start()`/`stop()` run in threads | Initially test synchronous methods only; use `pytest-timeout` as safety net |
| Weak references in `Signal` — slot objects get GC'd if no strong ref | Tests must keep strong references to slot objects (assign lambdas to local vars) |
| Module-level singleton instances (e.g., `clock.py` creates `Clock_10` etc.) | Handled by global `qapp` fixture; avoid importing clock.py in tests that don't need it |

## GStreamer Testing Strategy (Future)

Not for the initial test suite. When eventually added:
- Use `pytest.importorskip("gi.repository.Gst")` to skip on systems without GStreamer
- Mark with `@pytest.mark.gstreamer`
- Start with element-level tests (individual elements in isolation) rather than full pipelines
- Mock GStreamer pipeline for integration tests of `MediaCue` behavior
