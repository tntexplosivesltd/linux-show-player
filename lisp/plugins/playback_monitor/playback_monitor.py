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

from PyQt5.QtGui import QKeySequence
from PyQt5.QtWidgets import QAction

from lisp.core.plugin import Plugin
from lisp.core.signal import Connection
from lisp.plugins.playback_monitor.monitor_window import (
    PlaybackMonitorWindow,
)
from lisp.ui.ui_utils import translate


class PlaybackMonitor(Plugin):
    Name = "Playback Monitor"
    Authors = ("Linux Show Player Contributors",)
    Description = (
        "Standalone window showing elapsed and remaining time"
    )

    def __init__(self, app):
        super().__init__(app)
        self._window = None
        self._tracked_cues = {}

        # Menu action with keyboard shortcut
        self._action = QAction(app.window)
        self._action.setText(
            translate("PlaybackMonitor", "Playback Monitor")
        )
        self._action.setShortcut(QKeySequence("Ctrl+M"))
        self._action.triggered.connect(self._toggle_window)
        app.window.menuTools.addAction(self._action)

        # Watch for cue additions/removals
        app.cue_model.item_added.connect(self._cue_added)
        app.cue_model.item_removed.connect(self._cue_removed)
        app.cue_model.model_reset.connect(self._model_reset)

        # Reset on session changes
        app.session_before_finalize.connect(self._session_reset)

    def _toggle_window(self):
        if self._window is None:
            self._window = PlaybackMonitorWindow(
                PlaybackMonitor.Config
            )
            self._window.show()
        elif self._window.isVisible():
            self._window.close()
        else:
            self._window.show()
            self._window.raise_()

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
        if self._window is not None:
            self._window.close()
            self._window = None
        super().finalize()
