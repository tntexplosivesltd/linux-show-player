# This file is part of Linux Show Player
#
# Copyright 2018 Francesco Ceruti <ceppofrancy@gmail.com>
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

from PyQt5.QtCore import QT_TRANSLATE_NOOP, Qt
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QSizePolicy,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from lisp.application import Application
from lisp.core.properties import Property
from lisp.cues.cue import Cue, CueAction
from lisp.cues.targeting import TargetingCue
from lisp.ui.cuelistdialog import CueSelectDialog
from lisp.ui.icons import IconTheme
from lisp.ui.qdelegates import CueActionDelegate, CueSelectionDelegate
from lisp.ui.qmodels import CueClassRole, SimpleCueListModel
from lisp.ui.settings.cue_settings import CueSettingsRegistry
from lisp.ui.settings.pages import SettingsPage
from lisp.ui.ui_utils import translate


class CollectionCue(TargetingCue, Cue):
    Name = QT_TRANSLATE_NOOP("CueName", "Collection Cue")
    Category = QT_TRANSLATE_NOOP("CueCategory", "Action cues")

    CueActions = (
        CueAction.Default,
        CueAction.Start,
        CueAction.Stop,
        CueAction.Pause,
        CueAction.Resume,
        CueAction.Interrupt,
    )

    targets = Property(default=[])
    icon = Property("collection")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = translate("CueName", self.Name)
        self.changed("targets").connect(self._recheck_target)
        self._recheck_target()

    def _resolve_targets(self) -> bool:
        targets = getattr(self, "targets", None)
        if not targets:
            return False
        model = self.app.cue_model
        return all(
            tid and model.get(tid) is not None
            for tid, _action in targets
        )

    def _on_model_change(self, cue):
        # The base-class guard checks `cue.id == self.target_id`, but
        # CollectionCue has no scalar `target_id` — it keeps a list.
        # Always recheck so that removing any target in the list flips
        # `invalid_target` from False to True without a round-trip
        # through an already-invalid state.
        self._recheck_target()

    def __start__(self, fade=False):
        for target_id, action in self.targets:
            cue = self.app.cue_model.get(target_id)
            if cue is not self:
                cue.execute(action=CueAction[action])

        return False


