import os

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


def test_remove_is_idempotent(tmp_path):
    path = str(tmp_path / ".lisp-test-harness-port")
    portfile.write_port(path, 9)
    portfile.remove_portfile(path)
    portfile.remove_portfile(path)  # no error second time
    assert portfile.read_port(path) is None
