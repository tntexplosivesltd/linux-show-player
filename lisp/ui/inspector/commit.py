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
3. Drops from each update the values that cue already holds (see
   `_drop_held`): a widget can drift from the snapshot without the
   cue changing, and committing that would put a no-op on the undo
   stack and mark the session unsaved for nothing.
4. If no cue's update has anything left, refreshes the snapshot and
   returns; otherwise dispatches the appropriate update command and
   refreshes the snapshot.

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
        if old is not _MISSING and new == old:
            # Unchanged: every branch below would send nothing, so
            # don't read the cue (or walk its media elements) at all.
            continue
        target = _property_value(owner, key)
        both_dicts = isinstance(new, dict) and isinstance(old, dict)

        if both_dicts and isinstance(target, HasProperties):
            sub = _cue_update(target, old, new)
            if sub:
                update[key] = sub
        elif both_dicts and isinstance(target, dict):
            update[key] = _three_way(target, old, new)
        elif both_dicts:
            sub = _dict_diff(old, new)
            if sub:
                update[key] = copy.deepcopy(sub)
        else:
            update[key] = copy.deepcopy(new)
    return update


def _three_way(base: dict, snapshot: dict, current: dict) -> dict:
    """Apply the page's edits (*snapshot* -> *current*) to a copy of
    the plain dict *base* (the cue's own value), key by key.

    * a key the page changed or added takes the page's value;
    * a key the page removed (in *snapshot*, gone from *current*) is
      removed -- a trigger type whose last row was deleted, or one
      retyped to another type, must stop firing;
    * a key the page left unchanged keeps the cue's own value, and a
      key the page never showed (e.g. a protocol whose plugin didn't
      load) is kept as is.

    "Changed" compares the page with itself (*snapshot* vs *current*),
    never with *base*: the cue's stored rows are lists after a session
    load while pages emit tuples, so cue-vs-page equality is unreliable.

    A key missing from *current* means "removed" here, unlike at the
    top level of a page (see `_cue_update`): the triggers and
    controller pages emit their whole dict.

    Under multi-select this is per key, not per row: a changed key
    (e.g. one trigger type's rows) takes the page's value, which holds
    the last-loaded cue's rows, and a removed key is removed from
    every cue. Keys the user didn't touch keep each cue's own value.
    """
    merged = copy.deepcopy(base)
    for key in snapshot:
        if key not in current:
            merged.pop(key, None)

    for key, new in current.items():
        old = snapshot.get(key, _MISSING)
        if old is not _MISSING and new == old:
            continue
        mine = merged.get(key)
        if (
            isinstance(new, dict)
            and isinstance(old, dict)
            and isinstance(mine, dict)
        ):
            merged[key] = _three_way(mine, old, new)
        else:
            merged[key] = copy.deepcopy(new)
    return merged


def _canon(value):
    """*value* with every tuple turned into a list, at any depth.

    A cue loaded from a session holds rows as lists (`json.load`)
    while pages emit tuples, and `("B", "Start") != ["B", "Start"]`.
    """
    if isinstance(value, dict):
        return {key: _canon(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_canon(item) for item in value]
    return value


def _drop_held(owner, update: dict) -> dict:
    """Return *update* (from `_cue_update`) without the values *owner*
    already holds.

    * a properties object is descended into, matching how
      `update_properties` merges a partial dict into it;
    * any other value -- a scalar, or a plain dict property's whole
      new value -- is dropped only when *owner* holds an equal value
      (compared via `_canon`). A plain dict is never trimmed key by
      key: `update_properties` replaces it, so a partial dict would
      delete the keys left out.
    * a name that isn't a property of *owner* is kept, as before;
      only values the cue provably holds are dropped.

    A dropped value isn't written back, so it no longer fires
    `property_changed` / `changed(name)` for a value that didn't
    change.
    """
    kept = {}
    for key, value in update.items():
        target = _property_value(owner, key)
        if isinstance(value, dict) and isinstance(target, HasProperties):
            sub = _drop_held(target, value)
            if sub:
                kept[key] = sub
        elif target is _MISSING or _canon(target) != _canon(value):
            kept[key] = value
    return kept


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
        when the current `getSettings()` changes nothing on any cue:
        no edits since the snapshot, or only values each cue already
        holds.
        """
        if self._page is None or not self._cues:
            return
        if self._suppress_count:
            return

        current = self._page.getSettings()
        # One update per cue: each applies the page's edits to that
        # cue's own values (see `_cue_update`), minus what the cue
        # already holds (see `_drop_held`).
        updates = [
            _drop_held(cue, _cue_update(cue, self._snapshot, current))
            for cue in self._cues
        ]
        if not any(updates):
            # Advance the snapshot so a skipped no-op isn't re-diffed
            # on every later flush.
            self._snapshot = copy.deepcopy(current)
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
