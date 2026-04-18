"""Unit tests for `lisp.ui.inspector.commit.InspectorCommitEngine`."""

from unittest.mock import MagicMock

import pytest

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QLineEdit,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from lisp.command.cue import UpdateCueCommand, UpdateCuesCommand
from lisp.ui.inspector.commit import InspectorCommitEngine, _dict_diff
from lisp.ui.settings.pages import SettingsPage


# ---------------------------------------------------------------------------
# Helpers: a minimal SettingsPage exercising every widget class the
# engine claims to support.
# ---------------------------------------------------------------------------


class FakePage(SettingsPage):
    """Settings page wrapping a single field of each supported type.

    `getSettings()` returns a nested dict so the recursive diff is
    exercised as well.
    """

    Name = "FakePage"

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)

        self.line = QLineEdit()
        self.spin = QSpinBox()
        self.spin.setRange(0, 100)
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(0, 100)
        self.combo = QComboBox()
        self.combo.addItems(["alpha", "beta", "gamma"])
        self.check = QCheckBox()

        for w in (self.line, self.spin, self.slider, self.combo, self.check):
            layout.addWidget(w)

    def loadSettings(self, settings):
        section = settings.get("section", {})
        if "name" in section:
            self.line.setText(section["name"])
        if "count" in section:
            self.spin.setValue(section["count"])
        if "volume" in section:
            self.slider.setValue(section["volume"])
        if "mode" in section:
            idx = self.combo.findText(section["mode"])
            if idx >= 0:
                self.combo.setCurrentIndex(idx)
        if "enabled" in section:
            self.check.setChecked(section["enabled"])

    def getSettings(self):
        return {
            "section": {
                "name": self.line.text(),
                "count": self.spin.value(),
                "volume": self.slider.value(),
                "mode": self.combo.currentText(),
                "enabled": self.check.isChecked(),
            }
        }


def _make_cue(name="Cue"):
    cue = MagicMock()
    cue.name = name
    # UpdateCueCommand calls cue.properties() to snapshot old state.
    cue.properties.return_value = {}
    return cue


# ---------------------------------------------------------------------------
# _dict_diff
# ---------------------------------------------------------------------------


class TestDictDiff:
    def test_identical_returns_empty(self):
        d = {"a": 1, "b": {"x": 10}}
        assert _dict_diff(d, {"a": 1, "b": {"x": 10}}) == {}

    def test_flat_change(self):
        old = {"a": 1, "b": 2}
        new = {"a": 1, "b": 3}
        assert _dict_diff(old, new) == {"b": 3}

    def test_nested_change_includes_only_changed_leaf(self):
        old = {"s": {"x": 1, "y": 2, "z": 3}}
        new = {"s": {"x": 1, "y": 20, "z": 3}}
        assert _dict_diff(old, new) == {"s": {"y": 20}}

    def test_added_key_included(self):
        old = {"a": 1}
        new = {"a": 1, "b": 2}
        assert _dict_diff(old, new) == {"b": 2}

    def test_removed_key_ignored(self):
        """enableCheck() can drop keys; that is not a 'change' the
        inspector should try to undo by re-setting to the old value."""
        old = {"a": 1, "b": 2}
        new = {"a": 1}
        assert _dict_diff(old, new) == {}

    def test_dict_replacing_scalar_is_change(self):
        old = {"x": 5}
        new = {"x": {"inner": 1}}
        assert _dict_diff(old, new) == {"x": {"inner": 1}}


# ---------------------------------------------------------------------------
# Engine bind / unbind
# ---------------------------------------------------------------------------


@pytest.fixture
def engine_and_page(qtbot):
    page = FakePage()
    qtbot.addWidget(page)
    stack = MagicMock()
    engine = InspectorCommitEngine(commands_stack=stack)
    yield engine, page, stack
    engine.unbind()


def test_bind_snapshots_current_settings(engine_and_page):
    engine, page, stack = engine_and_page
    page.line.setText("initial")
    engine.bind(page, [_make_cue()])

    # Unchanged flush: no command should be dispatched.
    engine.flush()
    stack.do.assert_not_called()


