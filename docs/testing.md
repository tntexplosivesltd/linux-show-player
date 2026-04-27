# Testing Guide

LiSP has **two distinct test layers**, run with different tools and serving
different purposes:

| Layer        | Runner           | What it touches                          | Use when…                                                     |
|--------------|------------------|------------------------------------------|---------------------------------------------------------------|
| Unit tests   | `pytest`         | A mocked `Application`, isolated objects | Logic fits in a single module / can be exercised in-process   |
| E2E tests    | `poetry run python …` (no pytest) | A real LiSP subprocess driven over JSON-RPC | Behaviour spans the model, layout, GStreamer, save/load, UI |

Pick the lowest layer that can prove the thing you care about. Unit tests
are cheap, fast, and produce small diffs. E2E tests are the only thing
that proves a feature actually works end-to-end inside a running LiSP.

---

## 1. Unit tests (pytest)

### Layout

```
tests/
  conftest.py            # mock_app fixture, qapp_session autouse fixture
  __init__.py
  core/                  # mirrors lisp/core/
  cues/                  # mirrors lisp/cues/
  command/               # mirrors lisp/command/
  layout/                # mirrors lisp/layout/
  ui/                    # widgets, dialogs (uses pytest-qt)
  plugins/               # plugin-specific unit tests
```

The directory layout **mirrors `lisp/`** so the test for
`lisp/foo/bar.py` lives at `tests/foo/test_bar.py`.

### Running

```bash
poetry run pytest tests/                              # all unit tests
poetry run pytest tests/core/test_signal.py           # one file
poetry run pytest tests/ -v                           # verbose
poetry run pytest tests/ -k "fade and not group"      # name filter
poetry run pytest tests/ -x --pdb                     # stop & debug on first failure
```

### The two essential fixtures

`tests/conftest.py` provides everything the rest of the suite assumes:

```python
@pytest.fixture(scope="session", autouse=True)
def qapp_session(qapp):
    """QApplication must exist before any lisp module import."""
    return qapp

@pytest.fixture
def mock_app():
    """Lightweight mock of Application — never instantiate the real Singleton."""
    app = MagicMock()
    app.conf = DummyConfiguration(root={...})
    return app
```

Two things to internalise:

1. **`qapp_session` is autouse and session-scoped.** This is intentional:
   many LiSP modules call `translate()` at *class definition time*, which
   in turn calls `QApplication.translate()`. Importing without a
   `QApplication` already alive crashes. `pytest-qt` provides the `qapp`
   fixture; `qapp_session` simply forces it to wake up before any test
   module is imported.
2. **Never instantiate the real `Application` singleton in tests.** Use
   `mock_app`. The real one is a singleton, persists across tests,
   pulls in plugins, and has nasty side-effects on import. `mock_app`
   gives you `app.cue_model`, `app.session`, `app.conf`, etc. as
   `MagicMock`s you can configure per-test.

### Writing a unit test

```python
# tests/cues/test_my_cue.py
def test_property_round_trip(mock_app):
    cue = MyCue(app=mock_app)
    cue.update_properties({"name": "hello", "duration": 1500})
    assert cue.properties()["name"] == "hello"
    assert cue.duration == 1500
```

Conventions:

- File name `test_*.py`, function name `test_*`.
- Use `mock_app` whenever the code under test reaches for the singleton.
- For Qt widgets, use `pytest-qt` fixtures (`qtbot`, `qapp`) — see
  `tests/ui/test_cue_settings_dialog_integration.py` for an example.

### Signal gotcha (read this before writing signal tests)

LiSP's `Signal`/`Slot` system in `lisp/core/signal.py` holds **weak
references** to handlers. A bare lambda dies the moment its enclosing
scope finishes evaluating, *before* the signal fires. Bind to a named
function:

```python
# WRONG — handler is GC'd before emit reaches it
sig.connect(lambda x: events.append(x))

# RIGHT — keep a strong reference
def handler(x):
    events.append(x)

sig.connect(handler)
```

