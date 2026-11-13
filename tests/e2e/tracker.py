# This file is part of Linux Show Player
#
# Copyright 2026 Francesco Ceruti <ceppofrancy@gmail.com>
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

"""Pass / fail / SKIP accounting for the E2E scripts.

Standard library only and free of import-time side effects, so unit
tests and run_all.py can import it (helpers.py re-exports it).
"""

# A script that checked nothing (missing tools, no window manager)
# exits with this, so run_all reports it apart from passes. 77 is the
# automake "skipped" status.
EXIT_SKIP = 77


class TestTracker:
    """Tracks pass/fail counts, failure names and a skip reason."""

    __test__ = False  # not a pytest test class

    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.errors = []
        self.skipped = None

    def check(self, name, condition):
        """Assert with pass/fail tracking and printing."""
        if condition:
            self.passed += 1
            print(f"  PASS: {name}")
        else:
            self.failed += 1
            self.errors.append(name)
            print(f"  FAIL: {name}")

    def skip(self, reason):
        """Mark the run as skipped: what it exists to test could not
        run here. A failure recorded as well still fails the run."""
        self.skipped = reason
        print(f"  SKIP: {reason}")

    def summary(self):
        """Print the final summary and return the exit code: 1 if any
        check failed, else EXIT_SKIP if skipped, else 0."""
        print(f"\n{'=' * 40}")
        print(f"  {self.passed} passed, {self.failed} failed")
        if self.errors:
            print(f"  Failures: {', '.join(self.errors)}")
        if self.skipped is not None:
            print(f"  SKIPPED: {self.skipped}")
        print(f"{'=' * 40}")
        if self.failed:
            return 1
        return EXIT_SKIP if self.skipped is not None else 0