def test_unbind_is_idempotent(engine_and_page):
    engine, _, _ = engine_and_page
    engine.unbind()  # nothing bound
    engine.unbind()  # still nothing bound


def test_bind_after_bind_replaces_page(qtbot):
    page_a = FakePage()
    page_b = FakePage()
    qtbot.addWidget(page_a)
    qtbot.addWidget(page_b)
    stack = MagicMock()
    engine = InspectorCommitEngine(commands_stack=stack)

    engine.bind(page_a, [_make_cue()])
    engine.bind(page_b, [_make_cue()])

    # Edits on page_a should no longer trigger commits.
    page_a.line.setText("orphan edit")
    engine.flush()
    stack.do.assert_not_called()

    # Edits on page_b do.
    page_b.line.setText("live edit")
    engine.flush()
    assert stack.do.call_count == 1


# ---------------------------------------------------------------------------
# Commit paths
# ---------------------------------------------------------------------------


def test_text_change_commits_via_focus_out(qtbot, engine_and_page):
    engine, page, stack = engine_and_page
    cue = _make_cue()
    engine.bind(page, [cue])

    page.line.setText("hello")
    # Simulate focus-out by emitting the global focusChanged
    # signal directly with the line-edit as the old widget.
    from PyQt5.QtWidgets import QApplication
    decoy = QWidget()
    qtbot.addWidget(decoy)
    QApplication.instance().focusChanged.emit(page.line, decoy)

    assert stack.do.call_count == 1
    command = stack.do.call_args.args[0]
    assert isinstance(command, UpdateCueCommand)


def test_slider_release_commits(engine_and_page):
    engine, page, stack = engine_and_page
    engine.bind(page, [_make_cue()])

    page.slider.setValue(42)  # no commit yet
    assert stack.do.call_count == 0

    page.slider.sliderReleased.emit()
    assert stack.do.call_count == 1


def test_checkbox_toggle_commits(engine_and_page):
    engine, page, stack = engine_and_page
    engine.bind(page, [_make_cue()])

    page.check.setChecked(True)  # setChecked emits `toggled`

    assert stack.do.call_count == 1
    command = stack.do.call_args.args[0]
    assert isinstance(command, UpdateCueCommand)


def test_combo_change_commits(engine_and_page):
    engine, page, stack = engine_and_page
    engine.bind(page, [_make_cue()])

    page.combo.setCurrentIndex(2)

    assert stack.do.call_count == 1


def test_focus_out_with_no_change_emits_nothing(qtbot, engine_and_page):
    engine, page, stack = engine_and_page
    engine.bind(page, [_make_cue()])

    from PyQt5.QtWidgets import QApplication
    decoy = QWidget()
    qtbot.addWidget(decoy)
    # Focus-out without having touched any field.
    QApplication.instance().focusChanged.emit(page.line, decoy)

    stack.do.assert_not_called()


def test_focus_out_from_widget_outside_page_is_ignored(
    qtbot, engine_and_page
):
    engine, page, stack = engine_and_page
    engine.bind(page, [_make_cue()])

    from PyQt5.QtWidgets import QApplication
    outsider = QLineEdit()
    outsider.setText("foreign")
    qtbot.addWidget(outsider)

    QApplication.instance().focusChanged.emit(outsider, None)
    stack.do.assert_not_called()


def test_empty_diff_after_flush_no_command(engine_and_page):
    engine, page, stack = engine_and_page
    engine.bind(page, [_make_cue()])

    # Edit then flush.
    page.line.setText("x")
    engine.flush()
    assert stack.do.call_count == 1

    # Immediate second flush: snapshot has been refreshed, so
    # diff is empty and no extra command should be dispatched.
    engine.flush()
    assert stack.do.call_count == 1


# ---------------------------------------------------------------------------
# Multi-cue
# ---------------------------------------------------------------------------


def test_multi_cue_uses_update_cues_command(engine_and_page):
    engine, page, stack = engine_and_page
    cues = [_make_cue("a"), _make_cue("b"), _make_cue("c")]
    engine.bind(page, cues)

    page.line.setText("bulk")
    engine.flush()

    assert stack.do.call_count == 1
    command = stack.do.call_args.args[0]
    assert isinstance(command, UpdateCuesCommand)