This is the same reason `mock_app.something.connect(MagicMock())` can
look fine and silently never fire — the `MagicMock()` is unreferenced.

---

## 2. E2E tests (the harness)

E2E tests work fundamentally differently. Each test file is a
**self-contained executable script**:

1. Boots a real LiSP subprocess.
2. Waits for the test-harness JSON-RPC server to come up.
3. Calls JSON-RPC methods to drive the app and read its state.
4. Asserts via a tiny in-house `TestTracker`.
5. Tears LiSP down and exits with `0` (passed) or `1` (failed).

There is no pytest involvement. Trying to run them via pytest will
fail; `tests/e2e/conftest.py` uses `collect_ignore` to keep pytest from
even importing them.

### Running

```bash
# Standard flow — script starts and stops its own LiSP
poetry run python tests/e2e/test_seek_cue_e2e.py

# Run against an already-running LiSP (faster iteration on a single file)
poetry run linux-show-player -l warning &       # LiSP must have Test Harness enabled
poetry run python tests/e2e/test_seek_cue_e2e.py --no-launch

# Custom host/port (rare)
poetry run python tests/e2e/test_seek_cue_e2e.py --host 127.0.0.1 --port 8070
```

If `start_lisp` reports `Method not found` for a method you just added,
**a stale LiSP is almost certainly squatting on port 8070**:

```bash
pgrep -fa lisp.main
# kill the stale one
```

### The harness, conceptually

```
                ┌────────── LiSP process ──────────┐
                │                                  │
   E2E script   │   ┌─────────┐   ┌────────────┐   │
   ──JSON-RPC──►│──►│ Server  │──►│ Dispatcher │──►│── handler runs on
   over TCP     │   │ thread  │   │            │   │   Qt main thread via
   127.0.0.1    │   └─────────┘   └────────────┘   │   invoke_on_main_thread
   :8070        │         │                        │
                │         └──► SignalManager ◄─────│── connects to LiSP
                │                                  │   signals; buffers events
                └──────────────────────────────────┘
```

- **Plugin entry point**: `lisp/plugins/test_harness/test_harness.py`
- **Default config**: `lisp/plugins/test_harness/default.json` —
  `_enabled_: false` by default; flip to `true` (or enable via the
  Plugins UI) so the server boots on startup.
- **Bind address**: `127.0.0.1:8070` (loopback only). Don't expose it.
- **Wire format**: JSON-RPC 2.0, newline-delimited, one request/response per
  socket connection (the standalone `client.py` reconnects per call).

### Two clients, one protocol

| Tool                                                | Use for                                       |
|-----------------------------------------------------|-----------------------------------------------|
| `lisp/plugins/test_harness/client.py`               | Ad-hoc CLI debugging from your shell          |
| `tests/e2e/helpers.py` (`call`, `cue_signal`, …)    | Inside E2E test scripts                       |

CLI examples:

```bash
python lisp/plugins/test_harness/client.py ping
python lisp/plugins/test_harness/client.py cue.list
python lisp/plugins/test_harness/client.py cue.add '{"type": "StopAll", "properties": {"name": "Stop"}}'
python lisp/plugins/test_harness/client.py signals.subscribe '{"signal": "cue_model.item_added"}'
```

`tests/e2e/helpers.py` wraps the same protocol with conveniences: it
generates audio test tones, manages LiSP lifecycle, parses standard
CLI flags, and provides signal-wait helpers.

### Anatomy of an E2E test

Use `tests/e2e/test_seek_cue_e2e.py` as the canonical template. All E2E
tests share this skeleton:

