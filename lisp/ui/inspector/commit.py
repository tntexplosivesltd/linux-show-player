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

"""Commit-and-diff engine for the QLab-style cue inspector.

The inspector edits cues live, without an "Apply" button. Instead
it watches an active `SettingsPage`, takes a snapshot of
`page.getSettings()` at bind time, and replays any delta as an
`UpdateCueCommand`/`UpdateCuesCommand` whenever the user finishes
interacting with a field.

"Finishes interacting" is detected two ways:

* A global `QApplication.focusChanged` handler catches widgets that
  only publish their final value on blur (`QLineEdit`, any
  `QAbstractSpinBox`).
* Per-widget hookups cover click-only controls whose values change
  without moving focus — sliders via `sliderReleased`, buttons
  (incl. `QCheckBox`) via `toggled`, combos via `currentIndexChanged`.

Both paths funnel into `flush()`, which:

1. Re-runs `page.getSettings()`.
2. Builds one update per bound cue from the page's edits since the
   stored snapshot (see `_cue_update`): partial for properties the
   cue merges, the whole value -- the cue's own, with the edits
   applied -- for plain dict properties it would replace. A key the
   page stops emitting means "don't touch" at the top level (a group
   dropped by `enableCheck()`) but "removed" inside a plain dict
   property (a deleted trigger type); see `_three_way`.
3. Returns if no cue's update has anything in it.
4. Otherwise dispatches the appropriate update command and refreshes
   the snapshot.

Additional `flush()` calls are issued externally at selection
change, inspector hide, session save, and app quit (Step 4 will
wire those callers in).
"""

import copy
from contextlib import contextmanager
from typing import Optional, Sequence

from PyQt5.QtWidgets import (
    QAbstractButton,
    QAbstractSlider,
    QApplication,
    QComboBox,
    QWidget,
)

from lisp.command.cue import UpdateCueCommand, UpdateCuesCommand
from lisp.core.has_properties import HasProperties
from lisp.ui.widgets.cue_color_palette import CueColorPalette


def _dict_diff(old: dict, new: dict) -> dict:
    """Recursively diff two settings dicts.

    Only keys whose value in *new* differs from *old* are included
    in the result. Nested dicts are descended into so that a tweak
    to a single sub-key doesn't pull the entire subtree along.

    Keys present in *old* but missing in *new* are ignored — pages
    may legitimately drop keys via `enableCheck()`, and we don't
    want to treat that as "clear this property".
    """
    diff = {}
    for key, new_value in new.items():
        if key not in old:
            diff[key] = new_value
            continue

        old_value = old[key]
        if isinstance(new_value, dict) and isinstance(old_value, dict):
            sub = _dict_diff(old_value, new_value)
            if sub:
                diff[key] = sub
        elif new_value != old_value:
            diff[key] = new_value
    return diff


_MISSING = object()


def _property_value(owner, key):
    """*owner*'s value for property *key*, or `_MISSING`.

    Only real properties count, matching `update_properties`, which
    ignores every other name; plain attributes (and descriptor getters
    with side effects) are never read.
    """
    if isinstance(owner, HasProperties) and key in owner.properties_names():
        return getattr(owner, key)
    return _MISSING


def _cue_update(owner, snapshot: dict, current: dict) -> dict:
    """Return the update that applies the page's edits (*snapshot* ->
    *current*) to *owner*, without losing anything *owner* holds.

    `HasProperties.update_properties` merges a dict into a nested
    properties object (`GstMediaCue.media`, its elements) but replaces
    any other property outright. So:

    * a properties object is descended into and gets a partial dict;
    * a plain dict property (`Cue.controller`, `Cue.triggers`) gets
      its whole new value, built by `_three_way` from the cue's *own*
      value -- under multi-select the page holds the last-loaded cue's
      values, and a page never shows keys it doesn't know (e.g. a
      protocol whose plugin didn't load);
    * anything else (absent, scalar, `None`) gets the plain
      `_dict_diff` delta, as before; `update_properties` ignores
      names that aren't properties.

    Keys missing from *current* are left alone at this level: pages
    drop whole groups via `enableCheck()`, which means "don't touch".

    The reverse -- a key absent from *snapshot* that *current* now has
    -- is a group the user ticked under multi-select (`enableCheck(True)`
    leaves groups unticked, so the bind-time snapshot lacks them). As
    in the legacy multi-edit dialog, ticking a group means "apply this
    group, as shown, to every selected cue": its whole value is sent
    and replaces each cue's own. Per-cue preservation applies only to
    edits within groups that were already emitted at bind time.
    """
    update = {}
    for key, new in current.items():
        old = snapshot.get(key, _MISSING)
        target = _property_value(owner, key)
        both_dicts = isinstance(new, dict) and isinstance(old, dict)

        if both_dicts and isinstance(target, HasProperties):
            sub = _cue_update(target, old, new)
            if sub:
                update[key] = sub
        elif both_dicts and isinstance(target, dict):
            if new != old:
                update[key] = _three_way(target, old, new)
        elif both_dicts:
            sub = _dict_diff(old, new)
            if sub:
                update[key] = copy.deepcopy(sub)
        elif old is _MISSING or new != old:
            update[key] = copy.deepcopy(new)
    return update


