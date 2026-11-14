"""E2E pass / fail / SKIP accounting (tests/e2e/tracker.py, run_all.py).

A script that checked nothing (missing tools, no window manager) must
not be counted as a pass: it exits EXIT_SKIP, and run_all reports it
apart from passes and failures and never retries it.
"""

import sys

import pytest

from tests.e2e import run_all
from tests.e2e.tracker import EXIT_SKIP, TestTracker


class TestTrackerExitCodes:
    def test_all_passed_is_0(self):
        t = TestTracker()
        t.check("a", True)
        assert t.summary() == 0

    def test_a_failure_is_1(self):
        t = TestTracker()
        t.check("a", False)
        assert t.summary() == 1

    def test_skip_is_exit_skip(self, capsys):
        t = TestTracker()
        t.skip("need X display")
        assert t.summary() == EXIT_SKIP
        out = capsys.readouterr().out
        assert "SKIP: need X display" in out
        assert "SKIPPED" in out

    def test_skip_after_passing_checks_is_still_a_skip(self):
        # The fit E2E passes its set-up checks, then finds no WM: the
        # thing it exists to test never ran.
        t = TestTracker()
        t.check("set-up", True)
        t.skip("no window manager")
        assert t.summary() == EXIT_SKIP

    def test_failure_wins_over_skip(self):
        t = TestTracker()
        t.check("set-up", False)
        t.skip("no window manager")
        assert t.summary() == 1

    def test_exit_skip_is_not_a_pass_or_plain_failure(self):
        assert EXIT_SKIP not in (0, 1, 2)


def _script(tmp_path, code):
    path = tmp_path / f"exit_{code}.py"
    path.write_text(f"import sys\nsys.exit({code})\n")
    return str(path)


class TestRunOne:
    @pytest.mark.parametrize("code, status", [
        (0, "passed"), (1, "failed"), (2, "failed"),
        (EXIT_SKIP, "skipped"),
    ])
    def test_status_from_exit_code(self, tmp_path, code, status):
        assert run_all.run_one(_script(tmp_path, code), 30) == status


class TestMain:
    def _main(self, monkeypatch, results):
        """Run main() over fake scripts; results: name -> list of
        statuses returned by successive attempts."""
        attempts = {name: list(seq) for name, seq in results.items()}
        calls = []

        def run_one(path, timeout):
            calls.append(path)
            return attempts[path].pop(0)

        monkeypatch.setattr(run_all, "discover", lambda _p: list(results))
        monkeypatch.setattr(run_all, "kill_stale", lambda: None)
        monkeypatch.setattr(run_all, "run_one", run_one)
        monkeypatch.setattr(sys, "argv", ["run_all.py"])
        return run_all.main(), calls

    def test_skip_is_reported_apart_and_not_retried(self, monkeypatch,
                                                    capsys):
        code, calls = self._main(monkeypatch, {
            "a.py": ["passed"], "b.py": ["skipped"],
        })
        out = capsys.readouterr().out
        assert code == 0
        assert calls == ["a.py", "b.py"]  # b not retried
        assert "1 passed, 0 failed, 1 skipped" in out
        assert "SKIPPED: b.py" in out

    def test_failure_still_fails_the_run(self, monkeypatch):
        code, _ = self._main(monkeypatch, {
            "a.py": ["failed", "failed"], "b.py": ["skipped"],
        })
        assert code == 1

    def test_retry_that_skips_is_a_skip(self, monkeypatch, capsys):
        code, _ = self._main(monkeypatch, {"a.py": ["failed", "skipped"]})
        assert code == 0
        assert "SKIPPED: a.py" in capsys.readouterr().out