# ---------------------------------------------------------------------------
# Unbind disconnects
# ---------------------------------------------------------------------------


def test_unbind_stops_widget_commits(engine_and_page):
    engine, page, stack = engine_and_page
    engine.bind(page, [_make_cue()])
    engine.unbind()

    page.slider.sliderReleased.emit()
    page.check.setChecked(True)
    page.combo.setCurrentIndex(1)

    stack.do.assert_not_called()


def test_unbind_stops_focus_commits(qtbot, engine_and_page):
    engine, page, stack = engine_and_page
    engine.bind(page, [_make_cue()])
    page.line.setText("pending")
    engine.unbind()

    from PyQt5.QtWidgets import QApplication
    decoy = QWidget()
    qtbot.addWidget(decoy)
    QApplication.instance().focusChanged.emit(page.line, decoy)

    stack.do.assert_not_called()


# ---------------------------------------------------------------------------
# Diff granularity — only the edited leaf is forwarded
# ---------------------------------------------------------------------------


def test_commit_contains_only_changed_keys(engine_and_page):
    engine, page, stack = engine_and_page
    engine.bind(page, [_make_cue()])

    page.line.setText("renamed")
    engine.flush()

    command = stack.do.call_args.args[0]
    # `UpdateCueCommand` stores its new-properties dict on the
    # __new attribute (name-mangled under the class).
    new_props = command._UpdateCueCommand__new
    assert new_props == {"section": {"name": "renamed"}}


# ---------------------------------------------------------------------------
# suppressing_commits — guards against re-entrant flushes during external
# settings refresh (undo/redo, RPC edits).
# ---------------------------------------------------------------------------


class TestSuppressingCommits:
    def test_flush_is_noop_while_suppressed(self, engine_and_page):
        engine, page, stack = engine_and_page
        engine.bind(page, [_make_cue()])

        with engine.suppressing_commits():
            page.line.setText("x")
            engine.flush()
            # Widget setters during loadSettings would also call
            # flush() via their connected signals — simulate that.
            page.check.setChecked(True)

        stack.do.assert_not_called()

    def test_snapshot_refreshed_after_suppression_exits(
        self, engine_and_page
    ):
        engine, page, stack = engine_and_page
        engine.bind(page, [_make_cue()])

        with engine.suppressing_commits():
            page.line.setText("external-value")

        # New snapshot means a subsequent no-op flush doesn't
        # emit a command.
        engine.flush()
        stack.do.assert_not_called()

        # But a fresh user edit on top of the refreshed snapshot
        # still commits normally.
        page.line.setText("user-edit")
        engine.flush()
        assert stack.do.call_count == 1

    def test_nested_suppression_requires_full_unwind(
        self, engine_and_page
    ):
        engine, page, stack = engine_and_page
        engine.bind(page, [_make_cue()])

        with engine.suppressing_commits():
            with engine.suppressing_commits():
                page.line.setText("inner")
                engine.flush()
                stack.do.assert_not_called()
            # Still suppressed: outer context still active.
            page.line.setText("outer")
            engine.flush()
            stack.do.assert_not_called()

        # Fully unwound — commits resume.
        page.line.setText("after")
        engine.flush()
        assert stack.do.call_count == 1

    def test_suppression_counter_resets_on_exception(
        self, engine_and_page
    ):
        engine, page, stack = engine_and_page
        engine.bind(page, [_make_cue()])

        with pytest.raises(RuntimeError):
            with engine.suppressing_commits():
                raise RuntimeError("boom")

        # Counter must have decremented even though the block
        # raised — otherwise the engine would be permanently deaf.
        page.line.setText("after-exc")
        engine.flush()
        assert stack.do.call_count == 1

    def test_suppression_without_bound_page_is_safe(self):
        engine = InspectorCommitEngine(commands_stack=MagicMock())
        # No bind() — exercising the `_page is None` branch on
        # the exit path where snapshot refresh would otherwise run.
        with engine.suppressing_commits():
            pass