def _three_way(mine, old, new):
    """Apply the page's edit (*old* -> *new*) to *mine*, the cue's own
    value inside a plain dict property; return the result.

    *old* is what the page showed at bind time, which under
    multi-select is the last-loaded cue's value, so it only stands for
    *mine* when the two are equal:

    * ``mine == old`` (single cue, or cues that agree): take *new*
      exactly, order and all.
    * dicts: per key -- a key the page changed or added is patched
      recursively; a key it left unchanged keeps the cue's own value;
      a key it removed loses what the page showed under it
      (`_three_way(mine[key], old[key], _REMOVED)`) and is dropped
      once nothing of the cue's own is left; a key the page never
      showed is kept.
    * lists (trigger / controller rows): rows the page removed are
      removed from the cue's own list, rows it added are appended
      unless already there. Another cue's rows never land on this one.
    * anything else (scalars, type changes): take *new*.

    A key missing from *new* means "removed" here, unlike at the top
    level of a page (see `_cue_update`): the triggers and controller
    pages emit their whole dict, so a missing trigger type was deleted.
    """
    if new is _REMOVED:
        new = type(old)() if isinstance(old, (dict, list)) else _REMOVED
    if mine == old:
        return new if new is _REMOVED else copy.deepcopy(new)
    if new is _REMOVED:
        # Scalars the page removed but this cue holds differently:
        # the cue's own value was never shown, so it stays.
        return copy.deepcopy(mine)

    if isinstance(mine, dict) and isinstance(old, dict) and \
            isinstance(new, dict):
        merged = copy.deepcopy(mine)
        for key in set(old) | set(new):
            o = old.get(key, _MISSING)
            n = new.get(key, _REMOVED)
            if o is not _MISSING and n == o:
                continue
            if key not in merged:
                if n is not _REMOVED:
                    merged[key] = copy.deepcopy(n)
                continue
            if o is _MISSING:
                # Added by the page, but the cue already has the key:
                # patch it as if the page had shown an empty value.
                o = type(n)() if isinstance(n, (dict, list)) else _MISSING
            value = _three_way(merged[key], o, n)
            if value is _REMOVED or (
                n is _REMOVED and isinstance(value, (dict, list))
                and not value
            ):
                del merged[key]
            else:
                merged[key] = value
        return merged

    if isinstance(mine, list) and isinstance(old, list) and \
            isinstance(new, list):
        removed, added = _row_changes(old, new)
        rows = copy.deepcopy(mine)
        for row in removed:
            if row in rows:
                rows.remove(row)
        for row in added:
            if row not in rows:
                rows.append(copy.deepcopy(row))
        return rows

    return copy.deepcopy(new)


# Stands for "the page no longer emits this key" in `_three_way`.
_REMOVED = object()


def _row_changes(old: list, new: list):
    """Multiset difference: (rows only in *old*, rows only in *new*).
    Rows may be unhashable (lists), so this compares with ``==``."""
    removed, added = list(old), []
    for row in new:
        if row in removed:
            removed.remove(row)
        else:
            added.append(row)
    return removed, added


