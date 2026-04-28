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

"""Unit tests for the pre-arm indicator dot in CueListView."""

import pytest
from unittest.mock import MagicMock, patch

from PyQt5 import QtGui
from PyQt5.QtCore import QEvent, QPoint
from PyQt5.QtGui import QHelpEvent

from lisp.core.signal import Signal
from lisp.cues.cue import Cue
from lisp.cues.cue_model import CueModel
from lisp.plugins.list_layout.list_view import CueListView
from lisp.plugins.list_layout.models import CueListModel
from lisp.ui.icons import IconTheme


@pytest.fixture(autouse=True)
def _icon_theme():
    """List-column widgets pull icons via IconTheme at construction."""
    if IconTheme._GlobalTheme is None:
        IconTheme.set_theme_name("lisp")
    yield


def _make_fake_manager(armed=None, failed=None):
    """Build a fake PreArmManager with controllable state."""
    mgr = MagicMock()
    mgr._armed = armed if armed is not None else {}
    mgr._failed = failed if failed is not None else {}
    mgr.armed_set_changed = Signal()
    return mgr


def _build_view(mock_app, mgr=None):
    """Build a CueListView with an optional fake pre_arm_manager."""
    cue_model = CueModel()
    list_model = CueListModel(cue_model)
    mock_app.cue_model = cue_model

    fake_app = MagicMock()
    fake_app.pre_arm_manager = mgr  # None is also valid

    with patch(
        "lisp.plugins.list_layout.list_view.Application",
        return_value=fake_app,
    ):
        view = CueListView(list_model)

    view._fake_app = fake_app  # keep alive for later patching
    view._cue_model = cue_model
    return view


def _add_cue(view, mock_app, cue_id="test-cue", preload=False):
    """Add a Cue to the view's model and return it."""
    cue = Cue(id=cue_id, app=mock_app)
    if preload:
        cue.preload = True
    view._cue_model.add(cue)
    return cue


class TestIndicatorConstants:
    """Smoke-test the class-level colour constants."""

    def test_indicator_green_is_greenish(self):
        c = CueListView.INDICATOR_GREEN
        assert c.green() > c.red()
        assert c.green() > c.blue()

    def test_indicator_red_is_reddish(self):
        c = CueListView.INDICATOR_RED
        assert c.red() > c.green()
        assert c.red() > c.blue()

    def test_indicator_radius_is_positive(self):
        assert CueListView.INDICATOR_RADIUS > 0


class TestSignalSubscription:
    """The view must subscribe to armed_set_changed and repaint on emit."""

    def test_armed_set_changed_triggers_viewport_update(
        self, qapp, qtbot, mock_app, monkeypatch,
    ):
        """Emitting armed_set_changed must call viewport().update()."""
        mgr = _make_fake_manager()
        view = _build_view(mock_app, mgr=mgr)
        view.resize(600, 400)
        qtbot.addWidget(view)
        view.show()
        qtbot.waitExposed(view)

        calls = []
        real_update = view.viewport().update
        monkeypatch.setattr(
            view.viewport(),
            "update",
            lambda *a, **kw: (calls.append(1), real_update(*a, **kw))[1],
        )

        mgr.armed_set_changed.emit()

        assert calls, (
            "viewport().update() must be called when armed_set_changed fires"
        )

    def test_no_manager_does_not_crash_on_init(
        self, qapp, qtbot, mock_app,
    ):
        """Building a view without a pre_arm_manager must not raise."""
        view = _build_view(mock_app, mgr=None)
        view.resize(600, 400)
        qtbot.addWidget(view)
        view.show()
        qtbot.waitExposed(view)
        # No assertion needed — reaching here means no exception was raised.

    def test_handler_is_named_method_not_lambda(self):
        """_on_armed_set_changed must exist as a named method.

        LiSP signals use weak refs; anonymous lambdas get GC'd before
        the signal fires. Confirming the named method exists on the
        class guards against regression to a bare-lambda subscription.
        """
        assert callable(getattr(CueListView, "_on_armed_set_changed", None))


