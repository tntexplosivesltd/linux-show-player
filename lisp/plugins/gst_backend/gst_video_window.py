# This file is part of Linux Show Player
#
# Copyright 2025 Thomas Sherlock
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

import logging

from PyQt5.QtCore import Qt, QTimer, pyqtSignal, pyqtSlot
from PyQt5.QtGui import QCursor
from PyQt5.QtWidgets import QMainWindow, QWidget, QApplication

from lisp.plugins.gst_backend.video_compositor import canvas_size_for

logger = logging.getLogger(__name__)


class VideoOutputWindow(QMainWindow):
    """Dedicated frameless window for video/image projection.

    Managed as a singleton by GstBackend.  GStreamer's VideoOverlay
    interface renders directly into a native child widget via its
    X11 window ID.

    A separate native child widget (_render_widget) holds the video
    surface.  It stays mapped for the process lifetime: the
    VideoCompositor's sink binds to it once, and black-between-cues
    is the compositor's own background layer, not a hidden widget.

    The window ignores close events while video/image cues exist
    (visibility is managed by GstBackend's auto-show/hide logic).
    """

    # The output screen's resolution in physical pixels, emitted when it
    # changes (shown, moved to another screen, the screen's mode changed
    # or a screen was plugged / unplugged); the VideoCompositor
    # canvas follows it (see GstBackend). NOT the window's size: a
    # window resize must not renegotiate the canvas — that caps change
    # raced glimagesink's own resize handling, which letterboxed the
    # canvas by a stale size and could leave the picture squeezed or
    # magnified. glimagesink fits the canvas to the window itself.
    canvas_size_changed = pyqtSignal(int, int)

    # Coalesce a burst of moves (e.g. a drag across screens) into one
    # check of the screen.
    CANVAS_SIZE_DEBOUNCE_MS = 150

    def __init__(self, parent=None):
        super().__init__(parent, Qt.FramelessWindowHint)
        self.setWindowTitle("LiSP Video Output")

        # Black background — visible between cues and behind
        # letterboxed content.
        central = QWidget(self)
        central.setStyleSheet("background-color: black;")
        self.setCentralWidget(central)

        # Native child widget for GStreamer rendering.
        self._render_widget = QWidget(central)
        self._render_widget.setAttribute(Qt.WA_NativeWindow)
        self._render_widget.setAttribute(
            Qt.WA_DontCreateNativeAncestors
        )

        self._fullscreen = False
        # Where set_display_screen() put the window: what the canvas is
        # sized from while hidden (screen() of a never-shown window may
        # still be the primary, not the projector it will open on).
        self._target_screen = None

        self._emitted_canvas = None
        self._canvas_timer = QTimer(self)
        self._canvas_timer.setSingleShot(True)
        self._canvas_timer.setInterval(self.CANVAS_SIZE_DEBOUNCE_MS)
        self._canvas_timer.timeout.connect(self._emit_canvas_size)

        # The canvas follows the screen, so a screen change that moves
        # no window (an xrandr mode switch, a projector re-plugged at
        # another resolution, Qt re-homing the window after an unplug)
        # must re-check it too. Re-checks are deduplicated, so reacting
        # to every screen is harmless.
        app = QApplication.instance()
        app.screenAdded.connect(self._on_screen_added)
        app.screenRemoved.connect(self._schedule_canvas_check)
        app.primaryScreenChanged.connect(self._schedule_canvas_check)
        for screen in QApplication.screens():
            self._watch_screen(screen)

        self.resize(640, 480)

    def window_handle(self):
        """Return the native window ID for GStreamer VideoOverlay."""
        return int(self._render_widget.winId())

    def output_screen(self):
        """The screen the window is on (while hidden: the one
        set_display_screen() targeted); the primary if it is on none
        (e.g. placed where a now-disconnected screen used to be)."""
        screens = QApplication.screens()
        if not self.isVisible() and self._target_screen in screens:
            return self._target_screen
        screen = self.screen()
        if screen is None or screen not in screens:
            screen = QApplication.primaryScreen()
        return screen

    def canvas_size(self):
        """The compositor canvas: the output screen's resolution in
        physical pixels. Fullscreen (a show) it is the window; windowed
        glimagesink letterboxes it into the window."""
        screen = self.output_screen()
        geo = screen.geometry()
        return canvas_size_for(
            geo.width(), geo.height(), screen.devicePixelRatio()
        )

    def _watch_screen(self, screen):
        screen.geometryChanged.connect(self._schedule_canvas_check)

    @pyqtSlot("QScreen*")
    def _on_screen_added(self, screen):
        self._watch_screen(screen)
        self._schedule_canvas_check()

    @pyqtSlot()
    def _schedule_canvas_check(self):
        """(Re)start the debounced canvas check."""
        self._canvas_timer.start()

    def _emit_canvas_size(self):
        size = self.canvas_size()
        if size != self._emitted_canvas:
            self._emitted_canvas = size
            self.canvas_size_changed.emit(*size)

    def set_display(self, screen_index):
        """Move the window to the specified screen by index.

        :param screen_index: Index into QApplication.screens()
        """
        screens = QApplication.screens()
        if 0 <= screen_index < len(screens):
            self.set_display_screen(screens[screen_index])
        else:
            logger.warning(
                "VideoOutputWindow: screen index %d out of "
                "range (have %d screens)",
                screen_index,
                len(screens),
            )

    def set_display_screen(self, screen):
        """Move the window to the given QScreen.

        :param screen: Target QScreen
        """
        self._target_screen = screen
        geo = screen.geometry()
        self.move(geo.topLeft())
        logger.debug(
            "VideoOutputWindow: moved to screen %s",
            screen.name(),
        )

    def set_fullscreen(self, enabled):
        """Toggle fullscreen mode.

        If the window is already visible the change is applied
        immediately.  Otherwise it is stored and applied the next
        time the window is shown.
        """
        self._fullscreen = enabled
        if self.isVisible():
            self._apply_fullscreen()

    def show(self):
        """Apply deferred fullscreen setting, then show."""
        self._apply_fullscreen()

    def _apply_fullscreen(self):
        if self._fullscreen:
            self.setCursor(QCursor(Qt.BlankCursor))
            self.showFullScreen()
        else:
            self.setCursor(QCursor(Qt.ArrowCursor))
            self.showNormal()
        self._sync_render_geometry()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._sync_render_geometry()

    def moveEvent(self, event):
        super().moveEvent(event)
        # May have crossed onto another screen.
        self._schedule_canvas_check()

    def _sync_render_geometry(self):
        """Keep the render widget filling the central widget."""
        central = self.centralWidget()
        if central is not None:
            self._render_widget.setGeometry(central.rect())
        self._schedule_canvas_check()

    def closeEvent(self, event):
        """Block close while video/image cues exist."""
        event.ignore()


