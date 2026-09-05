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

"""Unit tests for run_suite's port resolution (tests/e2e/helpers).

Covers the ``--no-launch`` discovery-file branch and the launch-path
precedence of an explicit ``--port`` — logic that otherwise only runs
during a live E2E attach.
"""

from types import SimpleNamespace

import pytest

from tests.e2e import helpers


def _args(port=None, no_launch=False):
    return SimpleNamespace(port=port, no_launch=no_launch)


def test_no_launch_reads_discovery_file(tmp_path, monkeypatch):
    pf = tmp_path / ".lisp-test-harness-port"
    pf.write_text("54321\n")
    monkeypatch.setattr(helpers, "_PORTFILE", str(pf))
    assert helpers.resolve_suite_port(_args(no_launch=True)) == 54321


def test_no_launch_missing_file_exits_2(tmp_path, monkeypatch):
    monkeypatch.setattr(helpers, "_PORTFILE", str(tmp_path / "nope"))
    with pytest.raises(SystemExit) as exc:
        helpers.resolve_suite_port(_args(no_launch=True))
    assert exc.value.code == 2


def test_explicit_port_bypasses_portfile_in_attach_mode(monkeypatch):
    # --port with --no-launch must win without touching the portfile.
    def fail(_path):
        raise AssertionError("portfile should not be read")

    monkeypatch.setattr(helpers.portfile, "read_port", fail)
    assert helpers.resolve_suite_port(_args(port=9999, no_launch=True)) == 9999


def test_launch_mode_returns_none_and_ignores_port(capsys):
    # On the launch path the child auto-selects its port, so --port
    # cannot take effect: resolve returns None (start_lisp resolves it)
    # and a warning is emitted rather than silently honoring the flag.
    assert helpers.resolve_suite_port(_args(port=9999)) is None
    assert "ignored" in capsys.readouterr().err


def test_launch_mode_no_port_returns_none(capsys):
    assert helpers.resolve_suite_port(_args()) is None
    assert capsys.readouterr().err == ""
