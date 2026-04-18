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

from PyQt5.QtCore import QT_TRANSLATE_NOOP, Qt, QTime
from PyQt5.QtGui import QFontDatabase
from PyQt5.QtWidgets import (
    QCheckBox,
    QDateTimeEdit,
    QDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QTextEdit,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)

from lisp.cues.cue import CueAction
from lisp.ui.icons import IconTheme
from lisp.ui.settings.cue_pages.cue_appearance import IconSelectorDialog
from lisp.ui.settings.pages import CueSettingsPage
from lisp.ui.ui_utils import css_to_dict, dict_to_css, translate
from lisp.ui.widgets import (
    CueActionComboBox,
    CueNextActionComboBox,
    ColorButton,
    FadeComboBox,
    FadeEdit,
)


class CueGeneralSettingsPage(CueSettingsPage):
    Name = QT_TRANSLATE_NOOP("SettingsPageName", "General")
    SortOrder = 10
    iconName = "music"

    def __init__(self, cueType, **kwargs):
        super().__init__(cueType=cueType, **kwargs)
        self.iconSelectorDialog = None

        # QLab-style 3-column grid: identity | behaviour | appearance+fade.
        # Each column owns flat group-boxes so existing tests that touch
        # `xxxGroup.isCheckable()`/`isEnabled()` still work, but the chrome
        # disappears so the inspector reads as a single dense form.
        grid = QGridLayout(self)
        grid.setContentsMargins(8, 8, 8, 8)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(6)

        # ---- Column 0: identity --------------------------------------
        self.cueNameGroup = self._makeFlatGroup()
        self.cueNameGroup.setLayout(QHBoxLayout())
        self.cueNameGroup.layout().setContentsMargins(0, 14, 0, 0)

        self.cueIconPreview = QLabel(self.cueNameGroup)
        self.cueNameGroup.layout().addWidget(self.cueIconPreview)

        self.cueIconButton = QPushButton(self.cueNameGroup)
        self.cueIconButton.clicked.connect(self.showIconSelector)
        self.cueNameGroup.layout().addWidget(self.cueIconButton)

        self.cueNameEdit = QLineEdit(self.cueNameGroup)
        self.cueNameGroup.layout().addWidget(self.cueNameEdit, 1)

        grid.addWidget(self.cueNameGroup, 0, 0)

        self.cueDescriptionGroup = self._makeFlatGroup()
        self.cueDescriptionGroup.setLayout(QHBoxLayout())
        self.cueDescriptionGroup.layout().setContentsMargins(0, 14, 0, 0)
        self.cueDescriptionGroup.setSizePolicy(
            QSizePolicy.Expanding, QSizePolicy.Expanding
        )

        self.cueDescriptionEdit = QTextEdit(self.cueDescriptionGroup)
        self.cueDescriptionEdit.setAcceptRichText(False)
        self.cueDescriptionEdit.setFont(
            QFontDatabase.systemFont(QFontDatabase.FixedFont)
        )
        self.cueDescriptionGroup.layout().addWidget(self.cueDescriptionEdit)

        # Description fills column 0 from row 1 to the bottom of the grid.
        grid.addWidget(self.cueDescriptionGroup, 1, 0, -1, 1)

        # ---- Column 1: behaviour -------------------------------------
        self.startActionGroup = self._makeFlatGroup()
        self.startActionGroup.setLayout(QHBoxLayout())
        self.startActionGroup.layout().setContentsMargins(0, 14, 0, 0)

        self.startActionCombo = CueActionComboBox(
            {CueAction.Start, CueAction.FadeInStart}.intersection(
                self.cueType.CueActions
            ).union({CueAction.DoNothing}),
            mode=CueActionComboBox.Mode.Value,
            parent=self.startActionGroup,
        )
        self.startActionCombo.setEnabled(self.startActionCombo.count() > 1)
        self.startActionGroup.layout().addWidget(self.startActionCombo)

        self.startActionLabel = QLabel(self.startActionGroup)
        self.startActionLabel.setAlignment(Qt.AlignCenter)
        self.startActionGroup.layout().addWidget(self.startActionLabel, 1)

        grid.addWidget(self.startActionGroup, 0, 1)

        self.stopActionGroup = self._makeFlatGroup()
        self.stopActionGroup.setLayout(QHBoxLayout())
        self.stopActionGroup.layout().setContentsMargins(0, 14, 0, 0)

        self.stopActionCombo = CueActionComboBox(
            {
                CueAction.Stop,
                CueAction.Pause,
                CueAction.FadeOutStop,
                CueAction.FadeOutPause,
                CueAction.LoopRelease,
            }.intersection(self.cueType.CueActions).union(
                {CueAction.DoNothing}
            ),
            mode=CueActionComboBox.Mode.Value,
            parent=self.stopActionGroup,
        )
        self.stopActionCombo.setEnabled(self.stopActionCombo.count() > 1)
        self.stopActionGroup.layout().addWidget(self.stopActionCombo)

        self.stopActionLabel = QLabel(self.stopActionGroup)
        self.stopActionLabel.setAlignment(Qt.AlignCenter)
        self.stopActionGroup.layout().addWidget(self.stopActionLabel, 1)

        grid.addWidget(self.stopActionGroup, 1, 1)

        # Spacer keeps behaviour rows pinned to the top of column 1 so
        # they stay aligned with column 0/2 above the column-1 stretch.
        grid.setRowStretch(2, 1)

        # ---- Column 2: appearance + fade + exclusive -----------------
        self.colorGroup = self._makeFlatGroup()
        self.colorGroup.setLayout(QHBoxLayout())
        self.colorGroup.layout().setContentsMargins(0, 14, 0, 0)

        self.colorBButton = ColorButton(self.colorGroup)
        self.colorFButton = ColorButton(self.colorGroup)
        self.colorGroup.layout().addWidget(self.colorBButton)
        self.colorGroup.layout().addWidget(self.colorFButton)

        grid.addWidget(self.colorGroup, 0, 2)

        self.fontSizeGroup = self._makeFlatGroup()
        self.fontSizeGroup.setLayout(QHBoxLayout())
        self.fontSizeGroup.layout().setContentsMargins(0, 14, 0, 0)

        self.fontSizeSpin = QSpinBox(self.fontSizeGroup)
        self.fontSizeSpin.setValue(QLabel().fontInfo().pointSize())
        self.fontSizeGroup.layout().addWidget(self.fontSizeSpin)
        self.fontSizeGroup.layout().addStretch(1)

        grid.addWidget(self.fontSizeGroup, 1, 2)

        # Warning sits between the appearance pair and the fade trio so
        # it stays visually attached to the colour/font controls it
        # qualifies, not the fade controls below it.
        self.warning = QLabel(self)
        self.warning.setAlignment(Qt.AlignCenter)
        self.warning.setWordWrap(True)
        self.warning.setStyleSheet("color: #FFA500; font-weight: bold")
        grid.addWidget(self.warning, 2, 2)

        self.fadeInGroup = self._makeFlatGroup()
        self.fadeInGroup.setEnabled(CueAction.FadeInStart in cueType.CueActions)
        self.fadeInGroup.setLayout(QHBoxLayout())
        self.fadeInGroup.layout().setContentsMargins(0, 14, 0, 0)

        self.fadeInEdit = FadeEdit(
            self.fadeInGroup, mode=FadeComboBox.Mode.FadeIn
        )
        self.fadeInGroup.layout().addWidget(self.fadeInEdit)

        grid.addWidget(self.fadeInGroup, 3, 2)

        self.fadeOutGroup = self._makeFlatGroup()
        self.fadeOutGroup.setEnabled(
            CueAction.FadeOutPause in cueType.CueActions
            or CueAction.FadeOutStop in cueType.CueActions
        )
        self.fadeOutGroup.setLayout(QHBoxLayout())
        self.fadeOutGroup.layout().setContentsMargins(0, 14, 0, 0)

        self.fadeOutEdit = FadeEdit(
            self.fadeOutGroup, mode=FadeComboBox.Mode.FadeOut
        )
        self.fadeOutGroup.layout().addWidget(self.fadeOutEdit)

        grid.addWidget(self.fadeOutGroup, 4, 2)

        self.exclusiveGroup = self._makeFlatGroup()
        self.exclusiveGroup.setLayout(QVBoxLayout())
        self.exclusiveGroup.layout().setContentsMargins(0, 14, 0, 0)

        self.exclusiveCheckBox = QCheckBox(self.exclusiveGroup)
        self.exclusiveGroup.layout().addWidget(self.exclusiveCheckBox)

        grid.addWidget(self.exclusiveGroup, 5, 2)

        # Even the three columns; col 0 (identity) gets a touch more
        # because the description editor benefits from the extra width.
        grid.setColumnStretch(0, 3)
        grid.setColumnStretch(1, 2)
        grid.setColumnStretch(2, 2)

        self.retranslateUi()

    @staticmethod
    def _makeFlatGroup():
        """Create a borderless QGroupBox so titles still render but the
        chrome disappears — the page reads like a flat form while the
        opt-in checkable mechanic used for multi-edit keeps working."""
        group = QGroupBox()
        group.setFlat(True)
        group.setStyleSheet(
            "QGroupBox { border: 0; margin-top: 14px; padding: 0; }"
            "QGroupBox::title { subcontrol-origin: margin;"
            " subcontrol-position: top left; padding: 0; }"
        )
        return group

    def retranslateUi(self):
        self.cueNameGroup.setTitle(
            translate("CueAppearanceSettings", "Cue Name and Icon")
        )
        self.cueNameEdit.setText(translate("CueAppearanceSettings", "NoName"))
        self.cueIconButton.setText(
            translate("CueAppearanceSettings", "Change icon")
        )
        self.cueDescriptionGroup.setTitle(
            translate("CueAppearanceSettings", "Description/Note")
        )
        self.colorGroup.setTitle(translate("CueAppearanceSettings", "Color"))
        self.colorBButton.setText(
            translate("CueAppearanceSettings", "Select background color")
        )
        self.colorFButton.setText(
            translate("CueAppearanceSettings", "Select font color")
        )
        self.fontSizeGroup.setTitle(
            translate("CueAppearanceSettings", "Set Font Size")
        )
        self.warning.setText(
            translate(
                "CueAppearanceSettings", "The appearance depends on the layout"
            )
        )
        self.startActionGroup.setTitle(
            translate("CueSettings", "Start action")
        )
        self.startActionLabel.setText(
            translate("CueSettings", "Default action to start the cue")
        )
        self.stopActionGroup.setTitle(translate("CueSettings", "Stop action"))
        self.stopActionLabel.setText(
            translate("CueSettings", "Default action to stop the cue")
        )
        self.fadeInGroup.setTitle(translate("FadeSettings", "Fade In"))
        self.fadeOutGroup.setTitle(translate("FadeSettings", "Fade Out"))
        self.exclusiveGroup.setTitle(translate("CueSettings", "Exclusive"))
        self.exclusiveCheckBox.setText(
            translate(
                "CueSettings",
                "While playing, prevent other cues from starting",
            )
        )

    def showIconSelector(self):
        if self.iconSelectorDialog is None:
            self.iconSelectorDialog = IconSelectorDialog(self)

        self.iconSelectorDialog.setSelectedIcon(self.iconName)

        if self.iconSelectorDialog.exec() == QDialog.Accepted:
            self.iconName = self.iconSelectorDialog.getSelectedIcon("led")
            self.updateIconPreview()

    def updateIconPreview(self):
        self.cueIconPreview.setPixmap(
            IconTheme.get(self.iconName).pixmap(20, 20)
        )

    def enableCheck(self, enabled):
        self.setGroupEnabled(self.cueNameGroup, enabled)
        self.setGroupEnabled(self.cueDescriptionGroup, enabled)
        self.setGroupEnabled(self.colorGroup, enabled)
        self.setGroupEnabled(self.fontSizeGroup, enabled)
        self.setGroupEnabled(self.startActionGroup, enabled)
        self.setGroupEnabled(self.stopActionGroup, enabled)
        self.setGroupEnabled(self.fadeInGroup, enabled)
        self.setGroupEnabled(self.fadeOutGroup, enabled)
        self.setGroupEnabled(self.exclusiveGroup, enabled)

    def loadSettings(self, settings):
        if "name" in settings:
            self.cueNameEdit.setText(settings["name"])
        if "icon" in settings:
            self.iconName = settings["icon"]
            self.updateIconPreview()
        if "description" in settings:
            self.cueDescriptionEdit.setPlainText(settings["description"])
        if "stylesheet" in settings:
            style = css_to_dict(settings["stylesheet"])
            if "background" in style:
                self.colorBButton.setColor(style["background"])
            if "color" in style:
                self.colorFButton.setColor(style["color"])
            if "font-size" in style:
                # [:-2] strips the trailing "pt"
                self.fontSizeSpin.setValue(int(style["font-size"][:-2]))

        self.startActionCombo.setCurrentItem(
            settings.get("default_start_action", "")
        )
        self.stopActionCombo.setCurrentItem(
            settings.get("default_stop_action", "")
        )

        self.fadeInEdit.setFadeType(settings.get("fadein_type", ""))
        self.fadeInEdit.setDuration(settings.get("fadein_duration", 0))
        self.fadeOutEdit.setFadeType(settings.get("fadeout_type", ""))
        self.fadeOutEdit.setDuration(settings.get("fadeout_duration", 0))

        self.exclusiveCheckBox.setChecked(settings.get("exclusive", False))

    def getSettings(self):
        settings = {}
        style = {}

        if self.isGroupEnabled(self.cueNameGroup):
            settings["name"] = self.cueNameEdit.text()
            settings["icon"] = self.iconName
        if self.isGroupEnabled(self.cueDescriptionGroup):
            settings["description"] = self.cueDescriptionEdit.toPlainText()
        if self.isGroupEnabled(self.colorGroup):
            if self.colorBButton.color() is not None:
                style["background"] = self.colorBButton.color()
            if self.colorFButton.color() is not None:
                style["color"] = self.colorFButton.color()
        if self.isGroupEnabled(self.fontSizeGroup):
            style["font-size"] = str(self.fontSizeSpin.value()) + "pt"

        if style:
            settings["stylesheet"] = dict_to_css(style)

        if (
            self.isGroupEnabled(self.startActionGroup)
            and self.startActionCombo.isEnabled()
        ):
            settings["default_start_action"] = (
                self.startActionCombo.currentItem()
            )
        if (
            self.isGroupEnabled(self.stopActionGroup)
            and self.stopActionCombo.isEnabled()
        ):
            settings["default_stop_action"] = (
                self.stopActionCombo.currentItem()
            )

        if self.isGroupEnabled(self.fadeInGroup):
            settings["fadein_type"] = self.fadeInEdit.fadeType()
            settings["fadein_duration"] = self.fadeInEdit.duration()
        if self.isGroupEnabled(self.fadeOutGroup):
            settings["fadeout_type"] = self.fadeOutEdit.fadeType()
            settings["fadeout_duration"] = self.fadeOutEdit.duration()

        if self.isGroupEnabled(self.exclusiveGroup):
            settings["exclusive"] = self.exclusiveCheckBox.isChecked()

        return settings


