"""Unit tests for `lisp.ui.inspector.commit.InspectorCommitEngine`."""

import copy
import json
from unittest.mock import MagicMock, patch

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
from lisp.core.has_properties import HasProperties
from lisp.core.properties import Property
from lisp.cues.cue import Cue, CueAction
from lisp.ui.inspector.commit import (
    InspectorCommitEngine,
    _dict_diff,
    _cue_update,
)
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


def test_palette_color_pick_commits(qtbot):
    """Clicking a palette swatch fires ``colorPicked``. The palette's
    internal ``_Swatch`` buttons aren't checkable (the palette owns
    selection visually, not via Qt state), so the generic
    ``QAbstractButton.toggled`` hookup never fires. The commit engine
    has to hook ``colorPicked`` explicitly or the inspector's live-
    edit contract silently breaks for colour changes."""
    from PyQt5.QtWidgets import QVBoxLayout

    from lisp.ui.settings.pages import SettingsPage
    from lisp.ui.widgets.cue_color_palette import CueColorPalette

    class PalettePage(SettingsPage):
        Name = "PalettePage"

        def __init__(self, parent=None):
            super().__init__(parent)
            layout = QVBoxLayout(self)
            self.palette = CueColorPalette()
            layout.addWidget(self.palette)

        def loadSettings(self, settings):
            self.palette.setColor(settings.get("bg", ""))

        def getSettings(self):
            return {"bg": self.palette.color()}

    page = PalettePage()
    qtbot.addWidget(page)
    stack = MagicMock()
    engine = InspectorCommitEngine(commands_stack=stack)
    engine.bind(page, [_make_cue()])

    # Simulate a user click on the Red swatch — ``_Swatch.click()``
    # routes through the palette's internal slot, which emits
    # ``colorPicked``.
    page.palette.swatches()[1].click()

    assert stack.do.call_count == 1
    command = stack.do.call_args.args[0]
    assert isinstance(command, UpdateCueCommand)

    engine.unbind()


def test_commit_requested_signal_triggers_flush(engine_and_page):
    """Pages can ask the engine to commit via the inherited
    ``commit_requested`` signal — covers modal sub-dialogs (e.g. the
    icon picker) where the underlying widget never receives a
    focus-out event."""
    engine, page, stack = engine_and_page
    engine.bind(page, [_make_cue()])

    page.line.setText("changed via modal dialog")
    page.commit_requested.emit()

    assert stack.do.call_count == 1
    command = stack.do.call_args.args[0]
    assert isinstance(command, UpdateCueCommand)


def test_commit_requested_with_no_change_is_noop(engine_and_page):
    engine, page, stack = engine_and_page
    engine.bind(page, [_make_cue()])

    # No edit; emitting the signal should not synthesise a phantom
    # update command.
    page.commit_requested.emit()

    stack.do.assert_not_called()


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


_SECTION = {
    "name": "",
    "count": 0,
    "volume": 0,
    "mode": "alpha",
    "enabled": False,
}


class _Section(HasProperties):
    """`FakePage`'s section as a nested properties object, the way
    `GstMediaCue.media` is: `update_properties` merges into it."""

    name = Property(default="")
    count = Property(default=0)
    volume = Property(default=0)
    mode = Property(default="alpha")
    enabled = Property(default=False)


class _NestedSectionCue(HasProperties):
    name = Property(default="Cue")
    section = Property(default=_Section.class_defaults())

    def __init__(self):
        super().__init__()
        self.section = _Section()


class _PlainSectionCue(HasProperties):
    """`FakePage`'s section as a plain dict property, the way
    `Cue.controller` is: `update_properties` replaces it whole."""

    name = Property(default="Cue")
    section = Property(default={})

    def __init__(self):
        super().__init__()
        self.section = dict(_SECTION)


def _committed(stack, command_cls=UpdateCueCommand):
    """What the last pushed command applies: its properties dict, or
    for `UpdateCuesCommand` the list of dicts, one per cue.

    Runs a shallow copy of the command with `update_properties`
    stubbed, so neither the cues nor the pushed command (which some
    tests `do()` afterwards) change.
    """
    command = stack.do.call_args.args[0]
    assert isinstance(command, command_cls)
    with patch.object(
        HasProperties, "update_properties", autospec=True
    ) as update_properties:
        copy.copy(command).do()
    applied = [call.args[1] for call in update_properties.call_args_list]
    if command_cls is UpdateCueCommand:
        (applied,) = applied
    return applied


