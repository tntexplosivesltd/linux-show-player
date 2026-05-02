"""Unit tests for `lisp.ui.inspector.panel.InspectorPanel`."""

from unittest.mock import MagicMock

import pytest

from PyQt5.QtCore import QT_TRANSLATE_NOOP, Qt
from PyQt5.QtWidgets import QCheckBox, QLineEdit, QSpinBox, QVBoxLayout

from lisp.core.properties import Property
from lisp.cues.cue import Cue
from lisp.ui.inspector.mixed_values import MIXED_PLACEHOLDER
from lisp.ui.inspector.panel import InspectorPanel
from lisp.ui.settings.cue_settings import CueSettingsRegistry
from lisp.ui.settings.pages import CueSettingsPage


# ---------------------------------------------------------------------------
# Test fixtures: a minimal Cue subclass tree and a settings page that
# round-trips its properties through known widget types so divergence
# detection can be asserted directly on the QWidget state.
# ---------------------------------------------------------------------------


class _PanelCue(Cue):
    """Two writable properties chosen to exercise both a string field
    (drives QLineEdit / divergence as text) and an int field (drives
    QSpinBox / divergence as number)."""

    label = Property(default="")
    count = Property(default=0)
    enabled = Property(default=False)


class _PanelCueAlt(_PanelCue):
    """Subclass so multi-cue selections collapse to `_PanelCue` as
    the greatest common superclass — exercising the GCS path rather
    than the same-class shortcut."""


class _PanelPage(CueSettingsPage):
    Name = QT_TRANSLATE_NOOP("SettingsPageName", "PanelTest")
    SortOrder = 50

    def __init__(self, cueType, **kwargs):
        super().__init__(cueType=cueType, **kwargs)
        layout = QVBoxLayout(self)

        self.line = QLineEdit()
        self.line.setObjectName("label")
        self.spin = QSpinBox()
        self.spin.setRange(0, 100)
        self.spin.setObjectName("count")
        self.check = QCheckBox()
        self.check.setObjectName("enabled")
        for w in (self.line, self.spin, self.check):
            layout.addWidget(w)

        self._enable_check_called_with = None

    def loadSettings(self, settings):
        if "label" in settings:
            self.line.setText(settings["label"])
        if "count" in settings:
            self.spin.setValue(settings["count"])
        if "enabled" in settings:
            self.check.setChecked(settings["enabled"])

    def getSettings(self):
        return {
            "label": self.line.text(),
            "count": self.spin.value(),
            "enabled": self.check.isChecked(),
        }

    def enableCheck(self, enabled):
        self._enable_check_called_with = enabled


class _SecondPage(CueSettingsPage):
    """Second tab so ordering by `cue_page_sort_key` is observable."""

    Name = QT_TRANSLATE_NOOP("SettingsPageName", "AlphaTab")
    SortOrder = 10

    def __init__(self, cueType, **kwargs):
        super().__init__(cueType=cueType, **kwargs)
        QVBoxLayout(self)

    def loadSettings(self, settings):
        pass

    def getSettings(self):
        return {}


@pytest.fixture
def registered_pages():
    """Register the test pages against `_PanelCue` and tear down after."""
    registry = CueSettingsRegistry()
    registry.add(_PanelPage, _PanelCue)
    registry.add(_SecondPage, _PanelCue)
    yield
    registry.remove(_PanelPage)
    registry.remove(_SecondPage)


@pytest.fixture
def make_cue(mock_app):
    def _factory(cls=_PanelCue, **props):
        cue = cls(app=mock_app)
        for key, value in props.items():
            setattr(cue, key, value)
        return cue

    return _factory


@pytest.fixture
def panel(qtbot, registered_pages):
    p = InspectorPanel()
    qtbot.addWidget(p)
    yield p
    p.detach()


# ---------------------------------------------------------------------------
# Empty / placeholder
# ---------------------------------------------------------------------------


class TestEmptyState:
    def test_initial_state_is_empty_placeholder(self, panel):
        assert panel._stack.currentIndex() == InspectorPanel._EMPTY_INDEX

    def test_bind_empty_keeps_placeholder(self, panel):
        panel.bind([])
        assert panel._stack.currentIndex() == InspectorPanel._EMPTY_INDEX
        assert panel.active_cue_ids() == []

    def test_bind_then_empty_returns_to_placeholder(self, panel, make_cue):
        panel.bind([make_cue(label="A")])
        assert panel._stack.currentIndex() == InspectorPanel._CONTENT_INDEX
        panel.bind([])
        assert panel._stack.currentIndex() == InspectorPanel._EMPTY_INDEX


# ---------------------------------------------------------------------------
# Single-cue bind
# ---------------------------------------------------------------------------


