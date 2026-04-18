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

"""Mixed-value indicator helpers for the cue inspector.

When the inspector is bound to a multi-cue selection, any field whose
value differs across cues should render a uniform "—" indicator rather
than the first cue's value, so the user can tell at a glance which
properties are shared and which diverge.

The helpers here apply (and later clear) Qt's per-widget-class
"no value" convention:

* ``QLineEdit``  → empty text, placeholder ``—``
* ``QSpinBox``   → ``setSpecialValueText('—')`` displayed at ``minimum()``
* ``QDoubleSpinBox`` → same pattern as ``QSpinBox``
* ``QComboBox``  → ``setCurrentIndex(-1)``
* ``QCheckBox``  → tri-state ``Qt.PartiallyChecked``

Widgets whose class is not one of the above are left untouched;
``InspectorCommitEngine`` (built in Step 3) is responsible for
noticing the divergence through ``getSettings()`` diffing, so a
missing visual indicator is a degradation, not a correctness bug.
"""

from typing import Iterable

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QAbstractSpinBox,
    QCheckBox,
    QComboBox,
    QLineEdit,
    QWidget,
)


MIXED_PLACEHOLDER = "—"


def is_mixed(values: Iterable) -> bool:
    """Return True iff ``values`` contains at least two distinct items.

    An empty iterable or a single-item iterable is *not* mixed —
    there is only one (or zero) values under consideration, so
    nothing is diverging.
    """
    first_set = False
    first_value = None
    for v in values:
        if not first_set:
            first_value = v
            first_set = True
            continue
        if v != first_value:
            return True
    return False


def apply_mixed_indicator(widget: QWidget) -> None:
    """Render ``widget`` as "no single value".

    Silently no-ops for widget classes the inspector does not know
    how to decorate (custom plugin widgets, layout containers, etc.).
    """
    if isinstance(widget, QLineEdit):
        widget.clear()
        widget.setPlaceholderText(MIXED_PLACEHOLDER)
        return

    if isinstance(widget, QAbstractSpinBox):
        # setSpecialValueText only displays when the spin-box is at
        # its minimum, so force the value there as well. Covers
        # QSpinBox, QDoubleSpinBox, QDateTimeEdit, et al.
        widget.setSpecialValueText(MIXED_PLACEHOLDER)
        if hasattr(widget, "setValue"):
            widget.setValue(widget.minimum())
        return

    if isinstance(widget, QCheckBox):
        widget.setTristate(True)
        widget.setCheckState(Qt.PartiallyChecked)
        return

    if isinstance(widget, QComboBox):
        widget.setCurrentIndex(-1)
        return


def clear_mixed_indicator(widget: QWidget) -> None:
    """Undo a previous ``apply_mixed_indicator`` call.

    Called once the user commits a new value on the field, at
    which point all selected cues share that value and the dash
    indicator is no longer appropriate.
    """
    if isinstance(widget, QLineEdit):
        widget.setPlaceholderText("")
        return

    if isinstance(widget, QAbstractSpinBox):
        # Emptying the special-value text turns rendering at
        # minimum back into the numeric representation.
        widget.setSpecialValueText("")
        return

    if isinstance(widget, QCheckBox):
        # Leaving tri-state enabled means the user could manually
        # cycle back to PartiallyChecked, which is nonsense once
        # the values have been reconciled.
        widget.setTristate(False)
        return

    # QComboBox: nothing to undo — once the user picks an item
    # the index is no longer -1.
    _ = widget
