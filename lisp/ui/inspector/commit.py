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
2. Recursively diffs against the stored snapshot.
3. On a non-empty diff, dispatches the appropriate update command
   and refreshes the snapshot.

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
        when the current `getSettings()` matches the snapshot.
        """
        if self._page is None or not self._cues:
            return
        if self._suppress_count:
            return

        current = self._page.getSettings()
        diff = _dict_diff(self._snapshot, current)
        if not diff:
            return

        stack = self._commands_stack
        if stack is None:
            # Imported lazily: Application is a singleton whose
            # module bootstraps logging and the plugin system.
            from lisp.application import Application
            stack = Application().commands_stack

        if len(self._cues) == 1:
            stack.do(UpdateCueCommand(diff, self._cues[0]))
        else:
            stack.do(UpdateCuesCommand(diff, list(self._cues)))

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