```python
#!/usr/bin/env python3
"""E2E tests for <feature>.

Run:
    poetry run python tests/e2e/test_<feature>_e2e.py
"""

import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from tests.e2e.helpers import (   # noqa: E402
    run_suite, call, cue_state, wait_state, stop_all, setup_with_tones,
    cue_signal, wait_for_signal,
)


def test_1_some_behaviour(t, ids):
    print("\n=== Test 1: ... ===")
    A = ids["tone_A"]

    with cue_signal(A, "started") as sub:
        call("cue.execute", {"id": A, "action": "Start"})
        ev = wait_for_signal(sub, timeout=5)
    t.check("1: tone_A reported started", ev is not None)

    stop_all()


def run_tests(t):
    ids = setup_with_tones()
    for fn in (test_1_some_behaviour,):
        try:
            fn(t, ids)
        except Exception as e:
            t.check(f"{fn.__name__} error: {e}", False)
    stop_all()


if __name__ == "__main__":
    run_suite("Feature Name", run_tests)
```

Key points:

- **`run_suite()` is the lifecycle**. It parses `--host/--port/--no-launch`,
  generates the standard tone files, starts (or attaches to) LiSP, calls
  your `run_tests(t)`, prints the summary, and `sys.exit()`s with the
  right code. You almost never need to bypass it.
- **`TestTracker` (`t`)**. `t.check("descriptive name", condition)` is
  the entire assertion API. The summary at the end prints pass/fail
  counts and lists failed checks by name — keep names searchable.
- **Wrap each test in try/except in `run_tests`**. Without it, one test
  erroring would prevent the rest from running and skew results. The
  pattern in `test_seek_cue_e2e.py` is the convention.

### Polling vs. signal-waiting

There are two ways to wait for state changes — prefer signals:

```python
# Polling — fine for properties that don't have a corresponding signal
t.check("running", wait_state(cue_id, "Running", timeout=5))

# Signal-waiting — preferred for events the harness exposes
with cue_signal(cue_id, "started") as sub:
    call("cue.execute", {"id": cue_id, "action": "Start"})
    ev = wait_for_signal(sub, timeout=5)
    t.check("started fired", ev is not None)
```

The signal pattern is more deterministic: it's not a sleep-based poll,
the wait completes the instant the event hits the buffer, and you avoid
flaky timing assertions. **Subscribe BEFORE you trigger the action**
(otherwise the event fires before the subscription exists and you wait
forever).

`signals.wait_for` accepts an optional `match` dict to filter events by
field — useful when many of the same signal type fire in a row.

### Save/load round-trip pattern

Persistence bugs are the most common reason a feature looks fine on the
golden path and breaks the next time you open the session file. The
canonical guard, taken from the SeekCue suite:

```python
SAVE_PATH = "/tmp/lisp_<feature>_e2e_test.lsp"

call("session.save", {"path": SAVE_PATH})
call("session.load", {"path": SAVE_PATH})

cues = _wait_for_count(expected)            # session.load is async
reloaded = next(c for c in cues if c["name"] == "...")
t.check("property X preserved", cue_prop(reloaded["id"], "X") == expected_value)
```

`session.load` is async — it dispatches to the main thread and returns
before cues are fully repopulated. Always poll `cue.list` until you see
the expected count before reading reloaded properties.

---

## 3. Extending the harness

Sooner or later your test will need a method the harness doesn't yet
expose. Adding one is mechanical.

### Where to edit

```
lisp/plugins/test_harness/
  handlers.py       ← add the handler, register it in the methods dict
  signal_manager.py ← if you need a new signal source the harness can
                      subscribe to (rare; existing wildcard support
                      usually suffices)
  serializers.py    ← if your handler returns a domain object that
                      isn't already serializable
```

### Adding a JSON-RPC method — recipe

**1. Write the handler inside `register_all()` in `handlers.py`.**

```python
def handle_cue_metadata(params):
    cue_id = params.get("id")
    if not cue_id:
        raise AppError("id is required")
    cue = _get_cue(cue_id)            # raises AppError if missing

    # Pure read — GIL is enough.
    return {"name": cue.name, "duration": cue.duration}
```

**2. Register it in the `methods` dict at the bottom.**

