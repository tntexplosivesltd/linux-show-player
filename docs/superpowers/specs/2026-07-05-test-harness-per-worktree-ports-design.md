# Test Harness Per-Worktree Ports — Design

**Date:** 2026-07-05
**Status:** Approved (pending spec review)

## Problem

The `test_harness` plugin serves JSON-RPC on a fixed port (`8070`,
from its config). LiSP's plugin config lives in the *shared* user
config directory (`~/.config/LinuxShowPlayer/0.6/`), so every worktree's
LiSP reads the same port. Running LiSP from two worktrees at once
means the second instance either fails to bind or — worse — a stale
instance in one worktree silently intercepts JSON-RPC calls meant for
another (the failure mode recorded in the `feedback_e2e_port_clash`
memory: `Method not found` for a method you just added).

We want each worktree to get its own port **automatically** — no
session should have to remember to set or pass a port, and agents
should keep running the exact commands documented in `CLAUDE.md`
unchanged.

## Goals

- Each worktree's LiSP binds a port that does not collide with another
  worktree's LiSP, with **zero per-session configuration**.
- E2E scripts (`tests/e2e/*.py`) work unchanged — resolution lives in
  `helpers.py`, not in each script.
- The documented `client.py` commands work **verbatim** — no `--port`,
  no env var typed by a human or agent.
- The resolution rules are identical on both sides (the process that
  serves and the process that connects), so they can never disagree on
  the port.

## Non-Goals

- Running two LiSP instances from the *same* worktree simultaneously
  (unsupported; out of scope).
- Any change to the JSON-RPC protocol, methods, or serialization.
- A UI for choosing the port.

## Approach

Two cooperating mechanisms, plus one shared resolution rule.

### 1. Bind-with-fallback (server)

Today a second bind on `8070` dies with `OSError`/`EADDRINUSE`
(SO_REUSEADDR on Linux does **not** permit two live binds on the same
TCP port). We turn that failure into a fallback:

- Resolve the *desired* port from config (`8070` by default).
- Attempt to bind it.
- On `OSError` at bind (address in use), rebind to ephemeral port `0`
  and let the OS hand out a guaranteed-free port.

This makes port selection automatic and collision-free (the OS
guarantees the free port — no path-hash collision risk).

### 2. Discovery file (the shared source of truth for the port value)

After a successful bind, the server writes the **actual bound port**
(a plain integer, one line) to a discovery file. Readers never guess
the port — they read it. The port *value* is always the file's
contents, so the two sides can never disagree on the number even after
a fallback.

- **Format: a single line holding the integer port** (e.g. `41287`).
  Host is *not* stored — the harness binds localhost-only, so the port
  is the only thing that varies per worktree. Keeping it a bare integer
  lets `client.py`'s reader stay `int(path.read_text().strip())` with
  no JSON parsing (preserving its zero-LiSP-dep contract). If host ever
  becomes configurable, that's a cheap format bump later.
- **Atomic write.** The E2E helper polls for the file *while* the server
  may be writing it, so a naive write risks a torn read. The server
  writes to a temp file and `os.replace()`s it into place (atomic
  rename on POSIX): a reader sees the old file, no file, or the complete
  new one — never a partial.
- **Validating read.** Readers parse with a guarded `int(...)`; a
  stale/garbage/half-migrated file degrades to "port not found yet"
  rather than crashing.
- Default path: `<repo_root>/.lisp-test-harness-port`, where
  `repo_root` is found by walking up from the writer/reader's own
  `__file__` for `pyproject.toml`.
- The file is gitignored.
- The server removes the file in `finalize()`.

### 3. Shared port-file-path resolution rule

All three participants (server, `client.py`, `helpers.py`) locate the
discovery file by the same rule:

1. `LISP_TEST_HARNESS_PORTFILE` env var → that exact path.
2. else `<repo_root>/.lisp-test-harness-port` (walk up from `__file__`).

Resolving from **`__file__`, not cwd**, is deliberate: an agent's shell
cwd is unpredictable (repo root, a subdir, an absolute path), but each
file's on-disk location is fixed to its worktree. "The `client.py` in
worktree X" therefore always talks to "the LiSP running in worktree X."

## Flows

### E2E (`tests/e2e/helpers.py`) — automatic, launcher passes the path down

To make the two sides agree *by construction* (independent of poetry's
shared-venv/`sys.path`/cwd subtleties — see Environment Notes), the
launcher hands the child the exact path rather than having the child
recompute it:

1. Compute the portfile path from helpers' own repo root.
2. Delete any stale portfile.
3. Spawn LiSP with `LISP_TEST_HARNESS_PORTFILE=<that path>` in the child
   env and `cwd=<repo_root>`.
4. Poll for the portfile to appear → read the actual bound port → then
   `ping` / `session.info` as today.
5. `HOST`/`PORT` module state becomes resolved-at-startup rather than
   hardcoded `8070`; `call()` and friends use the resolved port.

Existing E2E scripts import `helpers` and call `start_lisp()`/`call()`
— they need **no changes**.

### Manual (`client.py`) — automatic, verbatim commands

`client.py` port resolution, first hit wins:

1. `--port` flag (unchanged, explicit).
2. `LISP_TEST_HARNESS_PORTFILE` / repo-root discovery file (walk up from
   `client.py`'s `__file__`).
3. Default `8070` (back-compat when nothing is running our way).

An agent that starts LiSP by hand in a worktree and runs
`python lisp/plugins/test_harness/client.py ping` from that worktree
just works — no port to remember. `client.py` keeps its zero-LiSP-dep
contract: it gets its own small path-finder (a few stdlib lines), not
an import from `lisp`.

### Server (`test_harness.py` / `server.py`)

1. Desired port = config `port` (`8070`).
2. Bind with fallback to ephemeral `0` on `EADDRINUSE`.
3. Write the actual bound port to the resolved portfile path
   (env-provided under E2E, repo-root default under manual launch).
4. Log the **actual** port.
5. Remove the portfile in `finalize()`.

## Environment Notes (why the launcher passes the path)

Verified in this checkout on 2026-07-05:

- Each worktree resolves `lisp` to its own copy
  (`.../linux-show-player/lisp` vs
  `.../linux-show-player.nested-groups/lisp`).
- But poetry venvs are keyed **by Python version, not by worktree**
  (`…-py3.13`, `…-py3.14`). Two worktrees on the same Python share one
  venv and thus one editable-install `.pth`. Each still loads its own
  `lisp` only because `poetry run` + the spawn's inherited cwd wins on
  `sys.path`.

Because that correctness hinges on cwd, having the child *independently*
recompute the repo root is fragile. Passing `LISP_TEST_HARNESS_PORTFILE`
from the launcher removes that dependency for the E2E path. The manual
path still recomputes from `__file__` (acceptable: the human/agent chose
which worktree's `client.py` to run).

## Components Touched

- `lisp/plugins/test_harness/server.py` — `JsonRpcServer.__init__`:
  catch `OSError` on bind, retry on port `0`.
- `lisp/plugins/test_harness/test_harness.py` — resolve portfile path,
  write actual bound port after bind, remove on `finalize()`, log the
  real port. (Shared portfile-path helper lives here or in a small
  module importable by the plugin.)
- `lisp/plugins/test_harness/client.py` — add discovery-file lookup to
  `--port` default resolution, via its own stdlib-only path-finder.
- `tests/e2e/helpers.py` — delete stale portfile, pass
  `LISP_TEST_HARNESS_PORTFILE` + `cwd` to the child, poll for the file,
  resolve `HOST`/`PORT` at startup.
- `.gitignore` — add `.lisp-test-harness-port`.
- `CLAUDE.md` — descriptive note on the auto-port behavior; retire the
  "check `pgrep` for a stale :8070" caution.
- `feedback_e2e_port_clash` memory — retire once shipped (per-worktree
  ports make the clash impossible).

## Testing

- **Unit — bind fallback:** occupy `8070`, start a second
  `JsonRpcServer`, assert it binds a different (non-zero) port and that
  the value is what a reader resolves.
- **Unit — reader precedence:** flag > env portfile > repo-root file >
  default `8070`, for both `client.py`'s finder and the shared rule.
- **Unit — portfile lifecycle:** written on start with the real port,
  removed on `finalize()`.
- **E2E smoke:** run an existing E2E script in this worktree to confirm
  the spawn → portfile → read → `ping` round-trip works end-to-end.

## Risks / Edge Cases

- **Stale portfile after a crash:** helpers delete it pre-spawn; a
  manual `client.py` read against a stale file yields a clear
  connection-refused error. Acceptable.
- **Same-worktree concurrent instances:** unsupported (out of scope) —
  they would race on the one portfile.
- **Back-compat:** with nothing else bound, the first instance still
  takes `8070` and readers still default to `8070`, so existing
  single-worktree habits are unchanged.