class CueTimingPage(CueSettingsPage):
    Name = QT_TRANSLATE_NOOP("SettingsPageName", "Timing")
    SortOrder = 20

    def __init__(self, cueType, **kwargs):
        super().__init__(cueType=cueType, **kwargs)
        self.setLayout(QVBoxLayout())

        # Pre wait
        self.preWaitGroup = QGroupBox(self)
        self.preWaitGroup.setLayout(QHBoxLayout())
        self.layout().addWidget(self.preWaitGroup)

        self.preWaitEdit = QTimeEdit(self.preWaitGroup)
        self.preWaitEdit.setDisplayFormat("HH:mm:ss.zzz")
        self.preWaitEdit.setCurrentSection(QDateTimeEdit.SecondSection)
        self.preWaitGroup.layout().addWidget(self.preWaitEdit)

        self.preWaitLabel = QLabel(self.preWaitGroup)
        self.preWaitLabel.setAlignment(Qt.AlignCenter)
        self.preWaitGroup.layout().addWidget(self.preWaitLabel)

        # Post wait
        self.postWaitGroup = QGroupBox(self)
        self.postWaitGroup.setLayout(QHBoxLayout())
        self.layout().addWidget(self.postWaitGroup)

        self.postWaitEdit = QTimeEdit(self.postWaitGroup)
        self.postWaitEdit.setDisplayFormat("HH:mm:ss.zzz")
        self.postWaitEdit.setCurrentSection(QDateTimeEdit.SecondSection)
        self.postWaitGroup.layout().addWidget(self.postWaitEdit)

        self.postWaitLabel = QLabel(self.postWaitGroup)
        self.postWaitLabel.setAlignment(Qt.AlignCenter)
        self.postWaitGroup.layout().addWidget(self.postWaitLabel)

        # Next action
        self.nextActionGroup = QGroupBox(self)
        self.nextActionGroup.setLayout(QHBoxLayout())
        self.layout().addWidget(self.nextActionGroup)

        self.nextActionCombo = CueNextActionComboBox(
            parent=self.nextActionGroup
        )
        self.nextActionGroup.layout().addWidget(self.nextActionCombo)

        self.layout().addStretch()

        self.retranslateUi()

    def retranslateUi(self):
        self.preWaitGroup.setTitle(translate("CueSettings", "Pre wait"))
        self.preWaitLabel.setText(
            translate("CueSettings", "Wait before cue execution")
        )
        self.postWaitGroup.setTitle(translate("CueSettings", "Post wait"))
        self.postWaitLabel.setText(
            translate("CueSettings", "Wait after cue execution")
        )
        self.nextActionGroup.setTitle(translate("CueSettings", "Next action"))

    def enableCheck(self, enabled):
        self.setGroupEnabled(self.preWaitGroup, enabled)
        self.setGroupEnabled(self.postWaitGroup, enabled)
        self.setGroupEnabled(self.nextActionGroup, enabled)

    def loadSettings(self, settings):
        preWaitMilliseconds = int(round(settings.get("pre_wait", 0) * 1000))
        self.preWaitEdit.setTime(QTime(0, 0).addMSecs(preWaitMilliseconds))
        postWaitMilliseconds = int(round(settings.get("post_wait", 0) * 1000))
        self.postWaitEdit.setTime(QTime(0, 0).addMSecs(postWaitMilliseconds))
        self.nextActionCombo.setCurrentAction(settings.get("next_action", ""))

    def getSettings(self):
        settings = {}

        if self.isGroupEnabled(self.preWaitGroup):
            preWaitMs = self.preWaitEdit.time().msecsSinceStartOfDay()
            settings["pre_wait"] = round(preWaitMs / 1000, 3)
        if self.isGroupEnabled(self.postWaitGroup):
            postWaitMs = self.postWaitEdit.time().msecsSinceStartOfDay()
            settings["post_wait"] = round(postWaitMs / 1000, 3)
        if self.isGroupEnabled(self.nextActionGroup):
            settings["next_action"] = self.nextActionCombo.currentData()

        return settings
