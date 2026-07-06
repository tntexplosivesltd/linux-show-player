#!/usr/bin/env python3
"""Serial runner for the standalone E2E test scripts.

Each tests/e2e/test_*.py is its own LiSP lifecycle driven over the
harness on a fixed port (127.0.0.1:8070), so they MUST run one at a
time. This runner discovers them, runs each in a subprocess with a
timeout and an optional retry, kills any stale LiSP between runs, and
returns a single aggregate exit code (0 = all passed, 1 = any failed).

Run:
    poetry run python tests/e2e/run_all.py
    poetry run python tests/e2e/run_all.py --filter 'test_video*.py'
    poetry run python tests/e2e/run_all.py --list
"""

import argparse
import glob
import os
import subprocess
import sys
import time

E2E_DIR = os.path.dirname(os.path.abspath(__file__))


def discover(pattern):
    """Return sorted absolute paths of matching test scripts."""
    paths = sorted(glob.glob(os.path.join(E2E_DIR, pattern)))
    return [p for p in paths if os.path.basename(p) != "run_all.py"]


def kill_stale():
    """Kill any LiSP left holding the harness port."""
    subprocess.run(
        ["pkill", "-f", "lisp.main"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    time.sleep(1)


def run_one(path, timeout):
    """Run one test script; return True on exit code 0."""
    try:
        result = subprocess.run([sys.executable, path], timeout=timeout)
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        print(f"  TIMEOUT after {timeout}s", flush=True)
        return False


def main():
    parser = argparse.ArgumentParser(description="Run all E2E tests serially.")
    parser.add_argument("--retries", type=int, default=1,
                        help="Extra attempts per failing test (default 1).")
    parser.add_argument("--timeout", type=int, default=180,
                        help="Per-test timeout in seconds (default 180).")
    parser.add_argument("--filter", default="test_*.py",
                        help="Glob selecting test files (default test_*.py).")
    parser.add_argument("--list", action="store_true",
                        help="List discovered tests and exit.")
    args = parser.parse_args()

    tests = discover(args.filter)
    if not tests:
        print(f"No tests match {args.filter!r}", file=sys.stderr)
        return 1

    if args.list:
        for t in tests:
            print(os.path.basename(t))
        print(f"\n{len(tests)} test(s)")
        return 0

    passed, failed, retried = [], [], []
    for path in tests:
        name = os.path.basename(path)
        print(f"\n{'=' * 60}\nRUN {name}\n{'=' * 60}", flush=True)
        kill_stale()
        ok = run_one(path, args.timeout)
        attempt = 0
        while not ok and attempt < args.retries:
            attempt += 1
            print(f"--- {name} FAILED, retry {attempt}/{args.retries} ---",
                  flush=True)
            kill_stale()
            ok = run_one(path, args.timeout)
        if ok:
            passed.append(name)
            if attempt:
                retried.append(name)
        else:
            failed.append(name)
        kill_stale()

    print(f"\n{'=' * 60}")
    print(f"SUMMARY: {len(passed)} passed, {len(failed)} failed, "
          f"{len(retried)} needed retry")
    print(f"{'=' * 60}")
    if retried:
        print("RETRIED (flaky): " + ", ".join(retried))
    if failed:
        print("FAILED: " + ", ".join(failed))
        return 1
    print("ALL GREEN")
    return 0


if __name__ == "__main__":
    sys.exit(main())