class VideoMonitorWindow(QMainWindow):
    """Small floating window that mirrors the projection output.

    Provides a confidence monitor on the operator's primary screen
    so they can see what's being projected without line-of-sight to
    the projection surface.  GStreamer renders into this window via
    the VideoCompositor's second (monitor) sink, fed by a leaky tee
    branch off the projection mixer.

    Closing the window hides it (the menu toggle re-shows it).
    """

    def __init__(self, parent=None):
        super().__init__(
            parent,
            Qt.Window | Qt.WindowStaysOnTopHint,
        )
        self.setWindowTitle("LiSP Video Monitor")
        self.resize(640, 360)

        central = QWidget(self)
        central.setStyleSheet("background-color: black;")
        self.setCentralWidget(central)

        self._render_widget = QWidget(central)
        self._render_widget.setAttribute(Qt.WA_NativeWindow)
        self._render_widget.setAttribute(
            Qt.WA_DontCreateNativeAncestors
        )

    def window_handle(self):
        """Return the native window ID for GStreamer VideoOverlay."""
        return int(self._render_widget.winId())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._sync_render_geometry()

    def _sync_render_geometry(self):
        """Keep the render widget filling the central widget."""
        central = self.centralWidget()
        if central is not None:
            self._render_widget.setGeometry(central.rect())

    def closeEvent(self, event):
        """Hide instead of close so the window can be re-shown."""
        event.ignore()
        self.hide()