class TestSingleCueBind:
    def test_loads_properties_into_widgets(self, panel, make_cue):
        cue = make_cue(label="hello", count=42, enabled=True)
        panel.bind([cue])

        # Find the populated _PanelPage (may be on a different tab
        # depending on sort order).
        panel_page = next(
            panel._tabs.widget(i)
            for i in range(panel._tabs.count())
            if isinstance(panel._tabs.widget(i), _PanelPage)
        )
        assert panel_page.line.text() == "hello"
        assert panel_page.spin.value() == 42
        assert panel_page.check.isChecked() is True

    def test_enable_check_false_for_single_cue(self, panel, make_cue):
        panel.bind([make_cue(label="x")])
        panel_page = next(
            w for w in (panel._tabs.widget(i)
                        for i in range(panel._tabs.count()))
            if isinstance(w, _PanelPage)
        )
        assert panel_page._enable_check_called_with is False

    def test_active_cue_ids_reflects_binding(self, panel, make_cue):
        cue = make_cue(label="x")
        panel.bind([cue])
        assert panel.active_cue_ids() == [cue.id]

    def test_engine_is_bound_to_active_tab(self, panel, make_cue):
        panel.bind([make_cue()])
        assert panel._engine._page is panel._tabs.currentWidget()
        assert panel._engine._cues == panel._cues


# ---------------------------------------------------------------------------
# Tab ordering — pages render in `cue_page_sort_key` order
# ---------------------------------------------------------------------------


class TestTabOrdering:
    def test_tabs_sort_by_sort_order_then_name(self, panel, make_cue):
        panel.bind([make_cue()])
        # _SecondPage.SortOrder=10 vs _PanelPage.SortOrder=50, so
        # AlphaTab should come first.
        assert panel.page_names() == ["AlphaTab", "PanelTest"]


# ---------------------------------------------------------------------------
# Multi-cue bind + mixed-value indicators
# ---------------------------------------------------------------------------


class TestMultiCueBind:
    def test_no_divergence_loads_common_value(self, panel, make_cue):
        cues = [make_cue(label="same", count=7), make_cue(label="same", count=7)]
        panel.bind(cues)

        page = next(
            w for w in (panel._tabs.widget(i)
                        for i in range(panel._tabs.count()))
            if isinstance(w, _PanelPage)
        )
        # No mixed indicator anywhere — everything agrees.
        assert page.line.text() == "same"
        assert page.line.placeholderText() == ""
        assert page.spin.value() == 7
        assert page.spin.specialValueText() == ""

    def test_divergent_text_field_shows_placeholder(
        self, panel, make_cue
    ):
        cues = [
            make_cue(label="alpha", count=5),
            make_cue(label="beta", count=5),
        ]
        panel.bind(cues)

        page = next(
            w for w in (panel._tabs.widget(i)
                        for i in range(panel._tabs.count()))
            if isinstance(w, _PanelPage)
        )
        # `label` diverged → mixed placeholder.
        assert page.line.text() == ""
        assert page.line.placeholderText() == MIXED_PLACEHOLDER
        # `count` agreed → loaded normally.
        assert page.spin.value() == 5
        assert page.spin.specialValueText() == ""

    def test_divergent_int_field_shows_special_value_text(
        self, panel, make_cue
    ):
        cues = [make_cue(count=1), make_cue(count=2), make_cue(count=3)]
        panel.bind(cues)

        page = next(
            w for w in (panel._tabs.widget(i)
                        for i in range(panel._tabs.count()))
            if isinstance(w, _PanelPage)
        )
        assert page.spin.specialValueText() == MIXED_PLACEHOLDER
        assert page.spin.value() == page.spin.minimum()

    def test_divergent_checkbox_becomes_tristate(
        self, panel, make_cue
    ):
        cues = [make_cue(enabled=True), make_cue(enabled=False)]
        panel.bind(cues)

        page = next(
            w for w in (panel._tabs.widget(i)
                        for i in range(panel._tabs.count()))
            if isinstance(w, _PanelPage)
        )
        assert page.check.isTristate() is True
        assert page.check.checkState() == Qt.PartiallyChecked

    def test_enable_check_true_for_multi_cue(self, panel, make_cue):
        panel.bind([make_cue(), make_cue()])
        page = next(
            w for w in (panel._tabs.widget(i)
                        for i in range(panel._tabs.count()))
            if isinstance(w, _PanelPage)
        )
        assert page._enable_check_called_with is True

    def test_multi_cue_uses_gcs_for_pages(
        self, panel, make_cue
    ):
        # Mix base + subclass; GCS is _PanelCue, so the registered
        # page is still picked.
        cues = [make_cue(_PanelCue, label="x"), make_cue(_PanelCueAlt, label="y")]
        panel.bind(cues)
        # Both pages should still be present (registered against
        # _PanelCue, and _PanelCueAlt subclasses _PanelCue).
        assert "PanelTest" in panel.page_names()