def test_commit_contains_only_changed_keys(engine_and_page):
    engine, page, stack = engine_and_page
    engine.bind(page, [_NestedSectionCue()])

    page.line.setText("renamed")
    engine.flush()

    assert _committed(stack) == {"section": {"name": "renamed"}}


class TestPlainDictProperties:
    """A plain dict property is replaced, not merged, by
    `update_properties`, so a commit must carry its whole value."""

    def test_commit_carries_whole_plain_dict(self, engine_and_page):
        engine, page, stack = engine_and_page
        engine.bind(page, [_PlainSectionCue()])

        page.line.setText("renamed")
        engine.flush()

        assert _committed(stack) == {
            "section": dict(_SECTION, name="renamed")
        }

    def test_applying_commit_keeps_unedited_keys(self, engine_and_page):
        engine, page, stack = engine_and_page
        cue = _PlainSectionCue()
        cue.section = dict(_SECTION, count=7, mode="beta")
        page.loadSettings({"section": cue.section})
        engine.bind(page, [cue])

        page.line.setText("renamed")
        engine.flush()
        stack.do.call_args.args[0].do()

        assert cue.section == dict(
            _SECTION, count=7, mode="beta", name="renamed"
        )

    def test_multi_cue_applies_whole_plain_dict(self, engine_and_page):
        engine, page, stack = engine_and_page
        cues = [_PlainSectionCue(), _PlainSectionCue()]
        engine.bind(page, cues)

        page.spin.setValue(3)
        engine.flush()
        stack.do.call_args.args[0].do()

        for cue in cues:
            assert cue.section == dict(_SECTION, count=3)

    def test_multi_cue_keeps_each_cues_own_unedited_keys(
        self, engine_and_page
    ):
        # The page ends up holding the last-loaded cue's values; only
        # the edited key may reach the other cues, never B's copy of
        # the keys the user didn't touch (e.g. B's MIDI trigger
        # landing on A when a keyboard key is added to both).
        engine, page, stack = engine_and_page
        a, b = _PlainSectionCue(), _PlainSectionCue()
        a.section = dict(_SECTION, count=1, mode="beta")
        b.section = dict(_SECTION, count=2, mode="gamma")
        for cue in (a, b):
            page.loadSettings({"section": cue.section})
        engine.bind(page, [a, b])

        page.line.setText("renamed")
        engine.flush()
        stack.do.call_args.args[0].do()

        assert a.section == dict(
            _SECTION, count=1, mode="beta", name="renamed"
        )
        assert b.section == dict(
            _SECTION, count=2, mode="gamma", name="renamed"
        )

    def test_keys_the_page_never_emits_survive(self, engine_and_page):
        # E.g. a controller protocol whose plugin didn't load: no page
        # shows it, so the page's output can't be the whole value.
        engine, page, stack = engine_and_page
        cue = _PlainSectionCue()
        cue.section = dict(_SECTION, unloaded=["keep", "me"])
        engine.bind(page, [cue])

        page.line.setText("renamed")
        engine.flush()
        stack.do.call_args.args[0].do()

        assert cue.section == dict(
            _SECTION, unloaded=["keep", "me"], name="renamed"
        )

    def test_mixed_targets_each_get_their_own_update(
        self, engine_and_page
    ):
        # A cue that merges gets the partial dict; a cue that replaces
        # gets its own whole value with the edit applied.
        engine, page, stack = engine_and_page
        engine.bind(page, [_NestedSectionCue(), _PlainSectionCue()])

        page.line.setText("renamed")
        engine.flush()

        assert _committed(stack, UpdateCuesCommand) == [
            {"section": {"name": "renamed"}},
            {"section": dict(_SECTION, name="renamed")},
        ]

    def test_absent_target_keeps_partial_value(self, engine_and_page):
        # `update_properties` ignores names that aren't properties, so
        # a cue lacking the key (e.g. a media element another selected
        # cue's pipeline has) must not widen the edit for anyone.
        engine, page, stack = engine_and_page
        nested, bare = _NestedSectionCue(), _BareCue()
        engine.bind(page, [nested, bare])

        page.line.setText("renamed")
        engine.flush()
        assert _committed(stack, UpdateCuesCommand) == [
            {"section": {"name": "renamed"}},
            {"section": {"name": "renamed"}},
        ]
        stack.do.call_args.args[0].do()

        assert nested.section.name == "renamed"
        assert "section" not in bare.properties()

    def test_undo_restores_the_whole_original_dict(self, engine_and_page):
        engine, page, stack = engine_and_page
        a, b = _PlainSectionCue(), _PlainSectionCue()
        a.section = dict(_SECTION, count=1, unloaded=["x"])
        b.section = dict(_SECTION, count=2)
        originals = [dict(a.section), dict(b.section)]
        page.loadSettings({"section": b.section})
        engine.bind(page, [a, b])

        page.line.setText("renamed")
        engine.flush()
        command = stack.do.call_args.args[0]
        command.do()
        command.undo()

        assert [a.section, b.section] == originals

        command.redo()
        assert a.section == dict(
            _SECTION, count=1, unloaded=["x"], name="renamed"
        )

    def test_second_edit_builds_on_the_first(self, engine_and_page):
        engine, page, stack = engine_and_page
        cue = _PlainSectionCue()
        cue.section = dict(_SECTION, unloaded=["x"])
        engine.bind(page, [cue])

        page.line.setText("renamed")
        engine.flush()
        stack.do.call_args.args[0].do()
        page.spin.setValue(9)
        engine.flush()

        assert stack.do.call_count == 2
        assert _committed(stack) == {
            "section": dict(
                _SECTION, unloaded=["x"], name="renamed", count=9
            )
        }
        stack.do.call_args.args[0].do()
        assert cue.section == dict(
            _SECTION, unloaded=["x"], name="renamed", count=9
        )