class TestPaintIndicators:
    """paintEvent must not crash when armed/failed cues are present."""

    def test_paint_with_armed_cue_does_not_crash(
        self, qapp, qtbot, mock_app,
    ):
        cue_id = "arm-cue"
        mgr = _make_fake_manager(armed={cue_id: object()})
        view = _build_view(mock_app, mgr=mgr)
        _add_cue(view, mock_app, cue_id=cue_id)

        view.resize(600, 400)
        qtbot.addWidget(view)
        view.show()
        qtbot.waitExposed(view)

        # Patch Application() to return the same fake_app during paint
        with patch(
            "lisp.plugins.list_layout.list_view.Application",
            return_value=view._fake_app,
        ):
            view.viewport().repaint()

    def test_paint_with_failed_preload_cue_does_not_crash(
        self, qapp, qtbot, mock_app,
    ):
        cue_id = "fail-cue"
        mgr = _make_fake_manager(
            failed={cue_id: "file not found"}
        )
        view = _build_view(mock_app, mgr=mgr)
        _add_cue(view, mock_app, cue_id=cue_id, preload=True)

        view.resize(600, 400)
        qtbot.addWidget(view)
        view.show()
        qtbot.waitExposed(view)

        with patch(
            "lisp.plugins.list_layout.list_view.Application",
            return_value=view._fake_app,
        ):
            view.viewport().repaint()

    def test_paint_with_failed_non_preload_cue_shows_no_dot(
        self, qapp, qtbot, mock_app, monkeypatch,
    ):
        """A cue in _failed but preload=False must not get a red dot."""
        cue_id = "silent-fail"
        mgr = _make_fake_manager(failed={cue_id: "audio decoder error"})
        view = _build_view(mock_app, mgr=mgr)
        _add_cue(view, mock_app, cue_id=cue_id, preload=False)

        view.resize(600, 400)
        qtbot.addWidget(view)
        view.show()
        qtbot.waitExposed(view)

        orig_painter_cls = QtGui.QPainter
        draw_calls = []

        class _SpyPainter(orig_painter_cls):
            def drawEllipse(self, *args, **kwargs):
                draw_calls.append(args)
                return super().drawEllipse(*args, **kwargs)

        with patch(
            "lisp.plugins.list_layout.list_view.Application",
            return_value=view._fake_app,
        ), patch(
            "lisp.plugins.list_layout.list_view.QPainter",
            _SpyPainter,
        ):
            view.viewport().repaint()

        assert not draw_calls, (
            "drawEllipse must NOT be called for a non-preload failed cue"
        )

    def test_paint_with_no_manager_does_not_crash(
        self, qapp, qtbot, mock_app,
    ):
        """paintEvent must be safe when pre_arm_manager is absent."""
        view = _build_view(mock_app, mgr=None)
        view.resize(600, 400)
        qtbot.addWidget(view)
        view.show()
        qtbot.waitExposed(view)

        with patch(
            "lisp.plugins.list_layout.list_view.Application",
            return_value=view._fake_app,
        ):
            view.viewport().repaint()


class TestTooltip:
    """viewportEvent must show failure reason tooltip only inside the dot."""

    def _make_help_event(self, view, item, offset_x=0, offset_y=0):
        """Return a QHelpEvent positioned relative to the dot centre."""
        row_rect = view.visualItemRect(item)
        dot_cx = row_rect.left() + CueListView.INDICATOR_CX
        dot_cy = row_rect.center().y()
        local_pt = QPoint(dot_cx + offset_x, dot_cy + offset_y)
        global_pt = view.viewport().mapToGlobal(local_pt)
        return QHelpEvent(QEvent.ToolTip, local_pt, global_pt)

    def test_hover_inside_dot_shows_tooltip(
        self, qapp, qtbot, mock_app,
    ):
        """A QHelpEvent inside the dot circle triggers QToolTip.showText
        with the failure reason."""
        cue_id = "fail-cue-tt"
        reason = "audio decoder error"
        mgr = _make_fake_manager(failed={cue_id: reason})
        view = _build_view(mock_app, mgr=mgr)
        cue = _add_cue(view, mock_app, cue_id=cue_id, preload=True)
        view.resize(600, 400)
        qtbot.addWidget(view)
        view.show()
        qtbot.waitExposed(view)

        item = view.cueItemAt(cue.index)
        event = self._make_help_event(view, item, offset_x=0, offset_y=0)

        with patch(
            "lisp.plugins.list_layout.list_view.Application",
            return_value=view._fake_app,
        ), patch(
            "lisp.plugins.list_layout.list_view.QToolTip.showText"
        ) as mock_show:
            view.viewportEvent(event)

        mock_show.assert_called_once()
        call_args = mock_show.call_args
        assert call_args[0][1] == reason, (
            "QToolTip.showText must be called with the failure reason"
        )

    def test_hover_outside_dot_does_not_show_tooltip(
        self, qapp, qtbot, mock_app,
    ):
        """A QHelpEvent far from the dot must not trigger QToolTip.showText."""
        cue_id = "fail-cue-outside"
        mgr = _make_fake_manager(failed={cue_id: "some error"})
        view = _build_view(mock_app, mgr=mgr)
        cue = _add_cue(view, mock_app, cue_id=cue_id, preload=True)
        view.resize(600, 400)
        qtbot.addWidget(view)
        view.show()
        qtbot.waitExposed(view)

        item = view.cueItemAt(cue.index)
        # Use a large x offset to land well outside the dot radius
        event = self._make_help_event(view, item, offset_x=200, offset_y=0)

        with patch(
            "lisp.plugins.list_layout.list_view.Application",
            return_value=view._fake_app,
        ), patch(
            "lisp.plugins.list_layout.list_view.QToolTip.showText"
        ) as mock_show:
            view.viewportEvent(event)

        mock_show.assert_not_called()

    def test_hover_on_non_preload_failed_cue_does_not_show_tooltip(
        self, qapp, qtbot, mock_app,
    ):
        """Failed cue with preload=False must not show tooltip even if cursor
        is inside the dot position."""
        cue_id = "non-preload-fail"
        mgr = _make_fake_manager(failed={cue_id: "pipeline error"})
        view = _build_view(mock_app, mgr=mgr)
        cue = _add_cue(view, mock_app, cue_id=cue_id, preload=False)
        view.resize(600, 400)
        qtbot.addWidget(view)
        view.show()
        qtbot.waitExposed(view)

        item = view.cueItemAt(cue.index)
        event = self._make_help_event(view, item, offset_x=0, offset_y=0)

        with patch(
            "lisp.plugins.list_layout.list_view.Application",
            return_value=view._fake_app,
        ), patch(
            "lisp.plugins.list_layout.list_view.QToolTip.showText"
        ) as mock_show:
            view.viewportEvent(event)

        mock_show.assert_not_called()
