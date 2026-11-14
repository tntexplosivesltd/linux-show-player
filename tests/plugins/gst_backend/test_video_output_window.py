"""Tests for VideoOutputWindow and VideoMonitorWindow."""

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication

from lisp.plugins.gst_backend import gst_video_window as gvw
from lisp.plugins.gst_backend.gst_video_window import (
    VideoMonitorWindow,
    VideoOutputWindow,
)
from lisp.plugins.gst_backend.video_compositor import (
    COMP_HEIGHT,
    COMP_WIDTH,
    canvas_size_for,
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
    def __init__(self, w, h, dpr=1.0, name="fake"):
        self._w, self._h, self._dpr, self._name = w, h, dpr, name

    def geometry(self):
        from PyQt5.QtCore import QRect
        return QRect(0, 0, self._w, self._h)

    def devicePixelRatio(self):
        return self._dpr

    def name(self):
        return self._name


def _recorder(window):
    """Connect to canvas_size_changed; return the list it fills. A named
    function, not a lambda, so the connection's lifetime is plain."""
    emitted = []

    def on_changed(w, h):
        emitted.append((w, h))

    window.canvas_size_changed.connect(on_changed)
    return emitted


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

    def test_show_emits_the_canvas_once(self, qtbot):
        window = VideoOutputWindow()
        qtbot.addWidget(window)
        emitted = _recorder(window)
        window.show()
        qtbot.waitExposed(window)
        qtbot.waitUntil(lambda: bool(emitted), timeout=1500)
        qtbot.wait(300)
        assert emitted == [window.canvas_size()]

    def test_resize_does_not_emit(self, qtbot):
        window = self._shown(qtbot)
        emitted = _recorder(window)
        for width in (700, 720, 740):
            window.resize(width, 500)
        qtbot.wait(500)
        assert emitted == []

    def test_screen_change_emits_once(self, qtbot, monkeypatch):
        window = self._shown(qtbot)
        emitted = _recorder(window)
        monkeypatch.setattr(window, "output_screen",
                            lambda: _FakeScreen(3840, 2160))
        window.move(window.x() + 1, window.y())
        window.move(window.x() + 1, window.y())
        qtbot.waitUntil(lambda: emitted == [(3840, 2160)], timeout=1500)
        qtbot.wait(300)
        assert emitted == [(3840, 2160)]  # debounced, deduplicated

    def test_screen_mode_change_emits(self, qtbot, monkeypatch):
        # An xrandr mode switch under a window that does not move.
        window = self._shown(qtbot)
        emitted = _recorder(window)
        monkeypatch.setattr(window, "output_screen",
                            lambda: _FakeScreen(1280, 720))
        screen = QApplication.primaryScreen()
        screen.geometryChanged.emit(screen.geometry())
        qtbot.waitUntil(lambda: emitted == [(1280, 720)], timeout=1500)

    def test_screen_unplug_emits(self, qtbot, monkeypatch):
        # Qt re-homes the window when its screen goes away; the
        # removal itself must trigger a re-check.
        window = self._shown(qtbot)
        emitted = _recorder(window)
        monkeypatch.setattr(window, "output_screen",
                            lambda: _FakeScreen(1024, 768))
        QApplication.instance().screenRemoved.emit(
            QApplication.primaryScreen())
        qtbot.waitUntil(lambda: emitted == [(1024, 768)], timeout=1500)

    def test_hotplugged_screen_is_watched(self, qtbot, monkeypatch):
        window = self._shown(qtbot)
        watched = []
        monkeypatch.setattr(window, "_watch_screen", watched.append)
        screen = QApplication.primaryScreen()
        QApplication.instance().screenAdded.emit(screen)
        assert watched == [screen]

    def test_hidpi_screen_is_physical_pixels(self, qtbot, monkeypatch):
        window = self._shown(qtbot)
        monkeypatch.setattr(window, "output_screen",
                            lambda: _FakeScreen(1280, 800, 2.0))
        assert window.canvas_size() == (2560, 1600)

    def test_screen_smaller_than_min_uses_default(self, qtbot,
                                                  monkeypatch):
        window = self._shown(qtbot)
        monkeypatch.setattr(window, "output_screen",
                            lambda: _FakeScreen(32, 32))
        assert window.canvas_size() == (COMP_WIDTH, COMP_HEIGHT)


class TestVideoOutputWindowCanvasFollowsWindow:
    """With a sink that cannot scale (ximagesink), the canvas must be
    the render area, as before: a screen-sized canvas would be drawn
    1:1 and cropped to the window's middle."""

    def _shown(self, qtbot):
        window = VideoOutputWindow()
        qtbot.addWidget(window)
        window.set_canvas_follows_window(True)
        window.show()
        qtbot.waitExposed(window)
        qtbot.wait(400)
        return window

    def test_canvas_is_the_render_area(self, qtbot):
        window = self._shown(qtbot)
        rw = window._render_widget
        dpr = rw.devicePixelRatioF()
        assert window.canvas_size() == (
            int(round(rw.width() * dpr)) & ~1,
            int(round(rw.height() * dpr)) & ~1,
        )

    def test_resize_emits_the_new_render_area(self, qtbot):
        window = self._shown(qtbot)
        emitted = _recorder(window)
        window.resize(700, 500)
        window.resize(740, 520)
        qtbot.waitUntil(lambda: bool(emitted), timeout=1500)
        qtbot.wait(300)
        assert emitted == [window.canvas_size()]  # debounced
        screen = window.output_screen()
        geo = screen.geometry()
        assert emitted[0] != canvas_size_for(
            geo.width(), geo.height(), screen.devicePixelRatio())

    def test_enabling_rechecks_the_canvas(self, qtbot):
        window = VideoOutputWindow()
        qtbot.addWidget(window)
        window.show()
        qtbot.waitExposed(window)
        qtbot.wait(400)
        emitted = _recorder(window)
        window.set_canvas_follows_window(True)
        qtbot.waitUntil(lambda: bool(emitted), timeout=1500)
        assert emitted == [window.canvas_size()]


class TestVideoOutputWindowOutputScreen:
    """Which screen the canvas is sized from."""

    def test_hidden_window_uses_the_target_screen(self, qtbot,
                                                  monkeypatch):
        # At startup the compositor reads canvas_size() while the
        # window is hidden; it must be the projector it will open on,
        # not whatever screen() a never-shown window reports.
        window = VideoOutputWindow()
        qtbot.addWidget(window)
        projector = _FakeScreen(3840, 2160, name="HDMI-1")
        monkeypatch.setattr(
            gvw.QApplication, "screens",
            staticmethod(lambda: [QApplication.primaryScreen(),
                                  projector]))
        window.set_display_screen(projector)
        assert window.output_screen() is projector
        assert window.canvas_size() == (3840, 2160)

    def test_disconnected_target_is_ignored(self, qtbot):
        window = VideoOutputWindow()
        qtbot.addWidget(window)
        window.set_display_screen(_FakeScreen(3840, 2160))  # not listed
        # Falls back to the screen Qt has the window on, else the
        # primary: a real, listed screen either way.
        expected = window.screen() or QApplication.primaryScreen()
        assert expected in QApplication.screens()
        assert window.output_screen() is expected

    def test_shown_window_uses_its_actual_screen(self, qtbot,
                                                 monkeypatch):
        window = VideoOutputWindow()
        qtbot.addWidget(window)
        projector = _FakeScreen(3840, 2160)
        monkeypatch.setattr(
            gvw.QApplication, "screens",
            staticmethod(lambda: [QApplication.primaryScreen(),
                                  projector]))
        window.set_display_screen(projector)
        window.show()
        qtbot.waitExposed(window)
        assert window.output_screen() is window.screen()

    def test_no_screen_falls_back_to_primary(self, qtbot, monkeypatch):
        window = VideoOutputWindow()
        qtbot.addWidget(window)
        window.show()
        qtbot.waitExposed(window)
        monkeypatch.setattr(window, "screen", lambda: None)
        assert window.output_screen() is QApplication.primaryScreen()