class _BareCue(HasProperties):
    name = Property(default="Cue")


class _Media(HasProperties):
    """A nested properties object holding a plain dict property,
    like a `HasProperties` sub-object with its own `controller`."""

    volume = Property(default=0)
    mapping = Property(default={})


class _MediaCue(HasProperties):
    name = Property(default="Cue")
    media = Property(default={})

    def __init__(self):
        super().__init__()
        self.media = _Media()
        self.media.mapping = {"keyboard": ["k"], "midi": ["m1"]}


# Per-row merging under multi-select (each cue keeps its own rows
# inside an edited key) is split out to the follow-up branch
# fix/inspector-multi-select-row-merge. Strict, so these fail loudly
# -- and the marker gets removed -- once that lands.
_PER_ROW_FOLLOW_UP = pytest.mark.xfail(
    strict=True,
    reason="per-row multi-select merge: fix/inspector-multi-select-row-merge",
)


class TestCueUpdate:
    """`_cue_update` / `_three_way` below the top level."""

    def test_outer_stays_partial_inner_plain_dict_goes_whole(self):
        cue = _MediaCue()
        snap = {"media": {"volume": 0, "mapping": dict(cue.media.mapping)}}
        cur = {"media": {"volume": 0, "mapping": {
            "keyboard": ["k"], "midi": ["m2"],
        }}}

        update = _cue_update(cue, snap, cur)

        assert update == {
            "media": {"mapping": {"keyboard": ["k"], "midi": ["m2"]}}
        }
        cue.update_properties(update)
        assert cue.media.mapping == {"keyboard": ["k"], "midi": ["m2"]}
        assert cue.media.volume == 0

    def test_nested_plain_dicts_merge_recursively(self):
        cue = _PlainSectionCue()
        cue.section = {"proto": {"a": 1, "b": 2, "own": 0}, "other": 3}

        update = _cue_update(
            cue,
            {"section": {"proto": {"a": 1, "b": 2}}},
            {"section": {"proto": {"a": 1, "b": 5}}},
        )

        assert update == {
            "section": {"proto": {"a": 1, "b": 5, "own": 0}, "other": 3}
        }

    def test_nested_removal_inside_plain_dict(self):
        cue = _PlainSectionCue()
        cue.section = {"proto": {"a": 1, "b": 2}}

        update = _cue_update(
            cue,
            {"section": {"proto": {"a": 1, "b": 2}}},
            {"section": {"proto": {"a": 1}}},
        )

        assert update == {"section": {"proto": {"a": 1}}}

    def test_does_not_mutate_the_cue_or_the_inputs(self):
        cue = _PlainSectionCue()
        cue.section = {"proto": {"a": 1}}
        snap = {"section": {"proto": {"a": 1}}}
        cur = {"section": {"proto": {"a": 1, "b": 2}}}

        update = _cue_update(cue, snap, cur)
        update["section"]["proto"]["a"] = 99

        assert cue.section == {"proto": {"a": 1}}
        assert snap == {"section": {"proto": {"a": 1}}}
        assert cur == {"section": {"proto": {"a": 1, "b": 2}}}

    def test_scalar_values_pass_through(self):
        cue = _PlainSectionCue()
        assert _cue_update(cue, {"name": "a"}, {"name": "x"}) == {
            "name": "x"
        }

    def test_unchanged_page_gives_empty_update(self):
        cue = _PlainSectionCue()
        snap = {"section": dict(_SECTION)}
        assert _cue_update(cue, snap, copy.deepcopy(snap)) == {}

    def test_group_dropped_by_the_page_is_left_alone(self):
        # enableCheck() drops whole top-level groups: "don't touch".
        cue = _PlainSectionCue()
        cue.section = dict(_SECTION, count=4)

        assert _cue_update(cue, {"section": dict(_SECTION)}, {}) == {}

    def test_non_dict_target_gets_the_plain_delta(self):
        # `None` (or a list) is neither merged nor replaced-by-copy:
        # the cue gets the same delta as before this change.
        cue = _PlainSectionCue()
        cue.section = None

        update = _cue_update(
            cue,
            {"section": {"a": 1, "b": 2}},
            {"section": {"a": 1, "b": 3}},
        )

        assert update == {"section": {"b": 3}}

    def test_non_property_attribute_is_never_read(self):
        # Only real properties decide the shape, as in
        # `update_properties`; a plain attribute holding a dict (or a
        # getter with side effects) must not be consulted.
        class _Probe(HasProperties):
            name = Property(default="")

            @property
            def extra(self):
                raise AssertionError("non-property attribute was read")

        update = _cue_update(
            _Probe(), {"extra": {"a": 1}}, {"extra": {"a": 2}}
        )

        assert update == {"extra": {"a": 2}}

    @pytest.mark.parametrize("old, new", [
        ({"a": 1}, 5),        # dict -> scalar
        (5, {"a": 1}),        # scalar -> dict
        (None, {"a": 1}),     # None -> dict
        ([1, 2], {"a": 1}),   # list -> dict
    ])
    def test_type_change_inside_plain_dict_takes_the_page(self, old, new):
        cue = _PlainSectionCue()
        cue.section = {"k": copy.deepcopy(old), "own": 1}

        update = _cue_update(
            cue, {"section": {"k": old}}, {"section": {"k": new}}
        )

        assert update == {"section": {"k": new, "own": 1}}

    @pytest.mark.parametrize("old, new", [
        ({"a": 1}, 5),
        (5, {"a": 1}),
        (None, {"a": 1}),
    ])
    def test_type_change_of_a_whole_property(self, old, new):
        cue = _PlainSectionCue()
        cue.section = copy.deepcopy(old)

        update = _cue_update(cue, {"section": old}, {"section": new})

        assert update == {"section": new}

    @_PER_ROW_FOLLOW_UP
    def test_removed_scalar_the_cue_holds_differently_is_kept(self):
        # Multi-select: the page showed (and removed) another cue's
        # value; this cue's own was never shown.
        cue = _PlainSectionCue()
        cue.section = {"k": "mine", "x": 1}

        update = _cue_update(
            cue, {"section": {"k": "theirs", "x": 1}}, {"section": {"x": 1}}
        )

        assert update == {"section": {"k": "mine", "x": 1}}

    def test_multi_cue_flush_and_undo_through_nested_plain_dict(
        self, qtbot
    ):
        class _MediaPage(SettingsPage):
            def __init__(self):
                super().__init__()
                self.mapping = {}

            def loadSettings(self, settings):
                self.mapping = copy.deepcopy(
                    settings.get("media", {}).get("mapping", {})
                )

            def getSettings(self):
                return {"media": {"mapping": copy.deepcopy(self.mapping)}}

        page = _MediaPage()
        qtbot.addWidget(page)
        stack = MagicMock()
        engine = InspectorCommitEngine(commands_stack=stack)
        a, b = _MediaCue(), _MediaCue()
        a.media.mapping = {"keyboard": ["ka"], "midi": ["m"]}
        b.media.mapping = {"keyboard": ["kb"], "midi": ["m"]}
        a.media.volume = 3
        for cue in (a, b):
            page.loadSettings(cue.properties())
        engine.bind(page, [a, b])

        page.mapping["midi"] = ["m", "m2"]
        engine.flush()
        command = stack.do.call_args.args[0]
        command.do()

        assert a.media.mapping == {"keyboard": ["ka"], "midi": ["m", "m2"]}
        assert b.media.mapping == {"keyboard": ["kb"], "midi": ["m", "m2"]}
        assert a.media.volume == 3

        command.undo()
        assert a.media.mapping == {"keyboard": ["ka"], "midi": ["m"]}
        assert b.media.mapping == {"keyboard": ["kb"], "midi": ["m"]}
        engine.unbind()


