import importlib.util
import os

_SPEC = importlib.util.spec_from_file_location(
    "lisp_harness_client",
    os.path.join(
        os.path.dirname(__file__),
        "..", "..", "..",
        "lisp", "plugins", "test_harness", "client.py",
    ),
)
client = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(client)


def test_explicit_wins(tmp_path):
    assert client.resolve_port(9999, str(tmp_path)) == 9999


def test_env_portfile(tmp_path, monkeypatch):
    pf = tmp_path / "env.port"
    pf.write_text("5555\n")
    monkeypatch.setenv("LISP_TEST_HARNESS_PORTFILE", str(pf))
    assert client.resolve_port(None, "/anywhere") == 5555


def test_repo_root_file(tmp_path, monkeypatch):
    monkeypatch.delenv("LISP_TEST_HARNESS_PORTFILE", raising=False)
    (tmp_path / "pyproject.toml").write_text("[tool.poetry]\n")
    (tmp_path / ".lisp-test-harness-port").write_text("6666\n")
    anchor = str(tmp_path / "pkg" / "client.py")
    assert client.resolve_port(None, anchor) == 6666


def test_default_when_nothing(tmp_path, monkeypatch):
    monkeypatch.delenv("LISP_TEST_HARNESS_PORTFILE", raising=False)
    anchor = str(tmp_path / "client.py")  # no pyproject, no file
    assert client.resolve_port(None, anchor) == client.DEFAULT_PORT
