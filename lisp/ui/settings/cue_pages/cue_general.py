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

from PyQt5.QtCore import QT_TRANSLATE_NOOP, Qt, QSize, QTime
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
    FadeComboBox,
    FadeEdit,
)
from lisp.ui.widgets.cue_color_palette import CueColorPalette


def make_flat_group():
    """Borderless QGroupBox: title still renders but the chrome
    disappears. Pages read like a flat form while the opt-in checkable
    mechanic used for multi-edit (setCheckable in setGroupEnabled) keeps
    working — checking the box still hatches the title row."""
    group = QGroupBox()
    group.setFlat(True)
    group.setStyleSheet(
        "QGroupBox { border: 0; margin-top: 1.1em; padding: 0; }"
        "QGroupBox::title { subcontrol-origin: margin;"
        " subcontrol-position: top left; padding: 0; }"
    )
    return group


class CueGeneralSettingsPage(CueSettingsPage):
    Name = QT_TRANSLATE_NOOP("SettingsPageName", "General")
    SortOrder = 10
    iconName = "music"

    def __init__(self, cueType, **kwargs):
        super().__init__(cueType=cueType, **kwargs)
        self.iconSelectorDialog = None

        # QLab-style 3-column grid: behaviour+fade | identity | appearance.
        # Each column owns flat group-boxes so existing tests that touch
        # `xxxGroup.isCheckable()`/`isEnabled()` still work, but the chrome
        # disappears so the inspector reads as a single dense form.
        grid = QGridLayout(self)
        grid.setContentsMargins(8, 4, 8, 4)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(2)

        # ---- Column 0: behaviour + fade ------------------------------
        self.startActionGroup = make_flat_group()
        self.startActionGroup.setLayout(QHBoxLayout())
        self.startActionGroup.layout().setContentsMargins(0, 0, 0, 0)

        self.startActionCombo = CueActionComboBox(
            {CueAction.Start, CueAction.FadeInStart}.intersection(
                self.cueType.CueActions
            ).union({CueAction.DoNothing}),
            mode=CueActionComboBox.Mode.Value,
            parent=self.startActionGroup,
        )
        self.startActionCombo.setEnabled(self.startActionCombo.count() > 1)
        self.startActionGroup.layout().addWidget(self.startActionCombo)

        grid.addWidget(self.startActionGroup, 0, 0)

        self.stopActionGroup = make_flat_group()
        self.stopActionGroup.setLayout(QHBoxLayout())
        self.stopActionGroup.layout().setContentsMargins(0, 0, 0, 0)

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

        grid.addWidget(self.stopActionGroup, 1, 0)

        self.fadeInGroup = make_flat_group()
        self.fadeInGroup.setEnabled(CueAction.FadeInStart in cueType.CueActions)
        self.fadeInGroup.setLayout(QHBoxLayout())
        self.fadeInGroup.layout().setContentsMargins(0, 0, 0, 0)

        self.fadeInEdit = FadeEdit(
            self.fadeInGroup, mode=FadeComboBox.Mode.FadeIn
        )
        self._stripDurationLabel(self.fadeInEdit)
        self.fadeInGroup.layout().addWidget(self.fadeInEdit)

        grid.addWidget(self.fadeInGroup, 2, 0)

        self.fadeOutGroup = make_flat_group()
        self.fadeOutGroup.setEnabled(
            CueAction.FadeOutPause in cueType.CueActions
            or CueAction.FadeOutStop in cueType.CueActions
        )
        self.fadeOutGroup.setLayout(QHBoxLayout())
        self.fadeOutGroup.layout().setContentsMargins(0, 0, 0, 0)

        self.fadeOutEdit = FadeEdit(
            self.fadeOutGroup, mode=FadeComboBox.Mode.FadeOut
        )
        self._stripDurationLabel(self.fadeOutEdit)
        self.fadeOutGroup.layout().addWidget(self.fadeOutEdit)

        grid.addWidget(self.fadeOutGroup, 3, 0)

        # ---- Column 1: identity --------------------------------------
        # Cue number sits in its own flat group. It's hidden entirely
        # in multi-edit mode (see enableCheck) — applying one value to
        # several cues would break the uniqueness invariant.
        self.cueNumberGroup = make_flat_group()
        self.cueNumberGroup.setLayout(QHBoxLayout())
        self.cueNumberGroup.layout().setContentsMargins(0, 0, 0, 0)

        self.cueNumberEdit = QLineEdit(self.cueNumberGroup)
        self.cueNumberEdit.setMaximumWidth(80)
        self.cueNumberEdit.editingFinished.connect(
            self.__validateCueNumberUnique
        )
        self.cueNumberGroup.layout().addWidget(self.cueNumberEdit)
        # Captured during loadSettings; the validator uses it to revert
        # to the previously-loaded value when a collision is detected.
        self._loadedCueNumber = ""

        self.cueNameGroup = make_flat_group()
        self.cueNameGroup.setLayout(QHBoxLayout())
        self.cueNameGroup.layout().setContentsMargins(0, 0, 0, 0)

        # The button itself shows the current icon — clicking it opens
        # the picker. A separate preview label would be redundant since
        # the icon-bearing button already tells the user "this is your
        # icon, and you can change it."
        self.cueIconButton = QPushButton(self.cueNameGroup)
        self.cueIconButton.setIconSize(QSize(20, 20))
        self.cueIconButton.setToolTip(
            translate("CueAppearanceSettings", "Change icon")
        )
        self.cueIconButton.clicked.connect(self.showIconSelector)
        self.cueNameGroup.layout().addWidget(self.cueIconButton)

        self.cueNameEdit = QLineEdit(self.cueNameGroup)
        self.cueNameGroup.layout().addWidget(self.cueNameEdit, 1)

        # Wrap Q# + Name on a single inspector row so they read as one
        # identity strip ("Q1  ♫  My Cue") rather than two stacked
        # fields. Each group keeps its own checkable enable for
        # multi-edit.
        identityRow = QWidget()
        identityLayout = QHBoxLayout(identityRow)
        identityLayout.setContentsMargins(0, 0, 0, 0)
        identityLayout.setSpacing(8)
        identityLayout.addWidget(self.cueNumberGroup)
        identityLayout.addWidget(self.cueNameGroup, 1)

        grid.addWidget(identityRow, 0, 1)

        self.cueDescriptionGroup = make_flat_group()
        self.cueDescriptionGroup.setLayout(QHBoxLayout())
        self.cueDescriptionGroup.layout().setContentsMargins(0, 0, 0, 0)
        self.cueDescriptionGroup.setSizePolicy(
            QSizePolicy.Expanding, QSizePolicy.Expanding
        )

        self.cueDescriptionEdit = QTextEdit(self.cueDescriptionGroup)
        self.cueDescriptionEdit.setAcceptRichText(False)
        self.cueDescriptionEdit.setFont(
            QFontDatabase.systemFont(QFontDatabase.FixedFont)
        )
        self.cueDescriptionGroup.layout().addWidget(self.cueDescriptionEdit)

        # Description fills column 1 from row 1 to the bottom of the grid,
        # matching the height of column 0's behaviour+fade stack.
        grid.addWidget(self.cueDescriptionGroup, 1, 1, -1, 1)

        # ---- Column 2: appearance + exclusive ------------------------
        self.colorGroup = make_flat_group()
        self.colorGroup.setLayout(QHBoxLayout())
        self.colorGroup.layout().setContentsMargins(0, 0, 0, 0)

        # QLab-style fixed palette replaces the old free-form
        # QColorDialog. Foreground colour is gone — the palette only
        # owns background, and any legacy ``color:`` key on a session's
        # stylesheet drops on the next save.
        self.colorPalette = CueColorPalette(self.colorGroup)
        self.colorGroup.layout().addWidget(self.colorPalette)

        grid.addWidget(self.colorGroup, 0, 2)

        self.fontSizeGroup = make_flat_group()
        self.fontSizeGroup.setLayout(QHBoxLayout())
        self.fontSizeGroup.layout().setContentsMargins(0, 0, 0, 0)

        self.fontSizeSpin = QSpinBox(self.fontSizeGroup)
        # QSpinBox defaults to [0, 99]; 0pt fonts render as invisible
        # labels and a corrupted session could round-trip one.
        self.fontSizeSpin.setMinimum(6)
        self.fontSizeSpin.setValue(QLabel().fontInfo().pointSize())
        self.fontSizeGroup.layout().addWidget(self.fontSizeSpin)
        self.fontSizeGroup.layout().addStretch(1)

        grid.addWidget(self.fontSizeGroup, 1, 2)

        # Warning sits beneath the appearance pair so it stays visually
        # attached to the colour/font controls it qualifies.
        self.warning = QLabel(self)
        self.warning.setAlignment(Qt.AlignCenter)
        self.warning.setWordWrap(True)
        self.warning.setStyleSheet("color: #FFA500; font-weight: bold")
        grid.addWidget(self.warning, 2, 2)

        self.exclusiveGroup = make_flat_group()
        self.exclusiveGroup.setLayout(QVBoxLayout())
        self.exclusiveGroup.layout().setContentsMargins(0, 0, 0, 0)

        self.exclusiveCheckBox = QCheckBox(self.exclusiveGroup)
        self.exclusiveGroup.layout().addWidget(self.exclusiveCheckBox)

        grid.addWidget(self.exclusiveGroup, 3, 2)

        # Enabled sits under Exclusive in the appearance column.
        # The stored property is `disabled` (default False); the
        # checkbox is labelled "Enabled" because ticked-means-active
        # reads more naturally in a settings context.
        self.enabledGroup = make_flat_group()
        self.enabledGroup.setLayout(QVBoxLayout())
        self.enabledGroup.layout().setContentsMargins(0, 0, 0, 0)

        self.enabledCheckBox = QCheckBox(self.enabledGroup)
        self.enabledCheckBox.setChecked(True)
        self.enabledGroup.layout().addWidget(self.enabledCheckBox)

        grid.addWidget(self.enabledGroup, 4, 2)

        # Behaviour controls are compact (combos + spinboxes), identity
        # owns the description editor and gets the lion's share, and
        # appearance needs only enough for the 8-slot palette strip —
        # extra width beyond that falls into the palette's trailing
        # stretch as dead space. Col 1's larger share lets the
        # description editor absorb the reclaimed room instead.
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 4)
        grid.setColumnStretch(2, 1)

        self.retranslateUi()

    @staticmethod
    def _stripDurationLabel(fadeEdit):
        """Re-flow a FadeEdit so the duration spinbox and curve combo
        sit side-by-side without their internal captions. The owning
        group title ('Fade In' / 'Fade Out') already names the duration,
        and the curve combo's icons (linear / quadratic glyphs) are
        self-documenting — so 'Duration (sec):' and 'Curve:' are pure
        noise inside the inspector. Both labels are removed from the
        layout and the two controls collapse onto row 0."""
        layout = fadeEdit.layout()
        for label in (fadeEdit.fadeDurationLabel, fadeEdit.fadeTypeLabel):
            layout.removeWidget(label)
            label.hide()
        layout.removeWidget(fadeEdit.fadeDurationSpin)
        layout.removeWidget(fadeEdit.fadeTypeCombo)
        layout.addWidget(fadeEdit.fadeDurationSpin, 0, 0)
        layout.addWidget(fadeEdit.fadeTypeCombo, 0, 1)

    def retranslateUi(self):
        self.cueNumberGroup.setTitle(
            translate("CueAppearanceSettings", "Q#")
        )
        self.cueNumberEdit.setToolTip(
            translate(
                "CueAppearanceSettings",
                "Static cue identifier (e.g. '1', '1.5', 'Pre-1'). "
                "Stable across reorders.",
            )
        )
        self.cueNameGroup.setTitle(
            translate("CueAppearanceSettings", "Cue Name and Icon")
        )
        self.cueNameEdit.setText(translate("CueAppearanceSettings", "NoName"))
        self.cueIconButton.setToolTip(
            translate("CueAppearanceSettings", "Change icon")
        )
        self.cueDescriptionGroup.setTitle(
            translate("CueAppearanceSettings", "Description/Note")
        )
        self.colorGroup.setTitle(translate("CueAppearanceSettings", "Color"))
        self.fontSizeGroup.setTitle(
            translate("CueAppearanceSettings", "Set Font Size")
        )
        self.warning.setText(
            translate(
                "CueAppearanceSettings", "The appearance depends on the layout"
            )
        )
        self.startActionGroup.setTitle(
            translate("CueSettings", "Default Start action")
        )
        self.stopActionGroup.setTitle(
            translate("CueSettings", "Default Stop action")
        )
        self.fadeInGroup.setTitle(translate("FadeSettings", "Fade In"))
        self.fadeOutGroup.setTitle(translate("FadeSettings", "Fade Out"))
        self.exclusiveGroup.setTitle(translate("CueSettings", "Exclusive"))
        self.exclusiveCheckBox.setText(
            translate("CueSettings", "Cue is exclusive")
        )
        self.exclusiveCheckBox.setToolTip(
            translate(
                "CueSettings",
                "While playing, prevent other media cues from starting",
            )
        )
        self.enabledGroup.setTitle(
            translate("CueSettings", "Enabled")
        )
        self.enabledCheckBox.setText(
            translate("CueSettings", "Cue is enabled")
        )
        self.enabledCheckBox.setToolTip(
            translate(
                "CueSettings",
                "When unchecked, the cue is skipped by GO, "
                "auto-follow chains, and group playback.",
            )
        )

    def __validateCueNumberUnique(self):
        """Reject a typed value that collides with another cue.

        Reverts the QLineEdit to its previously-loaded value and
        styles the field briefly to signal the rejection. Empty input
        and "no change" both pass through without touching anything.

        Lazy import of `Application` avoids a circular import — this
        page is constructed at module-load time (via the cue settings
        registry), well before the application singleton exists.
        """
        from lisp.application import Application
        from lisp.cues.cue_number import is_collision

        text = self.cueNumberEdit.text()
        if not text or text == self._loadedCueNumber:
            return

        app = Application()
        if app is None or app.cue_model is None:
            return

        # The cue we're editing isn't directly accessible from the
        # page — we identify "us" by matching cue_number against the
        # value that was loaded into the field. Excluding any cue that
        # currently holds `_loadedCueNumber` covers the common case
        # (single cue with the loaded value); on the rare collision-
        # before-our-edit path, the worst outcome is a false negative
        # which Application's item_added auto-assign would re-resolve.
        for cue in app.cue_model:
            if cue.cue_number == self._loadedCueNumber:
                # Skip; this is (almost certainly) us.
                continue
            if cue.cue_number == text:
                self.cueNumberEdit.setText(self._loadedCueNumber)
                self.cueNumberEdit.setToolTip(
                    translate(
                        "CueAppearanceSettings",
                        "Cue number '{}' is already in use",
                    ).format(text)
                )
                return

        # Accepted — adopt the new value as the baseline so subsequent
        # edits diff against the actually-saved value.
        self._loadedCueNumber = text
        self.cueNumberEdit.setToolTip(
            translate(
                "CueAppearanceSettings",
                "Static cue identifier (e.g. '1', '1.5', 'Pre-1'). "
                "Stable across reorders.",
            )
        )

    def showIconSelector(self):
        if self.iconSelectorDialog is None:
            self.iconSelectorDialog = IconSelectorDialog(self)

        self.iconSelectorDialog.setSelectedIcon(self.iconName)

        if self.iconSelectorDialog.exec() == QDialog.Accepted:
            self.iconName = self.iconSelectorDialog.getSelectedIcon("led")
            self.updateIconPreview()
            # The picker is modal, so the icon button never receives a
            # focus-out — without this nudge the inspector engine would
            # only commit when the user next clicks elsewhere.
            self.commit_requested.emit()

    def updateIconPreview(self):
        self.cueIconButton.setIcon(IconTheme.get(self.iconName))

    def enableCheck(self, enabled):
        # Cue number is intentionally excluded from multi-edit:
        # applying the same value to N cues would create N-1
        # duplicates, violating the per-cue uniqueness invariant. Hide
        # the field so users aren't tempted to tick its group.
        self.cueNumberGroup.setVisible(not enabled)
        self.setGroupEnabled(self.cueNameGroup, enabled)
        self.setGroupEnabled(self.cueDescriptionGroup, enabled)
        self.setGroupEnabled(self.colorGroup, enabled)
        self.setGroupEnabled(self.fontSizeGroup, enabled)
        self.setGroupEnabled(self.startActionGroup, enabled)
        self.setGroupEnabled(self.stopActionGroup, enabled)
        self.setGroupEnabled(self.fadeInGroup, enabled)
        self.setGroupEnabled(self.fadeOutGroup, enabled)
        self.setGroupEnabled(self.exclusiveGroup, enabled)
        self.setGroupEnabled(self.enabledGroup, enabled)

    def loadSettings(self, settings):
        if "cue_number" in settings:
            self._loadedCueNumber = settings["cue_number"] or ""
            self.cueNumberEdit.setText(self._loadedCueNumber)
        if "name" in settings:
            self.cueNameEdit.setText(settings["name"])
        if "icon" in settings:
            self.iconName = settings["icon"]
            self.updateIconPreview()
        if "description" in settings:
            self.cueDescriptionEdit.setPlainText(settings["description"])
        if "stylesheet" in settings:
            style = css_to_dict(settings["stylesheet"])
            # Palette snaps any non-palette hex on load so legacy
            # sessions migrate silently on the very next save. The
            # "color" (foreground) key is deliberately ignored — the
            # palette doesn't own a foreground affordance any more.
            self.colorPalette.setColor(style.get("background", ""))
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
        # Checkbox is "Enabled" (ticked = playable); stored property
        # is `disabled` (inverse). Default False means new cues /
        # legacy sessions load as Enabled.
        self.enabledCheckBox.setChecked(
            not settings.get("disabled", False)
        )

    def getSettings(self):
        settings = {}
        style = {}

        # cue_number is single-edit only: emit it whenever the field
        # is visible (single-cue mode). Multi-edit hides the group via
        # enableCheck, so this branch never fires there — guarding
        # against the uniqueness violation at the source.
        if self.cueNumberGroup.isVisible():
            settings["cue_number"] = self.cueNumberEdit.text()
        if self.isGroupEnabled(self.cueNameGroup):
            settings["name"] = self.cueNameEdit.text()
            settings["icon"] = self.iconName
        if self.isGroupEnabled(self.cueDescriptionGroup):
            settings["description"] = self.cueDescriptionEdit.toPlainText()
        color_enabled = self.isGroupEnabled(self.colorGroup)
        font_enabled = self.isGroupEnabled(self.fontSizeGroup)
        if color_enabled:
            bg = self.colorPalette.color()
            if bg:
                style["background"] = bg
        if font_enabled:
            style["font-size"] = str(self.fontSizeSpin.value()) + "pt"

        # Emit the stylesheet whenever the user has opted in to either
        # appearance group. Gating on ``style`` being non-empty would
        # swallow the "No color" case — style stays empty, yet the
        # user's intent ("clear the background") must still reach the
        # diff engine for UpdateCuesCommand to dispatch.
        if color_enabled or font_enabled:
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

        if self.isGroupEnabled(self.enabledGroup):
            settings["disabled"] = not self.enabledCheckBox.isChecked()

        return settings


