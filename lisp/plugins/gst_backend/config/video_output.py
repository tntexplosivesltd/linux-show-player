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

from PyQt5.QtCore import Qt, QT_TRANSLATE_NOOP
from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QGroupBox,
    QLabel,
    QVBoxLayout,
    QApplication,
)

from lisp.ui.settings.pages import SettingsPage
from lisp.ui.ui_utils import translate


class VideoOutputConfig(SettingsPage):
    Name = QT_TRANSLATE_NOOP(
        "SettingsPageName", "Video Output"
    )

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.setLayout(QVBoxLayout())
        self.layout().setAlignment(Qt.AlignTop)

        # --- Display selection ---
        self.displayGroup = QGroupBox(self)
        self.displayGroup.setLayout(QVBoxLayout())
        self.layout().addWidget(self.displayGroup)

        self.screenCombo = QComboBox(self.displayGroup)
        self._populate_screens()
        self.displayGroup.layout().addWidget(self.screenCombo)

        self.screenHelpLabel = QLabel(self.displayGroup)
        self.screenHelpLabel.setWordWrap(True)
        self.displayGroup.layout().addWidget(self.screenHelpLabel)

        # --- Fullscreen ---
        self.fullscreenCheck = QCheckBox(self)
        self.fullscreenCheck.setChecked(True)
        self.layout().addWidget(self.fullscreenCheck)

        self.retranslateUi()

    def retranslateUi(self):
        self.displayGroup.setTitle(
            translate("VideoOutputConfig", "Video output display")
        )
        self.screenHelpLabel.setText(
            translate(
                "VideoOutputConfig",
                '"Auto" uses the first secondary display if '
                "connected, otherwise falls back to the "
                "primary display as a preview window.",
            )
        )
        self.fullscreenCheck.setText(
            translate(
                "VideoOutputConfig",
                "Fullscreen on secondary display",
            )
        )

    def loadSettings(self, settings):
        screen_index = settings.get("video_screen", -1)
        # -1 means "primary display" (item 0 in the combo)
        combo_index = screen_index + 1
        if 0 <= combo_index < self.screenCombo.count():
            self.screenCombo.setCurrentIndex(combo_index)
        else:
            self.screenCombo.setCurrentIndex(0)

        self.fullscreenCheck.setChecked(
            settings.get("video_fullscreen", True)
        )

    def getSettings(self):
        return {
            "video_screen": self.screenCombo.currentData(),
            "video_fullscreen": self.fullscreenCheck.isChecked(),
        }

    def _populate_screens(self):
        self.screenCombo.clear()
        self.screenCombo.addItem(
            translate(
                "VideoOutputConfig", "Auto (secondary if available)"
            ),
            -1,
        )
        for i, screen in enumerate(QApplication.screens()):
            label = f"{screen.name()} ({screen.size().width()}"
            label += f"x{screen.size().height()})"
            self.screenCombo.addItem(label, i)