class CollectionCueSettings(SettingsPage):
    Name = QT_TRANSLATE_NOOP("SettingsPageName", "Edit Collection")
    SortOrder = 30

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._dropped_target_count = 0
        self.setLayout(QVBoxLayout(self))

        self.cueDialog = CueSelectDialog(
            cues=Application().cue_model,
            selection_mode=QAbstractItemView.ExtendedSelection,
        )
        self.collectionModel = CollectionModel()

        self.collectionGroup = QGroupBox(self)
        self.collectionGroup.setLayout(QVBoxLayout())
        self.layout().addWidget(self.collectionGroup)

        self.collectionView = CollectionView(
            Application().cue_model, self.cueDialog, parent=self.collectionGroup
        )
        self.collectionView.setModel(self.collectionModel)
        self.collectionView.setAlternatingRowColors(True)
        self.collectionGroup.layout().addWidget(self.collectionView)

        # Buttons
        self.dialogButtons = QDialogButtonBox(self.collectionGroup)
        self.dialogButtons.setSizePolicy(
            QSizePolicy.Minimum, QSizePolicy.Minimum
        )
        self.collectionGroup.layout().addWidget(self.dialogButtons)

        # Invalid-target summary row. Visible iff the table is empty
        # OR the most recent loadSettings dropped any rows because their
        # targets no longer exist.
        self.targetWarning = QWidget(self.collectionGroup)
        warningLayout = QHBoxLayout(self.targetWarning)
        warningLayout.setContentsMargins(0, 2, 0, 0)
        warningLayout.setSpacing(6)
        self._targetWarningIcon = QLabel(self.targetWarning)
        self._targetWarningIcon.setPixmap(
            IconTheme.get("dialog-warning").pixmap(16, 16)
        )
        self._targetWarningText = QLabel(self.targetWarning)
        warningLayout.addWidget(self._targetWarningIcon)
        warningLayout.addWidget(self._targetWarningText, stretch=1)
        self.targetWarning.setVisible(False)
        self.collectionGroup.layout().addWidget(self.targetWarning)

        self.addButton = QPushButton(self.dialogButtons)
        self.dialogButtons.addButton(
            self.addButton, QDialogButtonBox.ActionRole
        )
        self.addButton.clicked.connect(self._showAddCueDialog)

        self.delButton = QPushButton(self.dialogButtons)
        self.delButton.setEnabled(False)
        self.dialogButtons.addButton(
            self.delButton, QDialogButtonBox.ActionRole
        )
        self.delButton.clicked.connect(self._removeCurrentCue)

        self.retranslateUi()
        self._refresh_target_warning()

    def retranslateUi(self):
        self.collectionGroup.setTitle(
            translate("SettingsPageName", "Edit Collection")
        )
        self.addButton.setText(translate("CollectionCue", "Add"))
        self.delButton.setText(translate("CollectionCue", "Remove"))

    def enableCheck(self, enabled):
        self.setGroupEnabled(self.collectionGroup, enabled)

    def loadSettings(self, settings):
        # Re-callable: the inspector reloads settings on every external
        # refresh, so the model and the cue-select dialog must be reset
        # to a known baseline before re-adding the configured targets
        # (otherwise targets accumulate and remove_cue raises KeyError).
        self.collectionModel.reset()
        self.cueDialog.reset()
        self.cueDialog.add_cues(Application().cue_model)
        self.delButton.setEnabled(False)
        self._dropped_target_count = 0

        for target_id, action in settings.get("targets", []):
            target = Application().cue_model.get(target_id)
            if target is not None:
                self._addCue(target, CueAction(action))
            else:
                self._dropped_target_count += 1

        self._refresh_target_warning()

    def getSettings(self):
        if self.isGroupEnabled(self.collectionGroup):
            targets = []
            for target_id, action in self.collectionModel.rows:
                targets.append((target_id, action.value))

            return {"targets": targets}

        return {}

    def _addCue(self, cue, action):
        self.collectionModel.appendRow(cue.__class__, cue.id, action)
        self.cueDialog.remove_cue(cue)
        self.delButton.setEnabled(True)
        self._refresh_target_warning()

    def _showAddCueDialog(self):
        if self.cueDialog.exec() == QDialog.Accepted:
            for target in self.cueDialog.selected_cues():
                self._addCue(target, target.CueActions[0])

    def _removeCurrentCue(self):
        row = self.collectionView.currentIndex().row()

        if row >= 0:
            cueId = self.collectionModel.rows[row][0]

            self.collectionModel.removeRow(row)
            self.cueDialog.add_cue(Application().cue_model.get(cueId))

        self.delButton.setEnabled(self.collectionModel.rowCount() > 0)
        self._refresh_target_warning()

    def _refresh_target_warning(self):
        """Refresh the summary warning under the table.

        Two distinct conditions are surfaced (priority: dropped > empty):
        - dropped: loadSettings silently removed N rows because their
          targets no longer exist. Show "N invalid target(s) — saved
          cue references cues that no longer exist; they'll be removed
          when you save."
        - empty: the table has zero rows. Show "Collection is empty."
        """
        if self._dropped_target_count > 0:
            self._targetWarningText.setText(
                translate(
                    "CollectionCue",
                    "{n} invalid target(s) — saved cue references "
                    "cues that no longer exist; they'll be removed "
                    "when you save.",
                ).format(n=self._dropped_target_count)
            )
            self.targetWarning.setVisible(True)
            return
        if self.collectionModel.rowCount() == 0:
            self._targetWarningText.setText(
                translate("CollectionCue", "Collection is empty.")
            )
            self.targetWarning.setVisible(True)
            return
        self.targetWarning.setVisible(False)


class CollectionView(QTableView):
    def __init__(self, cueModel, cueSelect, **kwargs):
        super().__init__(**kwargs)

        self.setSelectionBehavior(QTableView.SelectRows)
        self.setSelectionMode(QTableView.SingleSelection)

        self.setShowGrid(False)
        self.setAlternatingRowColors(True)

        self.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.horizontalHeader().setHighlightSections(False)

        self.verticalHeader().sectionResizeMode(QHeaderView.Fixed)
        self.verticalHeader().setDefaultSectionSize(26)
        self.verticalHeader().setHighlightSections(False)

        self.delegates = [
            CueSelectionDelegate(cueModel, cueSelect),
            CueActionDelegate(),
        ]

        for column, delegate in enumerate(self.delegates):
            self.setItemDelegateForColumn(column, delegate)


class CollectionModel(SimpleCueListModel):
    def __init__(self):
        # NOTE: The model does fixed-indices operations based on this list
        super().__init__(
            [
                translate("CollectionCue", "Cue"),
                translate("CollectionCue", "Action"),
            ]
        )

    def setData(self, index, value, role=Qt.DisplayRole):
        result = super().setData(index, value, role)

        if result and role == CueClassRole:
            if self.rows[index.row()][1] not in value.CueActions:
                self.rows[index.row()][1] = value.CueActions[0]
                self.dataChanged.emit(
                    self.index(index.row(), 1),
                    self.index(index.row(), 1),
                    [Qt.DisplayRole, Qt.EditRole],
                )

        return result


CueSettingsRegistry().add(CollectionCueSettings, CollectionCue)
