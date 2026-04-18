"""Unit tests for `lisp.ui.inspector.mixed_values`."""

import pytest

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QLineEdit,
    QSpinBox,
    QWidget,
)

from lisp.ui.inspector.mixed_values import (
    MIXED_PLACEHOLDER,
    apply_mixed_indicator,
    clear_mixed_indicator,
    is_mixed,
)


# ---------------------------------------------------------------------------
# is_mixed
# ---------------------------------------------------------------------------


class TestIsMixed:
    def test_empty_is_not_mixed(self):
        assert is_mixed([]) is False

    def test_single_value_is_not_mixed(self):
        assert is_mixed([42]) is False

    def test_all_equal_is_not_mixed(self):
        assert is_mixed([1, 1, 1]) is False

    def test_two_distinct_values_is_mixed(self):
        assert is_mixed([1, 2]) is True

    def test_detects_divergence_at_tail(self):
        assert is_mixed([7, 7, 7, 8]) is True

    def test_works_with_strings(self):
        assert is_mixed(["a", "a", "b"]) is True

    def test_works_with_none(self):
        assert is_mixed([None, None]) is False
        assert is_mixed([None, 0]) is True

    def test_accepts_any_iterable(self):
        assert is_mixed(iter([1, 1])) is False
        assert is_mixed(iter([1, 2])) is True


# ---------------------------------------------------------------------------
# apply_mixed_indicator / clear_mixed_indicator per widget class
# ---------------------------------------------------------------------------


class TestLineEdit:
    def test_apply_clears_text_and_sets_placeholder(self, qtbot):
        w = QLineEdit()
        qtbot.addWidget(w)
        w.setText("alpha")

        apply_mixed_indicator(w)

        assert w.text() == ""
        assert w.placeholderText() == MIXED_PLACEHOLDER

    def test_clear_removes_placeholder(self, qtbot):
        w = QLineEdit()
        qtbot.addWidget(w)
        apply_mixed_indicator(w)

        clear_mixed_indicator(w)

        assert w.placeholderText() == ""


class TestSpinBox:
    def test_apply_shows_placeholder_at_minimum(self, qtbot):
        w = QSpinBox()
        qtbot.addWidget(w)
        w.setMinimum(0)
        w.setMaximum(100)
        w.setValue(42)

        apply_mixed_indicator(w)

        assert w.specialValueText() == MIXED_PLACEHOLDER
        assert w.value() == w.minimum()

    def test_clear_empties_special_value_text(self, qtbot):
        w = QSpinBox()
        qtbot.addWidget(w)
        apply_mixed_indicator(w)

        clear_mixed_indicator(w)

        assert w.specialValueText() == ""


class TestDoubleSpinBox:
    def test_apply_shows_placeholder_at_minimum(self, qtbot):
        w = QDoubleSpinBox()
        qtbot.addWidget(w)
        w.setMinimum(-10.0)
        w.setMaximum(10.0)
        w.setValue(3.14)

        apply_mixed_indicator(w)

        assert w.specialValueText() == MIXED_PLACEHOLDER
        assert w.value() == w.minimum()

    def test_clear_empties_special_value_text(self, qtbot):
        w = QDoubleSpinBox()
        qtbot.addWidget(w)
        apply_mixed_indicator(w)

        clear_mixed_indicator(w)

        assert w.specialValueText() == ""


class TestCheckBox:
    def test_apply_enables_tristate_and_partially_checks(self, qtbot):
        w = QCheckBox()
        qtbot.addWidget(w)
        w.setChecked(True)

        apply_mixed_indicator(w)

        assert w.isTristate() is True
        assert w.checkState() == Qt.PartiallyChecked

    def test_clear_disables_tristate(self, qtbot):
        w = QCheckBox()
        qtbot.addWidget(w)
        apply_mixed_indicator(w)

        clear_mixed_indicator(w)

        assert w.isTristate() is False


class TestComboBox:
    def test_apply_clears_selection(self, qtbot):
        w = QComboBox()
        qtbot.addWidget(w)
        w.addItems(["alpha", "beta", "gamma"])
        w.setCurrentIndex(1)

        apply_mixed_indicator(w)

        assert w.currentIndex() == -1

    def test_clear_is_noop(self, qtbot):
        """Nothing to undo — once the user picks an item the index
        moves on its own; clear_mixed_indicator must not blow up
        on a fresh QComboBox."""
        w = QComboBox()
        qtbot.addWidget(w)
        w.addItems(["a", "b"])
        w.setCurrentIndex(0)

        clear_mixed_indicator(w)  # no exception

        assert w.currentIndex() == 0


class TestUnknownWidget:
    def test_apply_is_silent_noop(self, qtbot):
        """Custom widgets the inspector doesn't know about must be
        left untouched rather than raising."""
        w = QWidget()
        qtbot.addWidget(w)

        apply_mixed_indicator(w)
        clear_mixed_indicator(w)

        assert w is w  # smoke — no exception raised


# ---------------------------------------------------------------------------
# Roundtrip: apply → clear restores a usable widget
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "widget_factory",
    [
        lambda: QLineEdit(),
        lambda: QSpinBox(),
        lambda: QDoubleSpinBox(),
        lambda: QCheckBox(),
        lambda: QComboBox(),
    ],
)
def test_apply_then_clear_leaves_widget_usable(qtbot, widget_factory):
    w = widget_factory()
    qtbot.addWidget(w)
    if isinstance(w, QComboBox):
        w.addItems(["a", "b"])

    apply_mixed_indicator(w)
    clear_mixed_indicator(w)

    # Post-clear we can still interact with the widget through
    # its normal API without the mixed-indicator state leaking
    # back in.
    if isinstance(w, QLineEdit):
        w.setText("hello")
        assert w.text() == "hello"
        assert w.placeholderText() == ""
    elif isinstance(w, QSpinBox):
        w.setValue(5)
        assert w.value() == 5
        assert w.specialValueText() == ""
    elif isinstance(w, QDoubleSpinBox):
        w.setValue(1.5)
        assert w.value() == 1.5
        assert w.specialValueText() == ""
    elif isinstance(w, QCheckBox):
        w.setChecked(True)
        assert w.isChecked() is True
        assert w.isTristate() is False
    elif isinstance(w, QComboBox):
        w.setCurrentIndex(1)
        assert w.currentIndex() == 1
