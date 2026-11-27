# This file is part of Linux Show Player
#
# Copyright 2017 Francesco Ceruti <ceppofrancy@gmail.com>
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

from PyQt5.QtGui import QKeySequence
from PyQt5.QtWidgets import QAction

from lisp.core.plugin import Plugin
from lisp.core.signal import Connection
from lisp.plugins.playback_monitor.monitor_window import (
    PlaybackMonitorWindow,
)
from lisp.ui.ui_utils import translate

logger = logging.getLogger(__name__)


class PlaybackMonitor(Plugin):
    Name = "Playback Monitor"
    Authors = ("Linux Show Player Contributors",)
    OptDepends = ("GstBackend",)
    Description = (
        "Standalone window showing elapsed and remaining time"
    )

    # Config key: was the window open when LiSP last exited?
    OPEN_KEY = "open"

    def __init__(self, app):
        super().__init__(app)
        self._window = None
        self._tracked_cues = {}
        # Set while LiSP shuts down: closing the window then must not
        # be recorded as the operator closing it.
        self._finalizing = False

        # Menu action with keyboard shortcut
        self._action = QAction(app.window)
        self._action.setText(
            translate("PlaybackMonitor", "Playback Monitor")
        )
        self._action.setShortcut(
            QKeySequence("Ctrl+Shift+M")
        )
        self._action.triggered.connect(self._toggle_window)
        app.window.menuTools.addAction(self._action)

        # Watch for cue additions/removals
        app.cue_model.item_added.connect(self._cue_added)
        app.cue_model.item_removed.connect(self._cue_removed)
        app.cue_model.model_reset.connect(self._model_reset)

        # Reset on session changes
        app.session_before_finalize.connect(self._session_reset)

        # Reopen the window if it was open when LiSP last exited. On
        # the first session, so it appears with the main window.
        app.session_created.connect(self._reopen_window)

    def _toggle_window(self):
        if self._window is None:
            self._window = PlaybackMonitorWindow(
                PlaybackMonitor.Config
            )
            self._window.closed.connect(self._window_closed)
            self._window.show()
            self._remember_open(True)
        elif self._window.isVisible():
            self._window.close()
        else:
            self._window.show()
            self._window.raise_()
            self._remember_open(True)

    def _reopen_window(self, *_):
        self.app.session_created.disconnect(self._reopen_window)
        if PlaybackMonitor.Config.get(self.OPEN_KEY, False) and not (
            self._window is not None and self._window.isVisible()
        ):
            self._toggle_window()

    def _window_closed(self):
        if not self._finalizing:
            self._remember_open(False)

    def _remember_open(self, is_open):
        # Best effort: called from Qt slots, where an exception (full
        # disk, read-only config dir) would abort LiSP.
        try:
            PlaybackMonitor.Config.set(self.OPEN_KEY, is_open)
            PlaybackMonitor.Config.write()
        except Exception:
            logger.exception("Could not save the playback monitor state")

    def _cue_added(self, cue):
        cue.started.connect(
            self._cue_started, Connection.QtQueued
        )
        self._tracked_cues[cue.id] = cue

    def _cue_removed(self, cue):
        cue.started.disconnect(self._cue_started)
        self._tracked_cues.pop(cue.id, None)

    def _cue_started(self, cue):
        if (
            self._window is not None
            and self._window.isVisible()
        ):
            self._window.track_cue(cue)

    def _disconnect_all_cues(self):
        for cue in self._tracked_cues.values():
            cue.started.disconnect(self._cue_started)
        self._tracked_cues.clear()

    def _model_reset(self):
        self._disconnect_all_cues()
        if self._window is not None:
            self._window.reset()

    def _session_reset(self):
        self._disconnect_all_cues()
        if self._window is not None:
            self._window.reset()

    def finalize(self):
        self._finalizing = True
        self._disconnect_all_cues()
        self.app.window.menuTools.removeAction(self._action)
        if self._window is not None:
            self._window.close()
            self._window = None
        super().finalize()