class _TriggerCue(Cue):
    """A real `Cue` with the plain dict properties the triggers and
    controller plugins register (`Cue.triggers`, `Cue.controller`)."""

    triggers = Property(default={})
    controller = Property(default={})


class _TriggersPage(SettingsPage):
    """Emits `TriggersSettings.getSettings()`'s shape: one key per
    trigger type that still has rows. (The real page needs the
    Application singleton, so it can't be built in a unit test.)"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.rows = []  # [(trigger, target, action)]

    def loadSettings(self, settings):
        self.rows = [
            (trigger, target, action)
            for trigger, pairs in settings.get("triggers", {}).items()
            for target, action in pairs
        ]

    def getSettings(self):
        triggers = {}
        for trigger, target, action in self.rows:
            triggers.setdefault(trigger, []).append((target, action))
        return {"triggers": triggers}


@pytest.fixture
def triggers_engine(qtbot):
    page = _TriggersPage()
    qtbot.addWidget(page)
    stack = MagicMock()
    engine = InspectorCommitEngine(commands_stack=stack)
    yield engine, page, stack
    engine.unbind()


def _apply(stack):
    stack.do.call_args.args[0].do()


class TestTriggersOnRealCues:
    """The review's repro: a page that *drops* plain-dict keys."""

    def test_changing_a_trigger_type_moves_the_trigger(
        self, triggers_engine, mock_app
    ):
        engine, page, stack = triggers_engine
        cue = _TriggerCue(mock_app)
        cue.triggers = {"Started": [("B", "Start")]}
        page.loadSettings(cue.properties())
        engine.bind(page, [cue])

        page.rows = [("Ended", "B", "Start")]
        engine.flush()
        _apply(stack)

        # The old Started trigger must not keep firing cue B.
        assert cue.triggers == {"Ended": [("B", "Start")]}

    def test_removing_the_last_trigger_of_a_type(
        self, triggers_engine, mock_app
    ):
        engine, page, stack = triggers_engine
        cue = _TriggerCue(mock_app)
        cue.triggers = {
            "Started": [("B", "Start")],
            "Ended": [("C", "Start")],
        }
        page.loadSettings(cue.properties())
        engine.bind(page, [cue])

        page.rows = [("Ended", "C", "Start")]
        engine.flush()
        _apply(stack)

        assert cue.triggers == {"Ended": [("C", "Start")]}

    def test_removing_the_only_trigger_still_commits(
        self, triggers_engine, mock_app
    ):
        # A removal-only edit has an empty `_dict_diff`; it must still
        # reach the cue.
        engine, page, stack = triggers_engine
        cue = _TriggerCue(mock_app)
        cue.triggers = {"Started": [("B", "Start")]}
        page.loadSettings(cue.properties())
        engine.bind(page, [cue])

        page.rows = []
        engine.flush()
        _apply(stack)

        assert cue.triggers == {}

    def test_multi_cue_type_change_keeps_each_cues_other_triggers(
        self, triggers_engine, mock_app
    ):
        engine, page, stack = triggers_engine
        a, b = _TriggerCue(mock_app), _TriggerCue(mock_app)
        a.triggers = {
            "Started": [("X", "Start")],
            "Paused": [("A-own", "Stop")],
        }
        b.triggers = {
            "Started": [("X", "Start")],
            "Paused": [("B-own", "Stop")],
        }
        for cue in (a, b):
            page.loadSettings(cue.properties())
        engine.bind(page, [a, b])

        page.rows = [("Ended", "X", "Start"), ("Paused", "B-own", "Stop")]
        engine.flush()
        _apply(stack)

        assert a.triggers == {
            "Ended": [("X", "Start")],
            "Paused": [("A-own", "Stop")],
        }
        assert b.triggers == {
            "Ended": [("X", "Start")],
            "Paused": [("B-own", "Stop")],
        }

    def test_multi_cue_removal_removes_from_every_cue(
        self, triggers_engine, mock_app
    ):
        engine, page, stack = triggers_engine
        a, b = _TriggerCue(mock_app), _TriggerCue(mock_app)
        a.triggers = {"Started": [("X", "Start")], "Ended": [("A", "Stop")]}
        b.triggers = {"Started": [("X", "Start")], "Ended": [("B", "Stop")]}
        for cue in (a, b):
            page.loadSettings(cue.properties())
        engine.bind(page, [a, b])

        page.rows = [("Ended", "B", "Stop")]
        engine.flush()
        _apply(stack)

        assert a.triggers == {"Ended": [("A", "Stop")]}
        assert b.triggers == {"Ended": [("B", "Stop")]}

    def test_undo_restores_the_removed_trigger(
        self, triggers_engine, mock_app
    ):
        engine, page, stack = triggers_engine
        cue = _TriggerCue(mock_app)
        cue.triggers = {"Started": [("B", "Start")]}
        page.loadSettings(cue.properties())
        engine.bind(page, [cue])

        page.rows = [("Ended", "B", "Start")]
        engine.flush()
        command = stack.do.call_args.args[0]
        command.do()
        command.undo()

        assert cue.triggers == {"Started": [("B", "Start")]}

    def test_controller_edit_keeps_other_protocols(
        self, engine_and_page, mock_app
    ):
        # The original bug, on a real `Cue.controller`.
        cue = _TriggerCue(mock_app)
        cue.controller = {"keyboard": [("k", "Start")], "midi": [("m1",)]}
        snap = {"controller": dict(cue.controller)}
        cur = {"controller": {
            "keyboard": [("k", "Start")], "midi": [("m2",)],
        }}

        cue.update_properties(_cue_update(cue, snap, cur))

        assert cue.controller == {
            "keyboard": [("k", "Start")], "midi": [("m2",)],
        }

    @_PER_ROW_FOLLOW_UP
    def test_multi_cue_added_row_keeps_each_cues_own_rows(
        self, triggers_engine, mock_app
    ):
        # Review 3: a changed list was copied whole from the
        # last-loaded cue, so A lost its row and gained B's.
        engine, page, stack = triggers_engine
        a, b = _TriggerCue(mock_app), _TriggerCue(mock_app)
        a.triggers = {"Started": [("a", "Start")]}
        b.triggers = {"Started": [("b", "Start")]}
        for cue in (a, b):
            page.loadSettings(cue.properties())
        engine.bind(page, [a, b])

        page.rows.append(("Started", "new", "Start"))
        engine.flush()
        _apply(stack)

        assert a.triggers == {"Started": [("a", "Start"), ("new", "Start")]}
        assert b.triggers == {"Started": [("b", "Start"), ("new", "Start")]}

    @_PER_ROW_FOLLOW_UP
    def test_multi_cue_removing_a_type_keeps_rows_the_page_never_showed(
        self, triggers_engine, mock_app
    ):
        # Deleting B's last Paused row must not pop A's own Paused.
        engine, page, stack = triggers_engine
        a, b = _TriggerCue(mock_app), _TriggerCue(mock_app)
        a.triggers = {"Paused": [("a", "Stop")], "Ended": [("x", "Start")]}
        b.triggers = {"Paused": [("b", "Stop")], "Ended": [("x", "Start")]}
        for cue in (a, b):
            page.loadSettings(cue.properties())
        engine.bind(page, [a, b])

        page.rows = [("Ended", "x", "Start")]
        engine.flush()
        _apply(stack)

        assert a.triggers == {
            "Paused": [("a", "Stop")], "Ended": [("x", "Start")],
        }
        assert b.triggers == {"Ended": [("x", "Start")]}

    @_PER_ROW_FOLLOW_UP
    def test_multi_cue_type_change_moves_only_the_shown_row(
        self, triggers_engine, mock_app
    ):
        engine, page, stack = triggers_engine
        a, b = _TriggerCue(mock_app), _TriggerCue(mock_app)
        a.triggers = {"Started": [("a", "Start"), ("x", "Start")]}
        b.triggers = {"Started": [("x", "Start")]}
        for cue in (a, b):
            page.loadSettings(cue.properties())
        engine.bind(page, [a, b])

        page.rows = [("Ended", "x", "Start")]
        engine.flush()
        _apply(stack)

        assert a.triggers == {
            "Started": [("a", "Start")], "Ended": [("x", "Start")],
        }
        assert b.triggers == {"Ended": [("x", "Start")]}

    def test_single_cue_takes_the_page_exactly_including_order(
        self, triggers_engine, mock_app
    ):
        engine, page, stack = triggers_engine
        cue = _TriggerCue(mock_app)
        cue.triggers = {"Started": [("b", "Start"), ("c", "Stop")]}
        page.loadSettings(cue.properties())
        engine.bind(page, [cue])

        page.rows = [("Started", "c", "Stop"), ("Started", "b", "Start")]
        engine.flush()
        _apply(stack)

        assert cue.triggers == {"Started": [("c", "Stop"), ("b", "Start")]}

    def test_per_cue_lists_of_tuples_survive_undo_and_redo(
        self, triggers_engine, mock_app
    ):
        # The real trigger shape through str/literal_eval.
        engine, page, stack = triggers_engine
        a, b = _TriggerCue(mock_app), _TriggerCue(mock_app)
        a.triggers = {"Started": [("a", "Start")]}
        b.triggers = {"Started": [("b", "Start")]}
        for cue in (a, b):
            page.loadSettings(cue.properties())
        engine.bind(page, [a, b])

        page.rows.append(("Ended", "e", "Stop"))
        engine.flush()
        command = stack.do.call_args.args[0]
        command.do()
        after = (copy.deepcopy(a.triggers), copy.deepcopy(b.triggers))
        command.undo()
        assert a.triggers == {"Started": [("a", "Start")]}
        assert b.triggers == {"Started": [("b", "Start")]}

        command.redo()
        assert (a.triggers, b.triggers) == after
        assert a.triggers == {
            "Started": [("a", "Start")], "Ended": [("e", "Stop")],
        }


