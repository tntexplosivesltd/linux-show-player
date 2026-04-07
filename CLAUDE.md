# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Linux Show Player (LiSP) is a cue player for stage productions, built with Python/PyQt5/GStreamer. Licensed under GPLv3.

## Development Commands

```bash
# Install dependencies (uses Poetry)
poetry install

# Run the application
poetry run linux-show-player
# or with debug logging
poetry run linux-show-player -l debug

# Run with a session file
poetry run linux-show-player -f /path/to/session.lsp

# Lint (Ruff, configured in pyproject.toml: 80 char lines, py39 target)
poetry run ruff check lisp/

# Update i18n translation files
python i18n_update.py
```

### Unit Tests

```bash
# Run unit tests (pytest, requires PyQt5 — uses pytest-qt for QApplication)
poetry run pytest tests/

# Run a specific test file
poetry run pytest tests/core/test_signal.py

# Run with verbose output
poetry run pytest tests/ -v
```

Tests live in `tests/` and mirror the `lisp/` package structure (`tests/core/`, `tests/cues/`, `tests/command/`). A `mock_app` fixture in `tests/conftest.py` provides a lightweight mock of the `Application` singleton — never instantiate the real singleton in unit tests.

### Test Harness Plugin (E2E Testing)

The `test_harness` plugin (`lisp/plugins/test_harness/`) exposes LiSP internals over a JSON-RPC 2.0 TCP socket for automated end-to-end testing. Disabled by default.

```bash
# Enable the plugin (set _enabled_ to true in its config or via LiSP settings UI)
# Then start LiSP:
poetry run linux-show-player -l debug

# Use the standalone CLI client (zero LiSP dependencies):
python lisp/plugins/test_harness/client.py ping
python lisp/plugins/test_harness/client.py session.info
python lisp/plugins/test_harness/client.py cue.list
python lisp/plugins/test_harness/client.py cue.add '{"type": "StopAll", "properties": {"name": "My Cue"}}'
python lisp/plugins/test_harness/client.py signals.subscribe '{"signal": "cue_model.item_added"}'
python lisp/plugins/test_harness/client.py signals.wait_for '{"subscription_id": "...", "timeout": 5.0}'
python lisp/plugins/test_harness/client.py cue.seek '{"id": "abc-123", "position": 160000}'
python lisp/plugins/test_harness/client.py cue.add_from_uri '{"uri": "/path/to/audio.wav"}'
python lisp/plugins/test_harness/client.py layout.move_cue '{"from_index": 5, "to_index": 2}'
python lisp/plugins/test_harness/client.py layout.context_action '{"action": "Group selected", "cue_ids": ["id1", "id2"]}'
python lisp/plugins/test_harness/client.py layout.selection_mode '{"enable": true}'
python lisp/plugins/test_harness/client.py layout.select_cues '{"indices": [1, 2, 3]}'
```

The harness provides 42 methods across 7 namespaces: `session.*`, `cue.*`, `layout.*`, `commands.*`, `signals.*`, `plugin.*`, and utilities (`ping`, `app.cue_types`). Key features:

- **Full introspection**: Query and mutate cues, sessions, layout, and the undo/redo stack
- **Signal subscriptions**: Subscribe to any LiSP signal, buffer events, and use `wait_for` to block until an expected event arrives (avoids fragile `sleep()` calls)
- **Thread-safe**: Mutations dispatch to the Qt main thread via `invoke_on_main_thread`; reads are safe under the GIL
- **Localhost only**: Binds to `127.0.0.1:8070` by default

## Architecture

### Entry Point & Lifecycle

`lisp/main.py:main()` bootstraps the app: parses CLI args, sets up logging, loads config, creates QApplication, initializes `Application` singleton, loads plugins, then enters the Qt event loop. On exit, plugins are finalized before the application.

### Core Design Patterns

- **Singleton** (`lisp/core/singleton.py`): `Application`, `MainWindow`, and `PluginsManager` are singletons.
- **Custom Signal/Slot** (`lisp/core/signal.py`): Event system using weak references (not Qt signals). Signals are used throughout for decoupled communication (e.g., `session_created`, `session_loaded`).
- **Command Pattern** (`lisp/command/`): All undoable user actions go through `CommandsStack` for undo/redo support.
- **Plugin System** (`lisp/core/plugin.py`, `lisp/plugins/`): Plugins declare `Name`, `Depends`, `OptDepends`, `CorePlugin`. Loaded dynamically by `PluginsManager` with dependency resolution. Each plugin is a directory under `lisp/plugins/` with its own `__init__.py` exporting a `Plugin` subclass.
- **CueFactory** (`lisp/cues/cue_factory.py`): Registry pattern for creating cue types by name.

### Package Layout

- `lisp/core/` - Framework essentials: signals, configuration (JSON-based with default/user fallback), plugin infrastructure, session management, decorators, singleton
- `lisp/cues/` - `Cue` base class, `MediaCue` subclass, `CueModel` (model-view for cue lists), `CueFactory`
- `lisp/backend/` - Abstract `Backend` interface for audio/video playback; concrete implementation lives in `lisp/plugins/gst_backend/`
- `lisp/layout/` - `CueLayout` base for organizing/displaying cues (concrete: `cart_layout`, `list_layout` plugins)
- `lisp/command/` - Undo/redo command infrastructure
- `lisp/ui/` - Qt5 widgets, main window, settings dialogs, themes, icon themes
- `lisp/plugins/` - All functionality beyond core: GStreamer backend, MIDI, OSC, action cues, layouts, network control, timecode, presets, etc.

### Configuration

- Default config: `lisp/default.json`
- User config: `~/.config/LinuxShowPlayer/0.6/lisp.json` (JSON, layered over defaults via `JSONFileConfiguration`)
- Plugins store their own config in the user config directory

### i18n

Uses Qt Linguist `.ts`/`.qm` files. Source translations in `lisp/i18n/ts/`, compiled in `lisp/i18n/qm/`. Use `translate()` from `lisp.ui.ui_utils` for translatable strings. Crowdin is used for community translations.

### Themes

Custom theme system in `lisp/ui/themes/` with icon theme support in `lisp/ui/icons/`. Default is a dark theme with Numix-style icons.

## Code Style

- Ruff enforced: 80 char line length, Python 3.9+ target
- F401 (unused imports) and E402 (module-level import order) are globally ignored
- GPLv3 license header on all source files
