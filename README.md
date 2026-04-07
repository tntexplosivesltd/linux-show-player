<p align="center">
    <img src="https://github.com/FrancescoCeruti/linux-show-player/blob/develop/dist/linuxshowplayer.png?raw=true" alt="Logo" width="100" height=100>
</p>
<h1 align="center">Linux Show Player</h1>
<h3 align="center">Cue player for stage productions</h3>

<p align="center">
    <a href="https://github.com/FrancescoCeruti/linux-show-player/blob/master/LICENSE"><img alt="License: GPL" src="https://img.shields.io/badge/license-GPL-blue.svg"></a>
    <a href="https://github.com/FrancescoCeruti/linux-show-player/releases/latest"><img src="https://img.shields.io/github/release/FrancescoCeruti/linux-show-player.svg?maxAge=2592000" alt="GitHub release" /></a>
    <a href="https://flathub.org/apps/org.linuxshowplayer.LinuxShowPlayer"><img alt="Flathub Downloads" src="https://img.shields.io/flathub/downloads/org.linuxshowplayer.LinuxShowPlayer?label=flathub"></a>
    <a href="https://gitter.im/linux-show-player/linux-show-player"><img src="https://img.shields.io/gitter/room/nwjs/nw.js.svg?maxAge=2592000" alt="Gitter" /></a>
    <a href="https://sonarcloud.io/summary/new_code?id=FrancescoCeruti_linux-show-player"><img src="https://sonarcloud.io/api/project_badges/measure?project=FrancescoCeruti_linux-show-player&metric=alert_status" alt="Quality Gate Status"></a>
    <a href="https://github.com/astral-sh/ruff"><img src="https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json&label=code%20style" alt="Code style: ruff"></a>
</p>

---

Linux Show Player, LiSP for short, is a free cue player, primarily intended for sound-playback during stage productions. 
The ultimate goal is to provide a complete playback software for musical plays, theatre shows, and similar.

For bugs and requests you can open an issue on the GitHub issues tracker; for support, discussions, and anything else 
you should use the [discussion](https://github.com/FrancescoCeruti/linux-show-player/discussions) section on GitHub
or the [gitter/matrix](https://gitter.im/linux-show-player/linux-show-player) chat.

Linux Show Player is currently developed and tested for **GNU/Linux** only.<br>
_The core components (Python, GStreamer and Qt) are multi-platform, thus in future - despite the name - LiSP might get ported to other platforms._

---

## 🧑‍💻 Installation

You can find the full instructions in the <a href="https://linux-show-player-users.readthedocs.io/en/latest/installation.html">user manual</a>.

### 📦 Flatpak

<a href='https://flathub.org/apps/org.linuxshowplayer.LinuxShowPlayer'>
    <img width='180' alt='Get it on Flathub' src='https://flathub.org/api/badge?locale=en'/>
</a>

Or you can get the latest **development** builds here:
 * [Master](https://github.com/FrancescoCeruti/linux-show-player/releases/tag/ci-master) - Generally stable
 * [Development](https://github.com/FrancescoCeruti/linux-show-player/releases/tag/ci-develop) - Preview features, might be unstable and untested

### 🐧 From your distribution repository

For some GNU/Linux distributions you can install a native package.<br>
Keeping in mind that it might not be the latest version, you can find a list on [repology.org](https://repology.org/metapackage/linux-show-player).

---

## 📖 Usage

The user manual can be [viewed online](http://linux-show-player-users.readthedocs.io/en/latest/index.html)

### ⌨️ Command line:

```
usage: linux-show-player [-h] [-f [FILE]] [-l {debug,info,warning}]
                         [--locale LOCALE]

Cue player for stage productions.

optional arguments:
  -h, --help            show this help message and exit
  -f [FILE], --file [FILE]
                        Session file to open
  -l {debug,info,warning}, --log {debug,info,warning}
                        Change output verbosity. default: warning
  --locale LOCALE       Force specified locale/language
```

---

## 🧪 Testing

### Unit Tests

Unit tests use [pytest](https://docs.pytest.org/) with [pytest-qt](https://pytest-qt.readthedocs.io/) for QApplication support.

```bash
poetry run pytest tests/
poetry run pytest tests/ -v          # verbose output
poetry run pytest tests/core/        # run a specific package
```

Tests are in `tests/` and mirror the source layout (`tests/core/`, `tests/cues/`, `tests/command/`).

### Test Harness Plugin (E2E Testing)

The **Test Harness** plugin (`lisp/plugins/test_harness/`) exposes LiSP internals over a JSON-RPC 2.0 TCP socket, enabling automated end-to-end testing from external tools. It is disabled by default and must be explicitly enabled.

Once enabled, start LiSP and use the standalone CLI client:

```bash
python lisp/plugins/test_harness/client.py ping
python lisp/plugins/test_harness/client.py cue.list
python lisp/plugins/test_harness/client.py cue.add '{"type": "StopAll", "properties": {"name": "My Cue"}}'
python lisp/plugins/test_harness/client.py commands.undo
```

The harness provides methods for session management, cue CRUD and control, layout operations, undo/redo, and signal subscriptions with a blocking `wait_for` mechanism for testing asynchronous cue behavior. Binds to `127.0.0.1:8070` by default.