def _loaded(value):
    """*value* as a saved show holds it: sessions are read with
    `json.load`, so rows come back as lists, while pages emit tuples."""
    return json.loads(json.dumps(value))


class TestSavedShowRows:
    """Review 4: cue rows are lists after a session load; page rows
    are tuples. Edits must not depend on the two comparing equal."""

    def _bind(self, triggers_engine, mock_app, triggers):
        engine, page, stack = triggers_engine
        cue = _TriggerCue(mock_app)
        cue.triggers = _loaded(triggers)
        page.loadSettings(cue.properties())
        engine.bind(page, [cue])
        return engine, page, stack, cue

    def test_deleting_a_trigger(self, triggers_engine, mock_app):
        engine, page, stack, cue = self._bind(
            triggers_engine, mock_app,
            {"Started": [("a", "Start"), ("x", "Stop")]},
        )

        page.rows = [("Started", "a", "Start")]
        engine.flush()
        _apply(stack)

        assert _loaded(cue.triggers) == {"Started": [["a", "Start"]]}

    def test_retyping_a_trigger(self, triggers_engine, mock_app):
        engine, page, stack, cue = self._bind(
            triggers_engine, mock_app, {"Started": [("B", "Start")]}
        )

        page.rows = [("Ended", "B", "Start")]
        engine.flush()
        _apply(stack)

        assert _loaded(cue.triggers) == {"Ended": [["B", "Start"]]}

    def test_deleting_the_last_trigger(self, triggers_engine, mock_app):
        engine, page, stack, cue = self._bind(
            triggers_engine, mock_app, {"Started": [("B", "Start")]}
        )

        page.rows = []
        engine.flush()
        _apply(stack)

        assert cue.triggers == {}

    def test_adding_a_trigger_does_not_duplicate(
        self, triggers_engine, mock_app
    ):
        engine, page, stack, cue = self._bind(
            triggers_engine, mock_app, {"Started": [("a", "Start")]}
        )

        page.rows.append(("Started", "n", "Stop"))
        engine.flush()
        _apply(stack)

        assert _loaded(cue.triggers) == {
            "Started": [["a", "Start"], ["n", "Stop"]]
        }

    def test_deleting_a_midi_mapping_keeps_other_protocols(self, mock_app):
        cue = _TriggerCue(mock_app)
        cue.controller = _loaded({
            "keyboard": [("k", "Start")],
            "midi": [("note_on channel=0 note=60", "Start")],
        })
        # The page's view of the cue: tuples, as getSettings emits.
        snap = {"controller": {
            "keyboard": [("k", "Start")],
            "midi": [("note_on channel=0 note=60", "Start")],
        }}
        cur = {"controller": {"keyboard": [("k", "Start")], "midi": []}}

        cue.update_properties(_cue_update(cue, snap, cur))

        assert _loaded(cue.controller) == {
            "keyboard": [["k", "Start"]], "midi": [],
        }


