"""Tests for VideoOutputWindow."""

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication

from lisp.plugins.gst_backend.gst_video_window import (
    VideoOutputWindow,
)


class TestVideoOutputWindowCreation:
    def test_creates_window(self, qtbot):
        window = VideoOutputWindow()
        qtbot.addWidget(window)
        assert window is not None

    def test_frameless_hint(self, qtbot):
        window = VideoOutputWindow()
        qtbot.addWidget(window)
        assert window.windowFlags() & Qt.FramelessWindowHint

    def test_window_handle_returns_nonzero(self, qtbot):
        window = VideoOutputWindow()
        qtbot.addWidget(window)
        handle = window.window_handle()
        assert isinstance(handle, int)
        assert handle != 0

    def test_central_widget_has_black_background(self, qtbot):
        window = VideoOutputWindow()
        qtbot.addWidget(window)
        assert "black" in window.centralWidget().styleSheet()


class TestVideoOutputWindowBehavior:
    def test_close_event_blocked(self, qtbot):
        """Close is blocked — visibility managed by GstBackend."""
        window = VideoOutputWindow()
        qtbot.addWidget(window)
        window.show()
        qtbot.waitExposed(window)

        window.close()

        assert window.isVisible()

    def test_set_fullscreen_true(self, qtbot):
        window = VideoOutputWindow()
        qtbot.addWidget(window)
        window.show()
        qtbot.waitExposed(window)
        window.set_fullscreen(True)
        assert window.isFullScreen()

    def test_set_fullscreen_false(self, qtbot):
        window = VideoOutputWindow()
        qtbot.addWidget(window)
        window.show()
        qtbot.waitExposed(window)
        window.set_fullscreen(True)
        window.set_fullscreen(False)
        assert not window.isFullScreen()

    def test_set_fullscreen_deferred(self, qtbot):
        """Fullscreen is applied when the window is shown."""
        window = VideoOutputWindow()
        qtbot.addWidget(window)
        window.set_fullscreen(True)
        # Not visible yet — isFullScreen() is False
        assert not window.isFullScreen()
        window.show()
        qtbot.waitExposed(window)
        assert window.isFullScreen()

    def test_set_display_out_of_range(self, qtbot):
        window = VideoOutputWindow()
        qtbot.addWidget(window)
        window.set_display(999)

    def test_set_display_valid_index(self, qtbot):
        window = VideoOutputWindow()
        qtbot.addWidget(window)
        screens = QApplication.screens()
        if screens:
            window.set_display(0)
            screen_geo = screens[0].geometry()
            assert window.pos() == screen_geo.topLeft()

    def test_clear_display_hides_render_widget(self, qtbot):
        window = VideoOutputWindow()
        qtbot.addWidget(window)
        window.show()
        qtbot.waitExposed(window)

        window.show_display()
        assert window._render_widget.isVisible()

        window.clear_display()
        assert not window._render_widget.isVisible()

    def test_show_display_shows_render_widget(self, qtbot):
        window = VideoOutputWindow()
        qtbot.addWidget(window)
        window.show()
        qtbot.waitExposed(window)

        window.clear_display()
        assert not window._render_widget.isVisible()

        window.show_display()
        assert window._render_widget.isVisible()

    def test_render_widget_is_native(self, qtbot):
        window = VideoOutputWindow()
        qtbot.addWidget(window)
        assert window._render_widget.testAttribute(
            Qt.WA_NativeWindow
        )
