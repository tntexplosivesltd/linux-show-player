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

"""QLab-style persistent cue inspector panel.

The inspector follows the layout's current selection. When cues
are selected it builds a `QTabWidget` of the settings pages that
apply to their greatest-common-superclass, loads each cue's
properties live, and installs an `InspectorCommitEngine` so edits
dispatch `UpdateCueCommand` / `UpdateCuesCommand` instances
without an "Apply" button.

For multi-cue selections, per-field divergence is detected by
loading each cue's properties in turn and comparing widget state;
divergent widgets are decorated via
`apply_mixed_indicator` (see `lisp.ui.inspector.mixed_values`).

External state changes — undo/redo, RPC edits, plugin-initiated
mutation — arrive via each cue's `property_changed` signal. The
panel reacts by re-running `loadSettings` inside the engine's
`suppressing_commits()` block so the widget setters' change
signals do not trip the engine into pushing a fresh command.
"""

import logging
from typing import Optional, Sequence

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import (
    QAbstractButton,
    QAbstractSlider,
    QAbstractSpinBox,
    QComboBox,
    QLabel,
    QLineEdit,
    QStackedWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from lisp.core.util import greatest_common_superclass
from lisp.cues.cue import Cue
from lisp.ui.inspector.commit import InspectorCommitEngine
from lisp.ui.inspector.mixed_values import (
    apply_mixed_indicator,
    clear_mixed_indicator,
)
from lisp.ui.settings.cue_settings import (
    CueSettingsRegistry,
    cue_page_sort_key,
)
from lisp.ui.settings.pages import CuePageMixin
from lisp.ui.ui_utils import escape_mnemonic, translate
from lisp.ui.widgets.cue_color_palette import CueColorPalette

logger = logging.getLogger(__name__)


# Widget classes we know how to (a) read a scalar value from for
# mixed-value detection and (b) decorate with a mixed indicator.
# Anything outside this tuple is treated as opaque — divergence on
# custom widgets simply won't be visualised.
_TRACKABLE = (
    QLineEdit,
    QAbstractSpinBox,
    QAbstractSlider,
    QAbstractButton,
    QComboBox,
    CueColorPalette,
)


def _widget_value(widget: QWidget):
    """Best-effort scalar read of a trackable widget's displayed value.

    Used only for divergence detection across a multi-cue selection;
    the result is never written back anywhere, so exact fidelity
    across every QWidget subclass is not required — we just need
    equality to be meaningful for the cases listed above.
    """
    if isinstance(widget, CueColorPalette):
        # Check this before QAbstractButton-bearing branches —
        # the palette is a QWidget containing swatch buttons, so
        # its own hex value is what matters, not any child button.
        return widget.color()
    if isinstance(widget, QLineEdit):
        return widget.text()
    if isinstance(widget, QAbstractSpinBox):
        # SpinBox / DoubleSpinBox / custom spin boxes all expose
        # `.value()` through the concrete subclass. Fall through
        # for any exotic QAbstractSpinBox without one.
        getter = getattr(widget, "value", None)
        if callable(getter):
            return getter()
        return None
    if isinstance(widget, QAbstractSlider):
        return widget.value()
    if isinstance(widget, QAbstractButton):
        # Non-checkable buttons have no meaningful state to diff;
        # `isChecked()` returns False uniformly and is ignored.
        return widget.isChecked() if widget.isCheckable() else None
    if isinstance(widget, QComboBox):
        # Index comparison, not text: empty/-1 on cleared selection
        # round-trips correctly, and items with identical text are
        # still distinguishable by slot.
        return widget.currentIndex()
    return None


class InspectorPanel(QWidget):
    """Panel that binds to the current layout selection and edits cues live.

    The owning `MainWindow` is expected to:

    * Call `attach(layout)` whenever the layout changes (or at startup).
    * Ensure `detach()` runs before the layout goes away.

    Public API consumed by the MainWindow / test harness:

    * `bind(cues)`        — force-rebuild against an explicit cue list.
    * `active_cue_ids()`  — cues currently driving the inspector.
    * `page_names()`      — display names of the visible tabs in order.
    * `set_field_value(page_name, object_name, value)` — E2E hook.
    * `flush()`           — commit pending edits without rebinding.
    """

    _EMPTY_INDEX = 0
    _CONTENT_INDEX = 1

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)

        self._engine = InspectorCommitEngine()
        self._layout = None
        self._observed_cue_model = None

        # State backing the "same selection shape" short-circuit.
        self._cues: list = []
        self._current_superclass: Optional[type] = None

        # Coalesces a burst of `property_changed` emissions into
        # one refresh per event-loop tick — undo/redo emits once
        # per changed property, so 20 edits on a single undo
        # should trigger a single reload, not twenty.
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.setInterval(0)
        self._refresh_timer.timeout.connect(self._do_external_refresh)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        self._stack = QStackedWidget(self)
        root.addWidget(self._stack)

        self._empty_label = QLabel(
            translate("InspectorPanel", "No cue selected"), self
        )
        self._empty_label.setAlignment(Qt.AlignCenter)
        self._empty_label.setEnabled(False)
        self._stack.insertWidget(self._EMPTY_INDEX, self._empty_label)

        self._tabs = QTabWidget(self)
        self._tabs.setTabPosition(QTabWidget.North)
        self._tabs.currentChanged.connect(self._on_tab_changed)
        self._stack.insertWidget(self._CONTENT_INDEX, self._tabs)

        self._stack.setCurrentIndex(self._EMPTY_INDEX)

    # ------------------------------------------------------------------
    # Layout wiring
    # ------------------------------------------------------------------

    def attach(self, layout) -> None:
        """Follow ``layout``'s selection changes."""
        if self._layout is layout:
            return
        self.detach()
        self._layout = layout
        if layout is not None:
            layout.selection_changed.connect(self._on_selection_changed)
            # Direct-bind callers (RPC, plugins) can bypass selection,
            # so we also listen for removals to drop dead references
            # without depending on the tree re-selecting something.
            cue_model = getattr(layout, "cue_model", None)
            if cue_model is not None:
                cue_model.item_removed.connect(self._on_cue_removed)
                self._observed_cue_model = cue_model
            # Seed initial state from whatever's already selected.
            self._on_selection_changed()

    def detach(self) -> None:
        if self._layout is None:
            return
        try:
            self._layout.selection_changed.disconnect(
                self._on_selection_changed
            )
        except (TypeError, ValueError):
            # Signal may already be cleared during teardown.
            pass
        cue_model = getattr(self, "_observed_cue_model", None)
        if cue_model is not None:
            try:
                cue_model.item_removed.disconnect(self._on_cue_removed)
            except (TypeError, ValueError):
                pass
            self._observed_cue_model = None
        self._layout = None
        self.bind([])

    def _on_cue_removed(self, cue) -> None:
        """Drop ``cue`` from the bound selection if present.

        Called regardless of how the inspector got bound — selection
        follow or direct `bind()`. If the removed cue was the only
        one, the panel collapses to empty; otherwise it stays bound
        to the survivors and reloads them.
        """
        if cue not in self._cues:
            return
        remaining = [c for c in self._cues if c is not cue]
        self.bind(remaining)

    # ------------------------------------------------------------------
    # Public hooks
    # ------------------------------------------------------------------

    def bind(self, cues: Sequence[Cue]) -> None:
        """Point the inspector at ``cues``; rebuild pages if needed."""
        new_cues = list(cues)

        # Flush any pending edits on the outgoing selection before
        # we swap out its pages / engine.
        self._engine.flush()
        self._disconnect_cue_signals()

        if not new_cues:
            self._cues = []
            self._current_superclass = None
            self._engine.unbind()
            self._clear_tabs()
            self._stack.setCurrentIndex(self._EMPTY_INDEX)
            return

        superclass = greatest_common_superclass(new_cues)

        # Short-circuit: if the selection's *shape* hasn't changed
        # (same GCS, same size), we can keep the existing tab row
        # and just reload data. This is the common case when the
        # user drags a rubber-band over same-type cues.
        shape_matches = (
            superclass is self._current_superclass
            and len(new_cues) == len(self._cues)
            and self._tabs.count() > 0
        )

        self._cues = new_cues
        self._current_superclass = superclass

        if not shape_matches:
            self._rebuild_tabs(superclass, new_cues)

        # Populate pages with the new cue data and rebind the
        # engine to the active tab.
        self._populate_all_pages(new_cues, single=len(new_cues) == 1)
        self._rebind_engine_to_active_tab()
        self._connect_cue_signals()

        self._stack.setCurrentIndex(self._CONTENT_INDEX)

    def flush(self) -> None:
        """Commit pending edits without touching the selection."""
        self._engine.flush()

    def active_cue_ids(self) -> list:
        return [getattr(c, "id", None) for c in self._cues]

    def page_names(self) -> list:
        return [self._tabs.tabText(i) for i in range(self._tabs.count())]

    def find_field(self, page_name: str, field_name: str) -> Optional[QWidget]:
        """Locate a field on a named page.

        Tries Qt's `objectName` registry first, then falls back to a
        Python attribute lookup on the page — settings pages don't
        normally call `setObjectName()`, but they do expose their
        editable widgets as instance attributes (e.g. `cueName`,
        `spinLoop`), so the attribute path is the practical one.
        """
        for i in range(self._tabs.count()):
            if self._tabs.tabText(i) != page_name:
                continue
            page = self._tabs.widget(i)
            widget = page.findChild(QWidget, field_name)
            if widget is not None:
                return widget
            attr = getattr(page, field_name, None)
            if isinstance(attr, QWidget):
                return attr
            return None
        return None

    def set_field_value(
        self, page_name: str, field_name: str, value
    ) -> bool:
        """Drive a field by name — used by the E2E harness.

        Returns True if the field was found and updated. The
        corresponding commit follows the normal focus-out /
        signal path, so callers must emit the right final event
        (e.g. focus-out for a QLineEdit) to push the command.
        """
        widget = self.find_field(page_name, field_name)
        if widget is None:
            return False
        return self._write_widget_value(widget, value)

    def set_group_enabled(
        self, page_name: str, group_name: str, enabled: bool
    ) -> bool:
        """Toggle a multi-edit group's "apply this property" checkbox.

        In multi-cue mode, pages wrap each editable property in a
        checkable `QGroupBox`; only checked groups contribute to
        `getSettings()` and therefore to the diff. The harness uses
        this to fan an edit out across a selection without having
        to simulate a mouse click on the group header.
        """
        widget = self.find_field(page_name, group_name)
        if widget is None or not widget.isCheckable():
            return False
        widget.setChecked(bool(enabled))
        return True

    # ------------------------------------------------------------------
    # Selection plumbing
    # ------------------------------------------------------------------

    def _on_selection_changed(self) -> None:
        if self._layout is None:
            self.bind([])
            return
        try:
            cues = list(self._layout.selected_cues())
        except AttributeError:
            cues = []
        self.bind(cues)

    # ------------------------------------------------------------------
    # Tab lifecycle
    # ------------------------------------------------------------------

    def _rebuild_tabs(self, superclass, cues) -> None:
        """Reconstruct the tab row from scratch."""
        self._engine.unbind()
        self._clear_tabs()

        if superclass is None or not issubclass(superclass, Cue):
            return

        pages = sorted(
            CueSettingsRegistry().filter(superclass), key=cue_page_sort_key
        )
        single_cue_type = type(cues[0]) if len(cues) == 1 else superclass

        for page_cls in pages:
            if issubclass(page_cls, CuePageMixin):
                widget = page_cls(single_cue_type)
            else:
                widget = page_cls()

            # enableCheck(True) hides option sub-trees that the
            # cue class doesn't support. In the dialog, passing
            # `cue is cue_class` (True) signalled multi-edit and
            # caused the page to render enable-tick-boxes; passing
            # False loaded directly. We mirror that here: single
            # cue selection → enableCheck(False); multi-cue →
            # enableCheck(True).
            widget.enableCheck(len(cues) > 1)
            self._tabs.addTab(
                widget,
                escape_mnemonic(
                    translate("SettingsPageName", page_cls.Name)
                ),
            )

    def _clear_tabs(self) -> None:
        while self._tabs.count():
            w = self._tabs.widget(0)
            self._tabs.removeTab(0)
            w.deleteLater()

    def _on_tab_changed(self, _index: int) -> None:
        # Tab switches while nothing is bound shouldn't do anything.
        if not self._cues or self._tabs.count() == 0:
            return
        # Commit edits on the outgoing page before we hand the
        # engine over to the new one.
        self._engine.flush()
        self._rebind_engine_to_active_tab()

    def _rebind_engine_to_active_tab(self) -> None:
        page = self._tabs.currentWidget()
        if page is None or not self._cues:
            self._engine.unbind()
            return
        self._engine.bind(page, self._cues)

    # ------------------------------------------------------------------
    # Page population + mixed-value detection
    # ------------------------------------------------------------------

    def _populate_all_pages(self, cues, *, single: bool) -> None:
        """Load ``cues`` into every tab, marking divergent widgets."""
        # Suppress commits while we drive setters from data — the
        # engine may already be bound to a previous tab's page at
        # this point (during a shape-matched rebind), so setter
        # signals would otherwise trip flush().
        with self._engine.suppressing_commits():
            for i in range(self._tabs.count()):
                page = self._tabs.widget(i)
                # A page raising during loadSettings (e.g. waveform
                # discovery on a cue with a missing/broken URI) must
                # not abort the rebuild — the remaining pages still
                # need their settings populated, otherwise downstream
                # tab-changes hit getSettings() on uninitialised pages.
                try:
                    self._populate_page(page, cues, single=single)
                except Exception:
                    logger.warning(
                        "Inspector: page %r failed to populate",
                        type(page).__name__,
                        exc_info=True,
                    )

    def _populate_page(self, page: QWidget, cues, *, single: bool) -> None:
        if not cues:
            return

        trackable = [
            w for w in page.findChildren(QWidget) if isinstance(w, _TRACKABLE)
        ]

        # Reset any stale mixed decoration before reloading.
        for w in trackable:
            clear_mixed_indicator(w)

        # First cue seeds the baseline view.
        if hasattr(page, "setCue"):
            page.setCue(cues[0] if single else None)
        page.loadSettings(cues[0].properties())
        if single:
            return

        baseline = {id(w): _widget_value(w) for w in trackable}
        diverged: set = set()

        for cue in cues[1:]:
            page.loadSettings(cue.properties())
            for w in trackable:
                key = id(w)
                if key in diverged:
                    continue
                if _widget_value(w) != baseline[key]:
                    diverged.add(key)

        for w in trackable:
            if id(w) in diverged:
                apply_mixed_indicator(w)

    # ------------------------------------------------------------------
    # External refresh (undo/redo, RPC, plugin mutations)
    # ------------------------------------------------------------------

    def _connect_cue_signals(self) -> None:
        for cue in self._cues:
            cue.property_changed.connect(self._on_property_changed)

    def _disconnect_cue_signals(self) -> None:
        for cue in self._cues:
            try:
                cue.property_changed.disconnect(self._on_property_changed)
            except Exception:
                # Cue may have been destroyed mid-selection change.
                pass

    def _on_property_changed(self, *_args) -> None:
        """Kick the coalesced refresh; actual work runs on next tick."""
        self._refresh_timer.start()

    def _do_external_refresh(self) -> None:
        if not self._cues or self._tabs.count() == 0:
            return
        self._populate_all_pages(
            self._cues, single=len(self._cues) == 1
        )

    # ------------------------------------------------------------------
    # Widget value writer (harness hook)
    # ------------------------------------------------------------------

    def _write_widget_value(self, widget: QWidget, value) -> bool:
        if isinstance(widget, CueColorPalette):
            # setColor accepts a canonical name or ""; unknown values
            # (including raw hex strings from legacy callers) coerce to
            # "".  Task 15 will migrate callers to pass canonical names.
            widget.setColor(value if value is not None else "")
            return True
        if isinstance(widget, QLineEdit):
            widget.setText(str(value))
            return True
        if isinstance(widget, QAbstractSpinBox):
            setter = getattr(widget, "setValue", None)
            if callable(setter):
                setter(value)
                return True
        if isinstance(widget, QAbstractSlider):
            widget.setValue(int(value))
            return True
        if isinstance(widget, QAbstractButton) and widget.isCheckable():
            widget.setChecked(bool(value))
            return True
        if isinstance(widget, QComboBox):
            idx = widget.findText(str(value))
            if idx < 0:
                try:
                    idx = int(value)
                except (TypeError, ValueError):
                    return False
            widget.setCurrentIndex(idx)
            return True
        return False