class TestRealTriggersPage:
    """`TriggersSettings` itself, with `Application` patched to a
    mock holding a real `CueModel` (never the singleton)."""

    @pytest.fixture
    def setup(self, qtbot, mock_app, monkeypatch):
        from lisp.cues.cue_model import CueModel
        from lisp.plugins.triggers import triggers_settings

        model = CueModel()
        targets = {}
        for name in ("T1", "T2", "T3"):
            target = Cue(mock_app)
            target.name = name
            model.add(target)
            targets[name] = target.id
        app = MagicMock()
        app.cue_model = model
        monkeypatch.setattr(triggers_settings, "Application", lambda: app)

        page = triggers_settings.TriggersSettings()
        qtbot.addWidget(page)
        stack = MagicMock()
        engine = InspectorCommitEngine(commands_stack=stack)
        yield engine, page, stack, targets
        engine.unbind()

    @staticmethod
    def _add_row(page, trigger, target_id, action):
        page.triggersModel.appendRow(Cue, trigger, target_id, action)

    def test_single_cue_type_change_moves_the_trigger(
        self, setup, mock_app
    ):
        engine, page, stack, t = setup
        cue = _TriggerCue(mock_app)
        cue.triggers = {"Started": [(t["T1"], "Start")]}
        page.loadSettings(cue.properties())
        engine.bind(page, [cue])

        page.triggersModel.rows[0][0] = "Ended"
        engine.flush()
        _apply(stack)

        assert cue.triggers == {"Ended": [(t["T1"], "Start")]}

    def test_multi_select_unticked_group_commits_nothing(
        self, setup, mock_app
    ):
        engine, page, stack, t = setup
        a, b = _TriggerCue(mock_app), _TriggerCue(mock_app)
        a.triggers = {"Started": [(t["T1"], "Start")]}
        b.triggers = {"Started": [(t["T2"], "Start")]}
        page.enableCheck(True)
        for cue in (a, b):
            page.loadSettings(cue.properties())
        engine.bind(page, [a, b])

        engine.flush()

        stack.do.assert_not_called()

    def test_multi_select_ticking_the_group_applies_it_as_shown(
        self, setup, mock_app
    ):
        # Review 3, High: documented, legacy-dialog semantics. With
        # enableCheck(True) the bind-time snapshot has no `triggers`;
        # ticking the group means "apply this group, as shown, to
        # every selected cue", so A gets B's (last-loaded) rows.
        engine, page, stack, t = setup
        a, b = _TriggerCue(mock_app), _TriggerCue(mock_app)
        a.triggers = {"Started": [(t["T1"], "Start")]}
        b.triggers = {"Started": [(t["T2"], "Start")]}
        page.enableCheck(True)
        for cue in (a, b):
            page.loadSettings(cue.properties())
        engine.bind(page, [a, b])

        page.triggerGroup.setChecked(True)
        self._add_row(page, "Ended", t["T3"], CueAction.Stop)
        engine.flush()
        _apply(stack)

        shown = {
            "Started": [(t["T2"], "Start")],
            "Ended": [(t["T3"], "Stop")],
        }
        assert a.triggers == shown
        assert b.triggers == shown


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
