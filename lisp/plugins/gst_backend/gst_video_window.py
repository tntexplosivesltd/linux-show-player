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

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QCursor
from PyQt5.QtWidgets import QMainWindow, QWidget, QApplication

logger = logging.getLogger(__name__)


class VideoOutputWindow(QMainWindow):
    """Dedicated frameless window for video/image projection.

    Managed as a singleton by GstBackend.  GStreamer's VideoOverlay
    interface renders directly into a native child widget via its
    X11 window ID.

    A separate native child widget (_render_widget) holds the video
    surface.  Hiding it reveals the black background underneath,
    providing a reliable way to clear stale frames between cues
    without needing a separate GStreamer pipeline.

    The window ignores close events while video/image cues exist
    (visibility is managed by GstBackend's auto-show/hide logic).
    """

    def __init__(self, parent=None):
        super().__init__(parent, Qt.FramelessWindowHint)
        self.setWindowTitle("LiSP Video Output")

        # Black background — visible between cues and behind
        # letterboxed content.
        central = QWidget(self)
        central.setStyleSheet("background-color: black;")
        self.setCentralWidget(central)

        # Native child widget for GStreamer rendering.  Hiding
        # this widget unmaps its X11 window so the parent's
        # black background shows through.
        self._render_widget = QWidget(central)
        self._render_widget.setAttribute(Qt.WA_NativeWindow)
        self._render_widget.setAttribute(
            Qt.WA_DontCreateNativeAncestors
        )

        self._fullscreen = False
        self.resize(640, 480)

    def window_handle(self):
        """Return the native window ID for GStreamer VideoOverlay."""
        return int(self._render_widget.winId())

    def clear_display(self):
        """Hide the render surface, showing the black background."""
        self._render_widget.hide()

    def show_display(self):
        """Show the render surface for GStreamer output."""
        self._render_widget.show()
        self._sync_render_geometry()

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

    def _sync_render_geometry(self):
        """Keep the render widget filling the central widget."""
        central = self.centralWidget()
        if central is not None:
            self._render_widget.setGeometry(central.rect())

    def closeEvent(self, event):
        """Block close while video/image cues exist."""
        event.ignore()


class VideoMonitorWindow(QMainWindow):
    """Small floating window that mirrors the projection output.

    Provides a confidence monitor on the operator's primary screen
    so they can see what's being projected without line-of-sight to
    the projection surface.  GStreamer renders into this window via
    a second VideoOverlay sink fed by a tee in the VideoSink pipeline.

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

    def clear_display(self):
        """Hide the render surface, showing the black background."""
        self._render_widget.hide()

    def show_display(self):
        """Show the render surface for GStreamer output."""
        self._render_widget.show()
        self._sync_render_geometry()

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
