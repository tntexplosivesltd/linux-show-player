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

import os

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QCheckBox,
    QGroupBox,
    QHBoxLayout,
    QPushButton,
    QLineEdit,
    QFileDialog,
    QVBoxLayout,
    QDoubleSpinBox,
)

from lisp.application import Application
from lisp.core.session_uri import SessionURI
from lisp.plugins.gst_backend import GstBackend
from lisp.plugins.gst_backend.elements.image_input import ImageInput
from lisp.ui.settings.pages import SettingsPage
from lisp.ui.ui_utils import translate


class ImageInputSettings(SettingsPage):
    ELEMENT = ImageInput
    Name = ELEMENT.Name

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.setLayout(QVBoxLayout())
        self.layout().setAlignment(Qt.AlignTop)

        # --- Source file ---
        self.fileGroup = QGroupBox(self)
        self.fileGroup.setLayout(QHBoxLayout())
        self.layout().addWidget(self.fileGroup)

        self.buttonFindFile = QPushButton(self.fileGroup)
        self.fileGroup.layout().addWidget(self.buttonFindFile)

        self.filePath = QLineEdit("file://", self.fileGroup)
        self.fileGroup.layout().addWidget(self.filePath)

        # --- Display duration ---
        self.durationGroup = QGroupBox(self)
        self.durationGroup.setLayout(QVBoxLayout())
        self.layout().addWidget(self.durationGroup)

        self.indefiniteCheck = QCheckBox(self.durationGroup)
        self.durationGroup.layout().addWidget(self.indefiniteCheck)

        self.durationSpin = QDoubleSpinBox(self.durationGroup)
        self.durationSpin.setRange(0.1, 3600.0)
        self.durationSpin.setDecimals(1)
        self.durationSpin.setSingleStep(0.5)
        self.durationSpin.setSuffix(" s")
        self.durationSpin.setValue(5.0)
        self.durationGroup.layout().addWidget(self.durationSpin)

        self.indefiniteCheck.toggled.connect(
            lambda checked: self.durationSpin.setEnabled(
                not checked
            )
        )

        self.buttonFindFile.clicked.connect(self.select_file)

        self.retranslateUi()

    def retranslateUi(self):
        self.fileGroup.setTitle(
            translate("ImageInputSettings", "Source")
        )
        self.buttonFindFile.setText(
            translate("ImageInputSettings", "Find File")
        )
        self.durationGroup.setTitle(
            translate("ImageInputSettings", "Display Duration")
        )
        self.indefiniteCheck.setText(
            translate(
                "ImageInputSettings",
                "Display until stopped",
            )
        )

    def getSettings(self):
        settings = {}

        if self.isGroupEnabled(self.fileGroup):
            settings["uri"] = self.filePath.text()
        if self.isGroupEnabled(self.durationGroup):
            if self.indefiniteCheck.isChecked():
                settings["duration"] = -1
            else:
                settings["duration"] = int(
                    self.durationSpin.value() * 1000
                )

        return settings

    def loadSettings(self, settings):
        self.filePath.setText(settings.get("uri", ""))
        duration_ms = settings.get("duration", 5000)
        if duration_ms < 0:
            self.indefiniteCheck.setChecked(True)
            self.durationSpin.setValue(5.0)
        else:
            self.indefiniteCheck.setChecked(False)
            self.durationSpin.setValue(duration_ms / 1000.0)

    def enableCheck(self, enabled):
        self.setGroupEnabled(self.fileGroup, enabled)
        self.setGroupEnabled(self.durationGroup, enabled)

    def select_file(self):
        directory = ""
        current = SessionURI(self.filePath.text())

        if current.is_local:
            directory = current.absolute_path
        if not os.path.exists(directory):
            directory = GstBackend.Config.get(
                "mediaLookupDir", ""
            )
        if not os.path.exists(directory):
            directory = Application().session.dir()

        path, _ = QFileDialog.getOpenFileName(
            self,
            translate("ImageInputSettings", "Choose file"),
            directory,
            translate("ImageInputSettings", "Image files")
            + " (*.jpg *.jpeg *.png *.bmp *.svg *.tiff *.webp);;"
            + translate("ImageInputSettings", "All files")
            + " (*)",
        )

        if os.path.exists(path):
            self.filePath.setText(
                Application().session.rel_path(path)
            )