class InspectorCommitEngine:
    """Owns the active `SettingsPage` and pushes diffs as commands.

    Typical lifecycle from the inspector panel (Step 4):

        engine = InspectorCommitEngine()
        engine.bind(page, [cue_a, cue_b])
        # ... user edits fields, engine flushes on focus-out etc ...
        engine.flush()   # called on selection change
        engine.unbind()  # called on tear-down
    """

    def __init__(self, commands_stack=None):
        """:param commands_stack: optional CommandsStack for dispatch;
        when None the engine pulls Application().commands_stack lazily
        at flush time (so tests can avoid the singleton)."""
        self._commands_stack = commands_stack
        self._page: Optional[QWidget] = None
        self._cues: Optional[list] = None
        self._snapshot: dict = {}
        self._focus_installed = False
        # Stable bound-method reference for (dis)connect symmetry.
        self._flush_slot = self.flush
        self._focus_slot = self._on_focus_changed
        # Tracks connections made during bind() so unbind() can
        # disconnect them precisely without blanket-disconnecting
        # the underlying widgets (other subscribers may exist).
        self._widget_connections: list = []
        # Counter (not bool) so nested suppressions compose — the
        # panel may re-load settings during a tab switch while an
        # outer undo/RPC refresh is already suppressing.
        self._suppress_count: int = 0

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def bind(self, page: QWidget, cues: Sequence) -> None:
        """Start tracking ``page`` for the given ``cues``.

        A previously bound page is unbound first; repeated bind()
        calls are idempotent modulo the snapshot refresh.
        """
        if self._page is not None:
            self.unbind()

        self._page = page
        self._cues = list(cues)
        self._snapshot = copy.deepcopy(page.getSettings())
        self._install_widget_connections(page)
        self._install_focus_handler()

    def unbind(self) -> None:
        """Release the active page and disconnect all handlers.

        Safe to call when nothing is bound — no-op in that case.
        """
        if self._page is None:
            return

        self._remove_focus_handler()
        self._disconnect_widget_connections()
        self._page = None
        self._cues = None
        self._snapshot = {}

    # ------------------------------------------------------------------
    # Flush
    # ------------------------------------------------------------------

    def flush(self) -> None:
        """Push any accumulated delta as an undoable command.

        No-op when nothing is bound, when the cue list is empty, or
        when the current `getSettings()` changes nothing on any cue.
        """
        if self._page is None or not self._cues:
            return
        if self._suppress_count:
            return

        current = self._page.getSettings()
        # One update per cue: each applies the page's edits to that
        # cue's own values (see `_cue_update`).
        updates = [
            _cue_update(cue, self._snapshot, current) for cue in self._cues
        ]
        if not any(updates):
            return

        stack = self._commands_stack
        if stack is None:
            # Imported lazily: Application is a singleton whose
            # module bootstraps logging and the plugin system.
            from lisp.application import Application
            stack = Application().commands_stack

        if len(self._cues) == 1:
            stack.do(UpdateCueCommand(updates[0], self._cues[0]))
        else:
            stack.do(UpdateCuesCommand(updates, list(self._cues)))

        self._snapshot = copy.deepcopy(current)

    # Public alias so plugin-authored widgets can explicitly request
    # a commit without importing anything more specific.
    request_flush = flush

    @contextmanager
    def suppressing_commits(self):
        """Disable `flush()` within the block; refresh snapshot on exit.

        Wrap external `loadSettings()` calls (undo/redo, RPC edits)
        in this so the widget setters' change signals don't cause
        the engine to push a command reversing the external edit.
        """
        self._suppress_count += 1
        try:
            yield
        finally:
            self._suppress_count -= 1
            if self._suppress_count == 0 and self._page is not None:
                # Re-snapshot so subsequent user edits diff against
                # the post-refresh state, not the pre-refresh one.
                self._snapshot = copy.deepcopy(self._page.getSettings())

    # ------------------------------------------------------------------
    # Wiring
    # ------------------------------------------------------------------

    def _install_widget_connections(self, page: QWidget) -> None:
        """Hook widgets whose edits don't naturally trigger focus-out."""
        # Pages can request an explicit commit via commit_requested
        # whenever they finish a sub-dialog or other non-widget edit.
        commit_requested = getattr(page, "commit_requested", None)
        if commit_requested is not None:
            commit_requested.connect(self._flush_slot)
            self._widget_connections.append(
                (commit_requested, self._flush_slot)
            )

        for child in page.findChildren(QWidget):
            if isinstance(child, QAbstractSlider):
                child.sliderReleased.connect(self._flush_slot)
                self._widget_connections.append(
                    (child.sliderReleased, self._flush_slot)
                )
            if isinstance(child, QAbstractButton):
                # Non-checkable buttons never fire `toggled`, so
                # this is a no-cost hookup for e.g. plain QPushButtons.
                child.toggled.connect(self._flush_slot)
                self._widget_connections.append(
                    (child.toggled, self._flush_slot)
                )
            if isinstance(child, QComboBox):
                child.currentIndexChanged.connect(self._flush_slot)
                self._widget_connections.append(
                    (child.currentIndexChanged, self._flush_slot)
                )
            if isinstance(child, CueColorPalette):
                # The palette's child swatches are non-checkable
                # QAbstractButtons, so the generic ``toggled`` hookup
                # above never sees them. Hook the palette's own
                # ``colorPicked`` signal instead — it fires once per
                # user pick with the canonical color name attached.
                child.colorPicked.connect(self._flush_slot)
                self._widget_connections.append(
                    (child.colorPicked, self._flush_slot)
                )

    def _disconnect_widget_connections(self) -> None:
        for signal, slot in self._widget_connections:
            try:
                signal.disconnect(slot)
            except TypeError:
                # Widget already destroyed / signal already cleared.
                pass
        self._widget_connections = []

    def _install_focus_handler(self) -> None:
        if self._focus_installed:
            return
        app = QApplication.instance()
        if app is None:
            return
        app.focusChanged.connect(self._focus_slot)
        self._focus_installed = True

    def _remove_focus_handler(self) -> None:
        if not self._focus_installed:
            return
        app = QApplication.instance()
        if app is not None:
            try:
                app.focusChanged.disconnect(self._focus_slot)
            except TypeError:
                pass
        self._focus_installed = False

    def _on_focus_changed(
        self, old: Optional[QWidget], new: Optional[QWidget]
    ) -> None:
        """Flush whenever focus leaves a descendant of the active page."""
        if self._page is None or old is None:
            return
        if not self._widget_is_in_page(old):
            return
        # A move within the same page still triggers a flush: if
        # the user tabs from field A to field B, A's value should
        # commit before B's edits start accumulating a new diff.
        self.flush()

    def _widget_is_in_page(self, widget: QWidget) -> bool:
        """True iff `widget` is `self._page` or one of its descendants."""
        cursor: Optional[QWidget] = widget
        while cursor is not None:
            if cursor is self._page:
                return True
            cursor = cursor.parentWidget()
        return False
