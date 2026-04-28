# This file is part of Linux Show Player
#
# Copyright 2022 Francesco Ceruti <ceppofrancy@gmail.com>
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

from PyQt5.QtCore import (
    pyqtSignal,
    Qt,
    QDataStream,
    QEvent,
    QIODevice,
    QPoint,
    QRect,
    QT_TRANSLATE_NOOP,
    QTimer,
)
from PyQt5.QtGui import (
    QBrush,
    QColor,
    QContextMenuEvent,
    QKeyEvent,
    QPainter,
    QPen,
)
from PyQt5.QtWidgets import QToolTip, QTreeWidget, QHeaderView, QTreeWidgetItem

from lisp.application import Application
from lisp.core.signal import Connection
from lisp.backend import get_backend
from lisp.command.model import ModelMoveItemsCommand, ModelInsertItemsCommand
from lisp.cues.cue import CueState
from lisp.plugins.action_cues.group_cue import GroupCue
from lisp.core.util import subdict
from lisp.plugins.list_layout.list_widgets import (
    CueStatusIcons,
    CueNumberWidget,
    NameWidget,
    PreWaitWidget,
    CueTimeWidget,
    NextActionIcon,
    PostWaitWidget,
    IndexWidget,
)
from lisp.ui.ui_utils import translate, css_to_dict, dict_to_css


class ListColumn:
    def __init__(self, name, widget, resize=None, width=None, visible=True):
        self.baseName = name
        self.widget = widget
        self.resize = resize
        self.width = width
        self.visible = visible

    @property
    def name(self):
        return translate("ListLayoutHeader", self.baseName)