class CueTimingPage(CueSettingsPage):
    Name = QT_TRANSLATE_NOOP("SettingsPageName", "Timing")
    SortOrder = 20

    def __init__(self, cueType, **kwargs):
        super().__init__(cueType=cueType, **kwargs)

        # Two-column flat-grid: pre-wait sits beside post-wait (both
        # are HH:mm:ss.zzz time editors and pair naturally), with the
        # next-action combo spanning underneath. Tooltips replace the
        # old "Wait before/after cue execution" sub-labels — the group
        # titles already say what each field does.
        grid = QGridLayout(self)
        grid.setContentsMargins(8, 4, 8, 4)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(2)

        self.preWaitGroup = make_flat_group()
        self.preWaitGroup.setLayout(QHBoxLayout())
        self.preWaitGroup.layout().setContentsMargins(0, 0, 0, 0)

        self.preWaitEdit = QTimeEdit(self.preWaitGroup)
        self.preWaitEdit.setDisplayFormat("HH:mm:ss.zzz")
        self.preWaitEdit.setCurrentSection(QDateTimeEdit.SecondSection)
        self.preWaitGroup.layout().addWidget(self.preWaitEdit)
        grid.addWidget(self.preWaitGroup, 0, 0)

        self.postWaitGroup = make_flat_group()
        self.postWaitGroup.setLayout(QHBoxLayout())
        self.postWaitGroup.layout().setContentsMargins(0, 0, 0, 0)

        self.postWaitEdit = QTimeEdit(self.postWaitGroup)
        self.postWaitEdit.setDisplayFormat("HH:mm:ss.zzz")
        self.postWaitEdit.setCurrentSection(QDateTimeEdit.SecondSection)
        self.postWaitGroup.layout().addWidget(self.postWaitEdit)
        grid.addWidget(self.postWaitGroup, 0, 1)

        self.nextActionGroup = make_flat_group()
        self.nextActionGroup.setLayout(QHBoxLayout())
        self.nextActionGroup.layout().setContentsMargins(0, 0, 0, 0)

        self.nextActionCombo = CueNextActionComboBox(
            parent=self.nextActionGroup
        )
        self.nextActionGroup.layout().addWidget(self.nextActionCombo)
        grid.addWidget(self.nextActionGroup, 1, 0, 1, 2)

        # Push everything to the top so the page doesn't centre-justify
        # its three rows in a tall inspector pane.
        grid.setRowStretch(2, 1)

        self.retranslateUi()

    def retranslateUi(self):
        self.preWaitGroup.setTitle(translate("CueSettings", "Pre wait"))
        self.preWaitEdit.setToolTip(
            translate("CueSettings", "Wait before cue execution")
        )
        self.postWaitGroup.setTitle(translate("CueSettings", "Post wait"))
        self.postWaitEdit.setToolTip(
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
