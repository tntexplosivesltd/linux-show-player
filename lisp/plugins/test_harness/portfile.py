# This file is part of Linux Show Player
#
# Copyright 2024 Linux Show Player Contributors
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

"""Discovery-file helpers for the test harness port.

Stdlib-only so the server (inside the lisp package) and the E2E
helpers can share one implementation. ``client.py`` keeps its own
inlined copy to stay dependency-free.
"""

import os
import tempfile

PORTFILE_NAME = ".lisp-test-harness-port"
PORTFILE_ENV = "LISP_TEST_HARNESS_PORTFILE"


def find_repo_root(anchor):
    """Walk up from ``anchor`` for a dir containing pyproject.toml."""
    path = os.path.abspath(anchor)
    if os.path.isfile(path):
        path = os.path.dirname(path)
    while True:
        if os.path.isfile(os.path.join(path, "pyproject.toml")):
            return path
        parent = os.path.dirname(path)
        if parent == path:
            return None
        path = parent


def resolve_portfile_path(anchor):
    """Resolve the discovery-file path: env override, else repo root."""
    override = os.environ.get(PORTFILE_ENV)
    if override:
        return override
    root = find_repo_root(anchor) or os.getcwd()
    return os.path.join(root, PORTFILE_NAME)


def _unlink_quiet(path):
    """Unlink ``path``, ignoring absence."""
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass


def write_port(path, port):
    """Atomically write ``port`` (temp file + os.replace)."""
    directory = os.path.dirname(path) or "."
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".portfile-")
    try:
        f = os.fdopen(fd, "w")
    except BaseException:
        # os.fdopen only takes ownership of fd once it returns; if it
        # raised, close the raw descriptor ourselves to avoid a leak.
        os.close(fd)
        _unlink_quiet(tmp)
        raise
    try:
        with f:
            f.write(f"{port}\n")
        os.replace(tmp, path)
    except BaseException:
        _unlink_quiet(tmp)
        raise


def read_port(path):
    """Return the int port, or None if missing/empty/out of range."""
    try:
        with open(path) as f:
            port = int(f.read().strip())
    except (OSError, ValueError):
        return None
    return port if 0 <= port <= 65535 else None


def remove_portfile(path):
    """Unlink the discovery file, ignoring absence."""
    _unlink_quiet(path)
