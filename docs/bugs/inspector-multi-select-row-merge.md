# Inspector: per-row merge for plain-dict properties under multi-select

Follow-up to PR #12 (`fix/inspector-plain-dict-property-diff`). It was split
out after review round 4.

## Problem

With several cues selected, #12 merges `Cue.triggers` and `Cue.controller`
**key by key** (`_three_way` in `lisp/ui/inspector/commit.py`):

- An edited key takes the page's value. Examples are one trigger type, such
  as `Started`, or one controller protocol, such as `midi`. The page holds
  the **last-loaded cue's** rows, so every selected cue ends up with that
  cue's rows under the edited key.
- A removed key is removed from **every** selected cue, including rows the
  page never showed for that cue.

Keys the user didn't touch keep each cue's own value. Single-cue edits are
exact.

## Goal

Merge **per row**: each cue keeps its own rows, and only the rows the user
added, removed or edited are applied to it.

## Do not merge `029ea63e` as it is

This branch's head implements per-row merging. Review round 4 on #12 found
two problems with it:

1. **High: tuple rows vs list rows.** This breaks even single-cue edits.
   - A cue loaded from a session holds rows as **lists**, because sessions
     are read with `json.load` (`lisp/application.py`).
   - The triggers, MIDI and OSC pages emit **tuples**, and
     `("B", "Start") != ["B", "Start"]`.
   - As a result, `mine == old` is never true, removed rows are never found,
     and added rows are duplicated next to their list twins.
   - **Fix:** compare in a canonical form. Map tuples to lists recursively,
     recursing into dicts. Use that form for `mine == old`, for the dict
     branch's `n == o`, and for row matching. Also consider writing
     canonical values, so a cue never ends up holding a mix of list and
     tuple rows.
2. **Low: an in-place edit moves the row to the end.** An edit is treated as
   one removed row plus one appended row, so editing `x` in
   `mine=[a, x, y]` gives `[a, y, x']`. For triggers, list order is firing
   order.
   - **Fix:** pair removed and added rows that share an index in `old` and
     `new`, and replace the cue's matching row in place. Append only rows
     that are genuinely new.

## Acceptance

- The four `_PER_ROW_FOLLOW_UP` strict-xfail tests in
  `tests/ui/inspector/test_commit.py` pass, and the marker is removed:
  - `test_removed_scalar_the_cue_holds_differently_is_kept`
  - `test_multi_cue_added_row_keeps_each_cues_own_rows`
  - `test_multi_cue_removing_a_type_keeps_rows_the_page_never_showed`
  - `test_multi_cue_type_change_moves_only_the_shown_row`
- `TestSavedShowRows` keeps passing (cue state goes through a JSON round
  trip). Add multi-cue variants of it with JSON-loaded rows.
- Single-cue edits stay exact, row order included.
- Ticking an `enableCheck` group under multi-select keeps its meaning,
  "apply this group as shown", unchanged (`TestRealTriggersPage`).

## Notes

- This branch is based on `029ea63e`, not on #12's final head `da4a7a13`.
  Rebase it onto master once #12 merges.
- #11 (`fix/inspector-cue-number-noop-commit`) runs into the same
  tuple/list problem when it compares cue values with page values. Share
  the canonical comparison helper with it.
