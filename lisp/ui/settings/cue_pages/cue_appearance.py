# This file is part of Linux Show Player
#
# Copyright 2016 Francesco Ceruti <ceppofrancy@gmail.com>
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

from PyQt5.QtCore import Qt, QSize
from PyQt5.QtGui import QStandardItemModel, QStandardItem
from PyQt5.QtWidgets import (
    QVBoxLayout,
    QDialog,
    QDialogButtonBox,
    QListWidget,
    QListView,
    QStyledItemDelegate,
    QStyleOptionViewItem,
)

from lisp.ui.ui_utils import translate
from lisp.ui.icons import IconTheme
from lisp import ICON_THEMES_DIR


class IconSelectorDialog(QDialog):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setWindowModality(Qt.ApplicationModal)
        self.setLayout(QVBoxLayout())

        self.iconsModel = QStandardItemModel()
        self.iconsList = QListView(self)
        self.iconsList.setModel(self.iconsModel)
        self.iconsList.setItemDelegate(IconOnlyDelegate())
        self.iconsList.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        self.iconsList.setFixedWidth(350)
        self.iconsList.setMinimumHeight(350)
        self.iconsList.setViewMode(QListWidget.IconMode)
        self.iconsList.setResizeMode(QListWidget.Adjust)
        self.iconsList.setFlow(QListWidget.LeftToRight)
        self.iconsList.setUniformItemSizes(True)
        self.iconsList.setWrapping(True)
        self.iconsList.setIconSize(QSize(48, 48))
        self.iconsList.setSpacing(10)
        self.iconsList.activated.connect(self.accept)
        self.iconsList.clicked.connect(self.accept)
        self.layout().addWidget(self.iconsList)

        self.buttons = QDialogButtonBox(QDialogButtonBox.Cancel, self)
        self.buttons.rejected.connect(self.reject)
        self.layout().addWidget(self.buttons)

        for name in self.fetchIcons():
            item = QStandardItem()
            item.setData(name, Qt.UserRole)
            item.setIcon(IconTheme.get(name))

            self.iconsModel.appendRow(item)

        self.retranslateUi()

    def retranslateUi(self):
        self.setWindowTitle(
            translate("CueAppearanceSettings", "Select an Icon")
        )

    def fetchIcons(self):
        icons = set()

        for item in os.scandir(os.path.join(ICON_THEMES_DIR, "lisp/cues")):
            if item.is_file():
                name, _ = os.path.splitext(item.name)
                icons.add(name)

        return sorted(icons)

    def getSelectedIcon(self, fallback=None):
        if self.iconsList.currentIndex().isValid():
            return self.iconsModel.data(
                self.iconsList.currentIndex(), Qt.UserRole
            )

        return fallback

    def setSelectedIcon(self, name):
        for row in range(self.iconsModel.rowCount()):
            item = self.iconsModel.item(row)
            if item.data(Qt.UserRole) == name:
                self.iconsList.setCurrentIndex(item.index())


class IconOnlyDelegate(QStyledItemDelegate):
    def initStyleOption(self, option, index):
        super().initStyleOption(option, index)

        option.features &= ~QStyleOptionViewItem.HasDisplay