# ---------------------------------------------------------------------------
# Rebind on selection change
# ---------------------------------------------------------------------------


class TestRebind:
    def test_attach_seeds_from_layout(self, panel, make_cue):
        layout = MagicMock()
        cue = make_cue(label="seeded")
        layout.selected_cues.return_value = iter([cue])
        # MagicMock's `selection_changed` is a MagicMock too —
        # InspectorPanel only needs `.connect()` on it, which
        # MagicMock supports natively.
        panel.attach(layout)

        assert panel.active_cue_ids() == [cue.id]

    def test_selection_changed_callback_rebinds(self, panel, make_cue):
        layout = MagicMock()
        cue_a = make_cue(label="A")
        cue_b = make_cue(label="B")
        layout.selected_cues.return_value = iter([cue_a])
        panel.attach(layout)

        # Now change selection and re-fire the handler manually.
        layout.selected_cues.return_value = iter([cue_b])
        panel._on_selection_changed()

        assert panel.active_cue_ids() == [cue_b.id]
        page = next(
            w for w in (panel._tabs.widget(i)
                        for i in range(panel._tabs.count()))
            if isinstance(w, _PanelPage)
        )
        assert page.line.text() == "B"

    def test_shape_match_short_circuits_tab_rebuild(
        self, panel, make_cue
    ):
        panel.bind([make_cue(label="A"), make_cue(label="A")])
        first_tab_widget = panel._tabs.widget(0)

        # Same GCS, same count → no rebuild expected.
        panel.bind([make_cue(label="C"), make_cue(label="C")])
        assert panel._tabs.widget(0) is first_tab_widget


# ---------------------------------------------------------------------------
# External property_changed refresh
# ---------------------------------------------------------------------------


class TestExternalRefresh:
    def test_property_changed_triggers_reload(
        self, qtbot, panel, make_cue
    ):
        cue = make_cue(label="initial")
        panel.bind([cue])

        page = next(
            w for w in (panel._tabs.widget(i)
                        for i in range(panel._tabs.count()))
            if isinstance(w, _PanelPage)
        )
        assert page.line.text() == "initial"

        # External edit (simulating undo or RPC).
        cue.label = "external"
        # Wait for the coalescing timer to fire.
        qtbot.wait(50)

        assert page.line.text() == "external"

    def test_external_refresh_does_not_dispatch_command(
        self, qtbot, panel, make_cue
    ):
        cue = make_cue(label="initial")
        panel.bind([cue])

        # Replace the engine's dispatch path so we can detect any
        # spurious flush during the external refresh.
        panel._engine._commands_stack = MagicMock()

        cue.label = "external"
        qtbot.wait(50)

        panel._engine._commands_stack.do.assert_not_called()


# ---------------------------------------------------------------------------
# CueColorPalette value adapters
# ---------------------------------------------------------------------------


class TestColorPaletteAdapters:
    """The panel's private value-read/write helpers need a branch for
    ``CueColorPalette`` so that (a) divergence detection on a multi-cue
    selection sees differing backgrounds and (b) the E2E harness can
    drive the palette through ``set_field_value``. Without these
    branches the palette is opaque — `_widget_value` returns None,
    collapsing divergence detection to a silent no-op."""

    def test_widget_value_reads_palette_color(self, qtbot):
        from lisp.ui.inspector.panel import _widget_value
        from lisp.ui.widgets.cue_color_palette import CueColorPalette

        w = CueColorPalette()
        qtbot.addWidget(w)
        w.setColor("Blue")

        assert _widget_value(w) == "Blue"

    def test_widget_value_reads_empty_for_none_slot(self, qtbot):
        from lisp.ui.inspector.panel import _widget_value
        from lisp.ui.widgets.cue_color_palette import CueColorPalette

        w = CueColorPalette()
        qtbot.addWidget(w)

        assert _widget_value(w) == ""

    def test_write_widget_value_sets_palette_color(self, qtbot, panel):
        from lisp.ui.widgets.cue_color_palette import CueColorPalette

        w = CueColorPalette()
        qtbot.addWidget(w)

        assert panel._write_widget_value(w, "Red") is True
        assert w.color() == "Red"

    def test_write_widget_value_unknown_name_clears(self, qtbot, panel):
        # setColor coerces unknown values (including raw hex) to "".
        # Task 15 will migrate callers to pass canonical names instead.
        from lisp.ui.widgets.cue_color_palette import CueColorPalette

        w = CueColorPalette()
        qtbot.addWidget(w)
        w.setColor("Red")  # start with something selected

        panel._write_widget_value(w, "NotAColor")
        assert w.color() == ""