class CueTreeWidgetItem(QTreeWidgetItem):
    def __init__(self, cue, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.cue = cue
        self.current = False


# TODO: use a custom Model/View
class CueListView(QTreeWidget):
    keyPressed = pyqtSignal(QKeyEvent)
    contextMenuInvoked = pyqtSignal(QContextMenuEvent)
    standbyChanged = pyqtSignal(int)

    # TODO: add ability to show/hide
    # TODO: implement columns (cue-type / target / etc..)
    COLUMNS = [
        ListColumn("", CueStatusIcons, QHeaderView.Fixed, width=75),
        ListColumn("#", IndexWidget, QHeaderView.ResizeToContents),
        ListColumn(
            QT_TRANSLATE_NOOP("ListLayoutHeader", "Q#"),
            CueNumberWidget,
            QHeaderView.ResizeToContents,
        ),
        ListColumn(
            QT_TRANSLATE_NOOP("ListLayoutHeader", "Cue"),
            NameWidget,
            QHeaderView.Stretch,
        ),
        ListColumn(
            QT_TRANSLATE_NOOP("ListLayoutHeader", "Pre wait"), PreWaitWidget
        ),
        ListColumn(
            QT_TRANSLATE_NOOP("ListLayoutHeader", "Action"), CueTimeWidget
        ),
        ListColumn(
            QT_TRANSLATE_NOOP("ListLayoutHeader", "Post wait"), PostWaitWidget
        ),
        ListColumn("", NextActionIcon, QHeaderView.Fixed, width=18),
    ]

    ITEM_DEFAULT_BG = QBrush(Qt.transparent)
    ITEM_CURRENT_BG = QBrush(QColor(250, 220, 0, 100))

    GROUP_OUTLINE_WIDTH = 2
    GROUP_OUTLINE_RADIUS = 4
    GROUP_OUTLINE_PARALLEL = QColor(76, 175, 80, 200)
    GROUP_OUTLINE_PLAYLIST = QColor(255, 152, 0, 200)
    GROUP_OUTLINE_COLORS = {
        "parallel": GROUP_OUTLINE_PARALLEL,
        "playlist": GROUP_OUTLINE_PLAYLIST,
    }

    INDICATOR_GREEN = QColor("#3E8A3B")
    INDICATOR_RED = QColor("#C03A2A")
    INDICATOR_RADIUS = 4
    INDICATOR_CX = INDICATOR_RADIUS * 2  # x-offset of dot centre from row's left edge

    def __init__(self, listModel, parent=None):
        """
        :type listModel: lisp.plugins.list_layout.models.CueListModel
        """
        super().__init__(parent)
        self.__itemMoving = False
        self.__scrollRangeGuard = False
        self._group_items = {}  # {group_cue_id: QTreeWidgetItem}
        self._auto_expand = True

        # Watch for model changes
        self._model = listModel
        self._model.item_added.connect(self.__cueAdded)
        self._model.item_moved.connect(self.__cueMoved)
        self._model.item_removed.connect(self.__cueRemoved)
        self._model.model_reset.connect(self.__modelReset)

        # Subscribe to pre-arm state changes for indicator dot repaints.
        # Guard with getattr so unit tests that don't set up a real
        # Application singleton still work cleanly.
        mgr = getattr(Application(), "pre_arm_manager", None)
        if mgr is not None:
            mgr.armed_set_changed.connect(self._on_armed_set_changed)

        # Setup the columns headers
        self.setHeaderLabels((c.name for c in CueListView.COLUMNS))
        for i, column in enumerate(CueListView.COLUMNS):
            if column.resize is not None:
                self.header().setSectionResizeMode(i, column.resize)
            if column.width is not None:
                self.setColumnWidth(i, column.width)

        self.header().setDragEnabled(False)
        self.header().setStretchLastSection(False)

        self.setDragDropMode(self.InternalMove)

        # Set some visual options
        self.setIndentation(16)
        self.setAlternatingRowColors(True)
        self.setVerticalScrollMode(self.ScrollPerItem)

        # This allows to have some spare space at the end of the scroll-area
        self.verticalScrollBar().rangeChanged.connect(self.__updateScrollRange)
        self.currentItemChanged.connect(
            self.__currentItemChanged, Qt.QueuedConnection
        )
        self.currentItemChanged.connect(self._on_current_item_changed)
        self.itemCollapsed.connect(self.__itemCollapsed)
        self.itemExpanded.connect(self.__itemExpanded)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            if all([x.isLocalFile() for x in event.mimeData().urls()]):
                event.accept()
            else:
                event.ignore()
        else:
            return super().dragEnterEvent(event)

    def dropEvent(self, event):
        if event.mimeData().hasUrls():
            # If files are being dropped, add them as cues
            get_backend().add_cue_from_urls(event.mimeData().urls())
        else:
            # Otherwise copy/move existing cue.

            # Decode mimedata information about the drag&drop event, since only
            # internal movement are allowed we assume the data format is correct
            data = event.mimeData().data(
                "application/x-qabstractitemmodeldatalist"
            )
            stream = QDataStream(data, QIODevice.ReadOnly)

            # Get the drop target index using item lookup to avoid
            # child-relative row numbers from QModelIndex.row()
            drop_item = self.itemAt(event.pos())
            if drop_item is not None:
                to_index = drop_item.cue.index
            else:
                to_index = len(self._model)

            rows = []
            while not stream.atEnd():
                row = stream.readInt()
                # Skip column and data
                stream.readInt()
                for _ in range(stream.readInt()):
                    stream.readInt()
                    stream.readQVariant()

                if rows and row == rows[-1]:
                    continue

                rows.append(row)

            if event.proposedAction() == Qt.MoveAction:
                Application().commands_stack.do(
                    ModelMoveItemsCommand(self._model, rows, to_index)
                )
            elif event.proposedAction() == Qt.CopyAction:
                new_cues = []
                for row in sorted(rows):
                    new_cues.append(
                        Application().cue_factory.clone_cue(
                            self._model.item(row)
                        )
                    )

                Application().commands_stack.do(
                    ModelInsertItemsCommand(self._model, to_index, *new_cues)
                )

    def contextMenuEvent(self, event):
        self.contextMenuInvoked.emit(event)

    def keyPressEvent(self, event):
        self.keyPressed.emit(event)
        # If the event object has been accepted during the `keyPressed`
        # emission don't call the base implementation
        if not event.isAccepted():
            super().keyPressEvent(event)

    def mousePressEvent(self, event):
        if (
            not event.buttons() & Qt.RightButton
            or not self.selectionMode() == QTreeWidget.NoSelection
        ):
            super().mousePressEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.updateHeadersSizes()

    def _on_armed_set_changed(self):
        """Repaint viewport when the pre-arm set changes."""
        self.viewport().update()

    def viewportEvent(self, event):
        if event.type() == QEvent.ToolTip:
            mgr = getattr(Application(), "pre_arm_manager", None)
            if mgr is not None:
                pos = event.pos()
                item = self.itemAt(pos)
                if item is not None:
                    cue = item.cue
                    cue_id = cue.id
                    if (
                        cue_id in mgr._failed
                        and getattr(cue, "preload", False)
                    ):
                        row_rect = self.visualItemRect(item)
                        dot_cx = row_rect.left() + self.INDICATOR_CX
                        dot_cy = row_rect.center().y()
                        dx = pos.x() - dot_cx
                        dy = pos.y() - dot_cy
                        if (
                            dx * dx + dy * dy
                            <= self.INDICATOR_RADIUS * self.INDICATOR_RADIUS
                        ):
                            QToolTip.showText(
                                event.globalPos(),
                                mgr._failed[cue_id],
                                self,
                            )
                            event.accept()
                            return True
        return super().viewportEvent(event)

    def paintEvent(self, event):
        super().paintEvent(event)

        mgr = getattr(Application(), "pre_arm_manager", None)
        has_groups = bool(self._group_items)
        has_armed = mgr is not None and bool(mgr._armed or mgr._failed)

        if not has_groups and not has_armed:
            return

        painter = QPainter(self.viewport())
        painter.setRenderHint(QPainter.Antialiasing)

        viewport_rect = self.viewport().rect()

        if has_groups:
            pen = QPen()
            pen.setWidth(self.GROUP_OUTLINE_WIDTH)
            for group_item in self._group_items.values():
                color = self.GROUP_OUTLINE_COLORS.get(
                    group_item.cue.group_mode
                )
                if color is None:
                    continue

                rect = self._groupOutlineRect(group_item)
                if rect is None or not rect.intersects(viewport_rect):
                    continue

                pen.setColor(color)
                painter.setPen(pen)
                painter.setBrush(Qt.NoBrush)
                painter.drawRoundedRect(
                    rect,
                    self.GROUP_OUTLINE_RADIUS,
                    self.GROUP_OUTLINE_RADIUS,
                )

        if mgr is not None:
            painter.setPen(Qt.NoPen)
            for item in self.iterAllItems():
                cue = item.cue
                cue_id = cue.id
                if cue_id in mgr._armed:
                    color = self.INDICATOR_GREEN
                elif (
                    cue_id in mgr._failed
                    and getattr(cue, "preload", False)
                ):
                    color = self.INDICATOR_RED
                else:
                    continue

                row_rect = self.visualItemRect(item)
                if row_rect.isEmpty():
                    continue

                cx = row_rect.left() + self.INDICATOR_CX
                cy = row_rect.center().y()
                painter.setBrush(QBrush(color))
                painter.drawEllipse(
                    QPoint(cx, cy),
                    self.INDICATOR_RADIUS,
                    self.INDICATOR_RADIUS,
                )

    def standbyIndex(self):
        return self.cueIndexOf(self.currentItem())

    def setStandbyIndex(self, newIndex):
        item = self.cueItemAt(newIndex)
        if item is not None:
            self.setCurrentItem(item)

    def _on_current_item_changed(self, current, _previous):
        """Bridge QTreeWidget.currentItemChanged → standbyChanged(index)."""
        if current is None:
            self.standbyChanged.emit(-1)
        else:
            self.standbyChanged.emit(self.cueIndexOf(current))

    def updateHeadersSizes(self):
        """Some hack to have "stretchable" columns with a minimum size

        NOTE: this currently works properly with only one "stretchable" column
        """
        header = self.header()
        for i, column in enumerate(CueListView.COLUMNS):
            if column.resize == QHeaderView.Stretch:
                # Make the header calculate the content size
                header.setSectionResizeMode(i, QHeaderView.ResizeToContents)
                contentWidth = header.sectionSize(i)

                # Make the header calculate the stretched size
                header.setSectionResizeMode(i, QHeaderView.Stretch)
                stretchWidth = header.sectionSize(i)

                # Set the maximum size as fixed size for the section
                header.setSectionResizeMode(i, QHeaderView.Fixed)
                header.resizeSection(i, max(contentWidth, stretchWidth))

    def cueItemAt(self, index):
        """Return the QTreeWidgetItem for a flat model index.

        Walks the tree in visual order (top-level items and
        their children) to find the item whose cue.index
        matches the requested index.
        """
        for i in range(self.topLevelItemCount()):
            top = self.topLevelItem(i)
            if top.cue.index == index:
                return top
            for j in range(top.childCount()):
                child = top.child(j)
                if child.cue.index == index:
                    return child
        return None

    def cueIndexOf(self, item):
        """Return the flat model index for a QTreeWidgetItem."""
        if item is None:
            return -1
        return item.cue.index

    def _groupOutlineRect(self, group_item):
        """Paint rect for a group's outline, or None if off-screen.

        When expanded, spans the group header and the last visible
        child. When collapsed (or childless), spans just the header.
        The rect is inset so the stroke sits fully inside the cell
        edges rather than straddling them.
        """
        header = self.visualItemRect(group_item)
        if header.isEmpty():
            return None

        rect = QRect(header)
        if group_item.isExpanded() and group_item.childCount() > 0:
            last_child = group_item.child(group_item.childCount() - 1)
            child_rect = self.visualItemRect(last_child)
            if not child_rect.isEmpty():
                rect = rect.united(child_rect)

        inset = self.GROUP_OUTLINE_WIDTH // 2 + 1
        rect.adjust(inset, inset, -inset, -inset)
        return rect

    def iterAllItems(self):
        """Yield all items in visual order (groups then children
        interleaved)."""
        for i in range(self.topLevelItemCount()):
            top = self.topLevelItem(i)
            yield top
            for j in range(top.childCount()):
                yield top.child(j)

    def setAutoExpand(self, enabled):
        self._auto_expand = enabled

    def __currentItemChanged(self, current, previous):
        if previous is not None:
            previous.current = False
            self.__updateItemStyle(previous)

        if current is not None:
            current.current = True
            self.__updateItemStyle(current)

            if self.selectionMode() == QTreeWidget.NoSelection:
                # Ensure the current item is in the middle of the viewport.
                # This is skipped in "selection-mode" otherwise it creates
                # confusion during drang&drop operations
                self.scrollToItem(current, QTreeWidget.PositionAtCenter)
            elif not self.selectedIndexes():
                current.setSelected(True)

    def __itemCollapsed(self, item):
        if isinstance(item.cue, GroupCue):
            item.cue.collapsed = True
        self.viewport().update()

    def __itemExpanded(self, item):
        if isinstance(item.cue, GroupCue):
            item.cue.collapsed = False
        self.viewport().update()

    def __updateItemStyle(self, item):
        if item.treeWidget() is not None:
            css = css_to_dict(item.cue.stylesheet)
            brush = QBrush()

            if item.current:
                widget_css = subdict(css, ("font-size",))
                brush = CueListView.ITEM_CURRENT_BG
            else:
                widget_css = subdict(css, ("color", "font-size"))
                css_bg = css.get("background")
                if css_bg is not None:
                    color = QColor(css_bg)
                    color.setAlpha(150)
                    brush = QBrush(color)

            # Dim disabled cues so they remain readable but visibly
            # de-emphasised. The foreground colour is muted grey;
            # any background-brush alpha is multiplied by 0.4 so
            # coloured rows stay recognisable but muted.
            if item.cue.effective_disabled:
                widget_css["color"] = "rgba(160, 160, 160, 0.5)"
                if brush.color().alpha() > 0:
                    dimmed = QColor(brush.color())
                    dimmed.setAlpha(int(dimmed.alpha() * 0.4))
                    brush = QBrush(dimmed)

            for column in range(self.columnCount()):
                # itemWidget may be None if this item's column
                # widgets haven't been set up yet (e.g. called
                # during insertion or before __setupItemWidgets).
                widget = self.itemWidget(item, column)
                if widget is not None:
                    widget.setStyleSheet(dict_to_css(widget_css))
                item.setBackground(column, brush)

    def _iter_all_items(self):
        """Yield every QTreeWidgetItem in the tree (top-level + children)."""
        for i in range(self.topLevelItemCount()):
            top = self.topLevelItem(i)
            yield top
            for j in range(top.childCount()):
                yield top.child(j)

    def __cuePropChanged(self, cue, property_name, _):
        if property_name == "stylesheet":
            item = self.cueItemAt(cue.index)
            if item is not None:
                self.__updateItemStyle(item)
        elif property_name == "disabled":
            # A disable toggle on a group also flips every
            # descendant's effective state. Re-style all rows rather
            # than walking the group-id graph — O(N) once per toggle
            # is negligible at realistic session sizes.
            for item in self._iter_all_items():
                self.__updateItemStyle(item)
        if property_name == "name":
            QTimer.singleShot(1, self.updateHeadersSizes)
        if property_name == "group_id":
            self.__cueGroupChanged(cue)
            # Re-style every row — the moved cue's effective
            # disabled state may have flipped (now under a
            # disabled ancestor, or no longer under one), and if
            # the moved cue is itself a group, all of ITS
            # descendants' effective state flip too. A full sweep
            # is O(N) and avoids missing the transitive cascade.
            for row in self._iter_all_items():
                self.__updateItemStyle(row)
        if property_name == "group_mode":
            self.viewport().update()

    def __cueGroupChanged(self, cue):
        """Reparent item when its group_id changes."""
        item = self.cueItemAt(cue.index)
        if item is None:
            return

        parent = item.parent()
        current_parent_id = parent.cue.id if parent is not None else None
        new_parent_id = cue.group_id or None
        # property_changed fires on every setattr, so undo of an
        # unrelated edit re-emits group_id with its existing value.
        # Skip the take-and-reinsert round-trip when the item is
        # already under the right parent — otherwise we'd wipe the
        # tree's selection as a side-effect.
        if current_parent_id == new_parent_id:
            return

        # Remove from current parent
        if parent is not None:
            parent.removeChild(item)
        else:
            idx = self.indexOfTopLevelItem(item)
            if idx >= 0:
                self.takeTopLevelItem(idx)

        # Re-insert under new parent (or top-level)
        if cue.group_id and cue.group_id in self._group_items:
            new_parent = self._group_items[cue.group_id]
            child_pos = 0
            for j in range(new_parent.childCount()):
                if new_parent.child(j).cue.index < cue.index:
                    child_pos = j + 1
                else:
                    break
            new_parent.insertChild(child_pos, item)
        else:
            pos = 0
            for i in range(self.topLevelItemCount()):
                if self.topLevelItem(i).cue.index < cue.index:
                    pos = i + 1
                else:
                    break
            self.insertTopLevelItem(pos, item)

        self.__setupItemWidgetsRecursive(item)
        self.__updateItemStyle(item)

    def __cueAdded(self, cue):
        item = CueTreeWidgetItem(cue)
        item.setFlags(item.flags() & ~Qt.ItemIsDropEnabled)
        cue.property_changed.connect(self.__cuePropChanged)

        # Block signals to prevent itemExpanded/itemCollapsed
        # from firing during insertion and overwriting the
        # persisted collapsed state on the cue.
        self.blockSignals(True)
        try:
            if isinstance(cue, GroupCue):
                pos = 0
                for i in range(self.topLevelItemCount()):
                    if (
                        self.topLevelItem(i).cue.index
                        < cue.index
                    ):
                        pos = i + 1
                    else:
                        break
                self.insertTopLevelItem(pos, item)
                self._group_items[cue.id] = item
                item.setExpanded(not cue.collapsed)
                cue.started.connect(
                    self.__groupStarted, Connection.QtQueued
                )
            elif (
                cue.group_id
                and cue.group_id in self._group_items
            ):
                parent = self._group_items[cue.group_id]
                child_pos = 0
                for j in range(parent.childCount()):
                    if (
                        parent.child(j).cue.index
                        < cue.index
                    ):
                        child_pos = j + 1
                    else:
                        break
                parent.insertChild(child_pos, item)
            else:
                pos = 0
                for i in range(self.topLevelItemCount()):
                    if (
                        self.topLevelItem(i).cue.index
                        < cue.index
                    ):
                        pos = i + 1
                    else:
                        break
                self.insertTopLevelItem(pos, item)
        finally:
            self.blockSignals(False)

        self.__setupItemWidgets(item)
        self.__updateItemStyle(item)

        total = sum(
            1 + self.topLevelItem(i).childCount()
            for i in range(self.topLevelItemCount())
        )
        if total == 1:
            self.setCurrentItem(item)
        elif not (
            item.parent() is not None
            and not item.parent().isExpanded()
        ):
            # Don't scroll to children of collapsed groups —
            # scrollToItem would auto-expand the parent.
            self.scrollToItem(item)

        self.setFocus()

    def __groupStarted(self, cue):
        if not self._auto_expand:
            return
        if not (cue.state & CueState.IsRunning):
            return
        if cue.id in self._group_items:
            item = self._group_items[cue.id]
            item.setExpanded(True)
            cue.collapsed = False

    def __cueMoved(self, before, after):
        item = self.cueItemAt(after)
        if item is None:
            return

        # Remove from current parent
        parent = item.parent()
        if parent is not None:
            parent.removeChild(item)
        else:
            idx = self.indexOfTopLevelItem(item)
            if idx >= 0:
                self.takeTopLevelItem(idx)

        # Update the cue index on the item before reinsertion
        # (the model has already updated cue.index)

        # Determine new parent
        cue = item.cue
        if cue.group_id and cue.group_id in self._group_items:
            new_parent = self._group_items[cue.group_id]
            child_pos = 0
            for j in range(new_parent.childCount()):
                if new_parent.child(j).cue.index < cue.index:
                    child_pos = j + 1
                else:
                    break
            new_parent.insertChild(child_pos, item)
        else:
            pos = 0
            for i in range(self.topLevelItemCount()):
                if self.topLevelItem(i).cue.index < cue.index:
                    pos = i + 1
                else:
                    break
            self.insertTopLevelItem(pos, item)

        self.__setupItemWidgetsRecursive(item)

    def __cueRemoved(self, cue):
        cue.property_changed.disconnect(self.__cuePropChanged)

        if isinstance(cue, GroupCue):
            cue.started.disconnect(self.__groupStarted)
            group_item = self._group_items.pop(cue.id, None)

            # Reparent children to top-level before removing group
            if group_item is not None:
                while group_item.childCount() > 0:
                    child = group_item.takeChild(0)
                    # Find correct top-level position by index
                    pos = 0
                    for i in range(self.topLevelItemCount()):
                        if (
                            self.topLevelItem(i).cue.index
                            < child.cue.index
                        ):
                            pos = i + 1
                        else:
                            break
                    self.insertTopLevelItem(pos, child)
                    self.__setupItemWidgets(child)

        item = self.cueItemAt(cue.index)
        if item is None:
            return

        parent = item.parent()
        if parent is not None:
            parent.removeChild(item)
        else:
            idx = self.indexOfTopLevelItem(item)
            if idx >= 0:
                self.takeTopLevelItem(idx)

    def __modelReset(self):
        self._group_items.clear()
        self.reset()
        self.clear()

    def __setupItemWidgets(self, item):
        for i, column in enumerate(CueListView.COLUMNS):
            self.setItemWidget(item, i, column.widget(item))

    def __setupItemWidgetsRecursive(self, item):
        """Install column widgets for `item` and every descendant.

        Qt's `setItemWidget` binding doesn't survive `takeTopLevelItem`
        / `takeChild` — the viewport loses its cell-to-widget mapping
        when items leave the tree. Re-installing widgets only on the
        moved item would leave any tree children (e.g. a dragged
        GroupCue's contents) with None for `itemWidget(child, col)`,
        which crashes `__updateItemStyle` on the next selection change.
        """
        self.__setupItemWidgets(item)
        for i in range(item.childCount()):
            self.__setupItemWidgetsRecursive(item.child(i))

        self.updateGeometries()

    def __updateScrollRange(self, min_, max_):
        if not self.__scrollRangeGuard:
            self.__scrollRangeGuard = True
            self.verticalScrollBar().setMaximum(max_ + 1)
            self.__scrollRangeGuard = False
