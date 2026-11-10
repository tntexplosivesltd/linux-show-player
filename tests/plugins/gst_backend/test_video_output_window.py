"""Tests for VideoOutputWindow and VideoMonitorWindow."""

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication

from lisp.plugins.gst_backend.gst_video_window import (
    VideoMonitorWindow,
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

    def test_render_widget_mapped_when_shown(self, qtbot):
        # No clear/show any more: the render widget stays mapped and
        # black-between-cues comes from the compositor's background.
        window = VideoOutputWindow()
        qtbot.addWidget(window)
        window.show()
        qtbot.waitExposed(window)
        assert window._render_widget.isVisible()

    def test_render_widget_is_native(self, qtbot):
        window = VideoOutputWindow()
        qtbot.addWidget(window)
        assert window._render_widget.testAttribute(
            Qt.WA_NativeWindow
        )

    def test_fullscreen_hides_cursor(self, qtbot):
        window = VideoOutputWindow()
        qtbot.addWidget(window)
        window.show()
        qtbot.waitExposed(window)
        window.set_fullscreen(True)
        assert window.cursor().shape() == Qt.BlankCursor

    def test_normal_restores_cursor(self, qtbot):
        window = VideoOutputWindow()
        qtbot.addWidget(window)
        window.show()
        qtbot.waitExposed(window)
        window.set_fullscreen(True)
        window.set_fullscreen(False)
        assert window.cursor().shape() == Qt.ArrowCursor


class TestVideoMonitorWindowCreation:
    def test_creates_window(self, qtbot):
        window = VideoMonitorWindow()
        qtbot.addWidget(window)
        assert window is not None

    def test_has_title_bar(self, qtbot):
        """Monitor window should NOT have FramelessWindowHint."""
        window = VideoMonitorWindow()
        qtbot.addWidget(window)
        assert not (window.windowFlags() & Qt.FramelessWindowHint)

    def test_stays_on_top(self, qtbot):
        window = VideoMonitorWindow()
        qtbot.addWidget(window)
        assert window.windowFlags() & Qt.WindowStaysOnTopHint

    def test_default_size(self, qtbot):
        window = VideoMonitorWindow()
        qtbot.addWidget(window)
        assert window.width() == 640
        assert window.height() == 360

    def test_window_handle_returns_nonzero(self, qtbot):
        window = VideoMonitorWindow()
        qtbot.addWidget(window)
        handle = window.window_handle()
        assert isinstance(handle, int)
        assert handle != 0

    def test_central_widget_has_black_background(self, qtbot):
        window = VideoMonitorWindow()
        qtbot.addWidget(window)
        assert "black" in window.centralWidget().styleSheet()

    def test_render_widget_is_native(self, qtbot):
        window = VideoMonitorWindow()
        qtbot.addWidget(window)
        assert window._render_widget.testAttribute(
            Qt.WA_NativeWindow
        )


class TestVideoMonitorWindowBehavior:
    def test_close_hides_instead_of_closing(self, qtbot):
        window = VideoMonitorWindow()
        qtbot.addWidget(window)
        window.show()
        qtbot.waitExposed(window)

        window.close()
        assert not window.isVisible()

    def test_render_widget_mapped_when_shown(self, qtbot):
        # No clear/show any more: the render widget stays mapped and
        # black-between-cues comes from the compositor's background.
        window = VideoMonitorWindow()
        qtbot.addWidget(window)
        window.show()
        qtbot.waitExposed(window)
        assert window._render_widget.isVisible()


class _FakeScreen:
    def __init__(self, w, h, dpr=1.0):
        self._w, self._h, self._dpr = w, h, dpr

    def geometry(self):
        from PyQt5.QtCore import QRect
        return QRect(0, 0, self._w, self._h)

    def devicePixelRatio(self):
        return self._dpr


class TestVideoOutputWindowCanvasSize:
    """The compositor canvas is the output SCREEN's resolution, not the
    window's size: a window resize must not renegotiate the canvas (the
    caps change raced glimagesink's own resize and left the picture
    squeezed or magnified). glimagesink letterboxes the canvas into
    whatever size the window is."""

    def _shown(self, qtbot):
        window = VideoOutputWindow()
        qtbot.addWidget(window)
        window.show()
        qtbot.waitExposed(window)
        qtbot.wait(400)  # let the show-time emission pass
        return window

    def test_canvas_is_the_screen_resolution(self, qtbot):
        window = self._shown(qtbot)
        screen = window.output_screen()
        dpr = screen.devicePixelRatio()
        geo = screen.geometry()
        assert window.canvas_size() == (
            int(geo.width() * dpr) & ~1, int(geo.height() * dpr) & ~1
        )

    def test_canvas_ignores_window_size(self, qtbot):
        window = self._shown(qtbot)
        before = window.canvas_size()
        window.resize(500, 700)
        QApplication.processEvents()
        assert window.canvas_size() == before

    def test_resize_does_not_emit(self, qtbot):
        window = self._shown(qtbot)
        emitted = []

        def on_changed(w, h):
            emitted.append((w, h))

        window.canvas_size_changed.connect(on_changed)
        for width in (700, 720, 740):
            window.resize(width, 500)
        qtbot.wait(500)
        assert emitted == []

    def test_screen_change_emits_once(self, qtbot, monkeypatch):
        window = self._shown(qtbot)
        emitted = []

        def on_changed(w, h):
            emitted.append((w, h))

        window.canvas_size_changed.connect(on_changed)
        monkeypatch.setattr(window, "output_screen",
                            lambda: _FakeScreen(3840, 2160))
        window.move(window.x() + 1, window.y())
        window.move(window.x() + 1, window.y())
        qtbot.waitUntil(lambda: emitted == [(3840, 2160)], timeout=1500)
        qtbot.wait(300)
        assert emitted == [(3840, 2160)]  # debounced, deduplicated

    def test_hidpi_screen_is_physical_pixels(self, qtbot, monkeypatch):
        window = self._shown(qtbot)
        monkeypatch.setattr(window, "output_screen",
                            lambda: _FakeScreen(1280, 800, 2.0))
        assert window.canvas_size() == (2560, 1600)

