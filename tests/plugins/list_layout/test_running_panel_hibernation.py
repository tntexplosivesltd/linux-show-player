"""Running-panel widget responds to set_hibernated() by hiding
controls, shrinking its size, and applying a muted stylesheet."""
from unittest.mock import MagicMock


class _FakeSubWidget:
    def __init__(self):
        self._visible = True

    def setVisible(self, visible):
        self._visible = visible

    def isVisible(self):
        return self._visible


class TestSetHibernatedBase:
    """The base-class set_hibernated logic on RunningCueWidget.

    We can't instantiate the real widget without a full QApplication
    pipeline including CueTime etc., so we bypass __init__ via
    __new__ and inject the minimum fields the method needs.
    """

    def _make_widget(self, with_media_attrs=False):
        from lisp.plugins.list_layout.playing_widgets import (
            RunningCueWidget,
        )
        w = RunningCueWidget.__new__(RunningCueWidget)
        w._hibernated = False
        w.controlButtons = _FakeSubWidget()
        w.timeDisplay = _FakeSubWidget()
        w.nameLabel = MagicMock()
        w.nameLabel.fontMetrics.return_value.height.return_value = 18
        w.gridLayout = MagicMock()
        w.gridLayoutWidget = MagicMock()
        w._apply_hibernated_opacity = MagicMock()
        w.setStyleSheet = MagicMock()
        w.updateGeometry = MagicMock()
        w.size_override = None
        # Explicit None — avoid tripping QWidget's __getattr__ when
        # the real __init__ was bypassed via __new__.
        w.dbmeter = None
        w.seekSlider = None
        w.volumeIndicator = None

        def fake_size():
            return MagicMock(
                width=lambda: 400,
                height=lambda: 100,
            )
        w.size = fake_size

        def fake_resize(width, height):
            w.size_override = (width, height)
        w.resize = fake_resize

        if with_media_attrs:
            w.dbmeter = _FakeSubWidget()
            w.seekSlider = _FakeSubWidget()
            w.volumeIndicator = _FakeSubWidget()

        return w

    def test_set_true_marks_hibernated(self):
        w = self._make_widget()
        w.set_hibernated(True)
        assert w._hibernated is True

    def test_set_false_restores(self):
        w = self._make_widget()
        w.set_hibernated(True)
        w.set_hibernated(False)
        assert w._hibernated is False

    def test_idempotent_no_double_work(self):
        w = self._make_widget()
        w.set_hibernated(True)
        calls1 = w._apply_hibernated_opacity.call_count
        w.set_hibernated(True)
        assert w._apply_hibernated_opacity.call_count == calls1

    def test_hides_controls_when_hibernated(self):
        w = self._make_widget()
        w.set_hibernated(True)
        assert w.controlButtons.isVisible() is False

    def test_hides_timedisplay_when_hibernated(self):
        w = self._make_widget()
        w.set_hibernated(True)
        assert w.timeDisplay.isVisible() is False

    def test_inverts_row_stretch_so_name_dominates(self):
        w = self._make_widget()
        w.set_hibernated(True)
        # Name row (0) gets the stretch; content row (1) gets 0.
        stretch_calls = w.gridLayout.setRowStretch.call_args_list
        assert (0, 1) in [c.args for c in stretch_calls]
        assert (1, 0) in [c.args for c in stretch_calls]

    def test_restores_timedisplay_and_stretch_on_wake(self):
        w = self._make_widget()
        w.set_hibernated(True)
        w.set_hibernated(False)
        assert w.timeDisplay.isVisible() is True
        # Normal stretch restored: row 0 = 1, row 1 = 3.
        stretch_calls = w.gridLayout.setRowStretch.call_args_list
        assert (1, 3) in [c.args for c in stretch_calls]

    def test_shrinks_height_when_hibernated(self):
        w = self._make_widget()
        w.set_hibernated(True)
        assert w.size_override is not None
        _new_width, new_height = w.size_override
        assert new_height < 100  # base was 100

    def test_restores_controls_on_wake(self):
        w = self._make_widget()
        w.set_hibernated(True)
        w.set_hibernated(False)
        assert w.controlButtons.isVisible() is True

    def test_media_hides_dbmeter_and_seek(self):
        w = self._make_widget(with_media_attrs=True)
        # Set them both visible first (operator had them on).
        w.dbmeter.setVisible(True)
        w.seekSlider.setVisible(True)
        w.set_hibernated(True)
        assert w.dbmeter.isVisible() is False
        assert w.seekSlider.isVisible() is False

    def test_media_restores_dbmeter_and_seek_on_wake(self):
        w = self._make_widget(with_media_attrs=True)
        w.dbmeter.setVisible(True)
        w.seekSlider.setVisible(True)
        w.set_hibernated(True)
        w.set_hibernated(False)
        assert w.dbmeter.isVisible() is True
        assert w.seekSlider.isVisible() is True