```python
methods = {
    ...
    "cue.metadata": handle_cue_metadata,
}
```

That's it for read-only methods.

### Mutation handlers MUST hop to the main thread

Anything that touches Qt widgets, mutates `CueModel`, or invokes a
`Command` must run on the Qt main thread. The harness provides
`invoke_on_main_thread()`:

```python
from lisp.plugins.test_harness.qt_invoke import invoke_on_main_thread

def handle_cue_rename(params):
    cue_id = params.get("id")
    new_name = params.get("name")
    if not cue_id or new_name is None:
        raise AppError("id and name are required")
    cue = _get_cue(cue_id)

    def _do():
        # Use the existing command for proper undo support.
        UpdateCueCommand({"name": new_name}, cue).execute_command()
        return cue.name

    return {"name": invoke_on_main_thread(_do)}
```

Important nuances:

- `invoke_on_main_thread()` blocks the server thread until the Qt main
  thread processes the event (default timeout 10s, raises `TimeoutError`
  → maps to JSON-RPC `-32001`).
- **Re-entrancy is handled**: if you happen to already be on the main
  thread, the call short-circuits and runs `fn` directly to avoid a
  self-deadlock.
- Exceptions inside `fn` propagate back through `invoke_on_main_thread`,
  so the dispatcher's normal error mapping still works:
  `AppError → -32000`, `TypeError → -32602` (invalid params), other
  exceptions → `-32603` (internal error).
- Prefer **using existing `Command` classes** (`UpdateCueCommand`,
  `ModelAddItemsCommand`, etc.) over poking at attributes directly —
  this keeps the harness path identical to the user-driven path and
  preserves undo/redo, which the `commands.*` methods can then drive.

### Error contract

Inside a handler, raise the exception type that matches the failure:

| Raise            | Becomes JSON-RPC error                  |
|------------------|------------------------------------------|
| `AppError("…")`  | `-32000` Application error               |
| `TypeError("…")` | `-32602` Invalid params                  |
| `TimeoutError`   | `-32001` Operation timed out             |
| anything else    | `-32603` Internal error (logged with traceback) |

Validate params early and clearly:

```python
if "id" not in params:
    raise AppError("id is required")
```

### Adding a new signal subscription

Most signals are already proxied through `SignalManager` via wildcard
namespace registration. If you find yourself needing a signal that
isn't reachable, look at `signal_manager.py` — the pattern is:

1. Identify the LiSP `Signal` object you want.
2. Add a registration entry mapping a JSON-RPC `signal` path string
   (e.g. `"cue_model.item_added"`) to that signal.
3. Decide what payload the harness should serialize when it fires —
   `serializers.py` has helpers for cues; add new ones for novel
   payload shapes.

Subscribers then call `signals.subscribe` with the new path.

### Adding a helper to `tests/e2e/helpers.py`

If three or more E2E tests would call the same JSON-RPC sequence,
promote it to a helper. Keep helpers thin — one verb per function —
and prefer the **subscribe-then-trigger-then-wait** signal pattern over
adding more `wait_state` polls.

---

## 4. Workflow tips

- **Lint before pushing**: `poetry run ruff check lisp/` — Ruff is
  configured for 80-char lines and Python 3.9 syntax.
- **A failing E2E gives you a live LiSP**: run the script with
  `--no-launch` against a manually-launched LiSP and add prints; the
  Test Harness CLI client lets you poke at state interactively while
  the test is paused.
- **Debug logging during E2E**: replace `"-l", "warning"` in
  `helpers.start_lisp()` with `"-l", "debug"` (or run with
  `--no-launch` against `poetry run linux-show-player -l debug`).
- **Always run the E2E suite for the area you touched** before claiming
  a feature is done. Type-checking and unit tests don't catch
  cross-layer regressions; the E2E suite is what does.
- **One E2E file per feature** is the established convention. Keep
  per-test names searchable in commit messages and CI output.
