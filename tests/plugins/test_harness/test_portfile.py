import os

import pytest

from lisp.plugins.test_harness import portfile


def test_find_repo_root_walks_up(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[tool.poetry]\n")
    nested = tmp_path / "a" / "b"
    nested.mkdir(parents=True)
    assert portfile.find_repo_root(str(nested)) == str(tmp_path)


def test_find_repo_root_none_when_absent(tmp_path):
    assert portfile.find_repo_root(str(tmp_path)) is None


def test_resolve_uses_env_override(tmp_path, monkeypatch):
    target = str(tmp_path / "custom.port")
    monkeypatch.setenv("LISP_TEST_HARNESS_PORTFILE", target)
    assert portfile.resolve_portfile_path("/anywhere") == target


def test_resolve_uses_repo_root(tmp_path, monkeypatch):
    monkeypatch.delenv("LISP_TEST_HARNESS_PORTFILE", raising=False)
    (tmp_path / "pyproject.toml").write_text("[tool.poetry]\n")
    anchor = str(tmp_path / "pkg" / "mod.py")
    expected = str(tmp_path / ".lisp-test-harness-port")
    assert portfile.resolve_portfile_path(anchor) == expected


def test_resolve_falls_back_to_cwd(tmp_path, monkeypatch):
    monkeypatch.delenv("LISP_TEST_HARNESS_PORTFILE", raising=False)
    monkeypatch.chdir(tmp_path)
    # anchor with no pyproject.toml ancestor → find_repo_root returns
    # None, so resolve_portfile_path falls back to cwd.
    anchor = str(tmp_path / "no_repo" / "mod.py")
    expected = os.path.join(os.getcwd(), portfile.PORTFILE_NAME)
    assert portfile.resolve_portfile_path(anchor) == expected


def test_write_is_atomic_and_read_roundtrips(tmp_path):
    path = str(tmp_path / ".lisp-test-harness-port")
    portfile.write_port(path, 41287)
    assert portfile.read_port(path) == 41287
    # No leftover temp files in the directory.
    assert os.listdir(tmp_path) == [".lisp-test-harness-port"]


def test_read_missing_returns_none(tmp_path):
    assert portfile.read_port(str(tmp_path / "nope")) is None


def test_read_garbage_returns_none(tmp_path):
    path = tmp_path / ".lisp-test-harness-port"
    path.write_text("not-a-port\n")
    assert portfile.read_port(str(path)) is None


@pytest.mark.parametrize("value", ["-5", "999999", "70000"])
def test_read_out_of_range_returns_none(tmp_path, value):
    # Parses as an int but is not a valid TCP port — must degrade to
    # None rather than flow into socket.connect() and raise OverflowError.
    path = tmp_path / ".lisp-test-harness-port"
    path.write_text(f"{value}\n")
    assert portfile.read_port(str(path)) is None


def test_write_closes_fd_when_fdopen_fails(tmp_path, monkeypatch):
    path = str(tmp_path / ".lisp-test-harness-port")

    closed = []
    real_close = os.close
    monkeypatch.setattr(
        os, "close", lambda fd: (closed.append(fd), real_close(fd))[0]
    )

    def boom(fd, mode):
        raise MemoryError("simulated fdopen failure")

    monkeypatch.setattr(os, "fdopen", boom)

    with pytest.raises(MemoryError):
        portfile.write_port(path, 8070)

    # The raw fd was closed (no descriptor leak) and no temp file or
    # target file was left behind.
    assert closed
    assert os.listdir(tmp_path) == []


def test_remove_is_idempotent(tmp_path):
    path = str(tmp_path / ".lisp-test-harness-port")
    portfile.write_port(path, 9)
    portfile.remove_portfile(path)
    portfile.remove_portfile(path)  # no error second time
    assert portfile.read_port(path) is None
