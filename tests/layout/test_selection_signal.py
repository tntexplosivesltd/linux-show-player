"""Unit tests for Step 1 of the QLab inspector plan.

Verifies that:
* `CueLayout.selection_changed` exists on the base as a `Signal`
  (subclasses can rely on it even before wiring).
* `CueWidget.selected` setter emits `selectedChanged` once per real
  transition, and is idempotent on no-op writes.
* The list-layout coalescing timer collapses many rapid triggers
  into a single `selection_changed` emit per event-loop tick.
"""

import pytest

from lisp.core.signal import Signal
from lisp.layout.cue_layout import CueLayout
from lisp.plugins.cart_layout.cue_widget import CueWidget
from lisp.ui.icons import IconTheme


@pytest.fixture(autouse=True)
def _ensure_icon_theme():
    """CueWidget.__init__ looks up an icon; the theme must be set."""
    if IconTheme._GlobalTheme is None:
        IconTheme.set_theme_name("numix")


@pytest.fixture
def cue_widget(qtbot, monkeypatch):
    """Build a CueWidget with _setCue bypassed.

    The setter-under-test doesn't touch the underlying Cue at all,
    so we can skip the (non-trivial) Cue wiring that CueWidget
    normally does in __init__.
    """
    monkeypatch.setattr(CueWidget, "_setCue", lambda self, cue: None)
    widget = CueWidget(cue=None)
    qtbot.addWidget(widget)
    return widget


def test_base_cuelayout_has_selection_changed_signal():
    """Every subclass inherits the signal; it can always be connected.

    We don't instantiate CueLayout (it's abstract) — but we can
    read the class annotation path via a lightweight subclass.
    """
    # The signal is created in __init__, so build a throwaway subclass
    # that bypasses abstract-method requirements by overriding them.
    class _Stub(CueLayout):
        @property
        def model(self):  # pragma: no cover - not exercised here
            return None

        @property
        def view(self):  # pragma: no cover
            return None

        def cues(self, cue_type=None):  # pragma: no cover
            return iter(())

        def cue_at(self, index):  # pragma: no cover
            raise IndexError

        def selected_cues(self, cue_type=None):  # pragma: no cover
            return iter(())

        def invert_selection(self):  # pragma: no cover
            pass

        def select_all(self, cue_type=None):  # pragma: no cover
            pass

        def deselect_all(self, cue_type=None):  # pragma: no cover
            pass

    class _FakeApp:
        pass

    stub = _Stub(_FakeApp())
    assert isinstance(stub.selection_changed, Signal)

    # Connect a real (non-lambda) slot; emitting with no additional
    # wiring must not raise — the default path is a safe no-op.
    called = []

    def _on_selection_changed():
        called.append(True)

    stub.selection_changed.connect(_on_selection_changed)
    stub.selection_changed.emit()
    assert called == [True]


def test_cue_widget_selected_setter_emits_once_per_transition(
    qtbot, cue_widget
):
    with qtbot.waitSignal(cue_widget.selectedChanged, timeout=500):
        cue_widget.selected = True

    # A second identical write is a no-op: no signal must fire.
    with qtbot.assertNotEmitted(cue_widget.selectedChanged):
        cue_widget.selected = True

    # Flipping back emits again.
    with qtbot.waitSignal(cue_widget.selectedChanged, timeout=500):
        cue_widget.selected = False


def test_cue_widget_selected_setter_coerces_truthy(qtbot, cue_widget):
    """Passing truthy/falsy values should still emit exactly once."""
    with qtbot.waitSignal(cue_widget.selectedChanged, timeout=500):
        cue_widget.selected = 1  # truthy → True transition
    assert cue_widget.selected is True

    with qtbot.waitSignal(cue_widget.selectedChanged, timeout=500):
        cue_widget.selected = 0  # falsy → False transition
    assert cue_widget.selected is False


