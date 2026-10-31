---
name: next-bug
description: Use when asked to pick up, start, or work the next bug/finding from the merge-review bug list (docs/bugs/2026-07-06-merge-review-findings.md) — triggers like "next bug", "work through the findings", "fix the next item", "grab the next one off the list".
---

# next-bug

## Overview

Pick up the next outstanding item from the merge-review to-fix list and take it end-to-end: re-verify it still applies, fix it test-first, then check it off. The list is severity-ordered (Critical → Low), so top-down = highest priority first.

- List: `docs/bugs/2026-07-06-merge-review-findings.md`
- Full per-finding verifier evidence (outside the repo): `~/merge-review/consolidated.json`

**REQUIRED SUB-SKILL:** Use superpowers:test-driven-development for the fix.
**REQUIRED:** Use superpowers:verification-before-completion before checking an item off.

## Steps

1. **Find the next item** — first unchecked box, top-down:
   ```bash
   grep -nE '^- \[ \] \*\*[CHML][0-9]+\*\*' docs/bugs/2026-07-06-merge-review-findings.md | head -1
   ```
   Read that item's full block: ID, location, source merge, reviewer(s), detail, and the suggested fix.

2. **Re-verify it still applies.** The findings were verified against master at generation time (2026-07-06) and may be stale. Open the cited file/symbol and confirm the problem is really present in the *current* tree. If it is already resolved or was a misread, tick it `- [x]` with `— verified fixed / N-A: <reason>` and stop — do not invent a change.

3. **Fix it test-first.** Write the failing regression test that asserts the *behaviour* the finding is about, watch it fail, then make the minimal change. Many of these findings exist precisely *because* the original test asserted a proxy instead of the real outcome — assert the real invariant (e.g. for C1, that `GroupCue._resolve_children()` includes the promoted child ids, not just that `group_id` was rewritten).

4. **Verify.** Run the new test plus the relevant suite (`poetry run pytest tests/...`; run the E2E flow per CLAUDE.md if the finding is runtime-observable). Evidence before claiming done.

5. **Check it off.** Flip `- [ ]` → `- [x]` for that ID and append `— <short what/how + commit sha>`. Commit the fix and the ticked list together on a branch (never `master`; branch per bug, or per themed cluster of related IDs).

## Quick reference

| Need | Command |
|---|---|
| Next open item | `grep -nE '^- \[ \] \*\*[CHML][0-9]+\*\*' <list> \| head -1` |
| Progress | done `grep -cE '^- \[x\]' <list>` / open `grep -cE '^- \[ \]' <list>` |
| Jump to an ID | `grep -nE '\*\*H12\*\*' <list>` |

`<list>` = `docs/bugs/2026-07-06-merge-review-findings.md`

## Common mistakes

- **Fixing before re-verifying.** The list is a dated snapshot; code moves. Confirm the issue is live first (step 2).
- **Asserting the proxy, not the behaviour.** Repeating the original test's mistake leaves the bug. Assert the real outcome.
- **Ticking without evidence.** Only `- [x]` after the test passes or the behaviour is observed.
- **Committing to `master`.** Branch first.
- **Silent skips.** If you skip an item (too big, needs a decision), leave it `- [ ]` and say so — don't tick it.
