# Collapsible Groups Implementation Plan ✅ Complete

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Make group cues in the list layout collapsible, using native QTreeWidget parent/child hierarchy with per-group persistent state and auto-expand on play.

**Architecture:** The flat `CueListModel` stays unchanged. The `CueListView` (QTreeWidget) gains a true parent/child hierarchy where child cues of a group are inserted as children of the group's `QTreeWidgetItem`. A `collapsed` property on `GroupCue` persists state via the existing `Property` serialization system. A helper method on `CueListView` maps between flat model indices and tree items.

**Tech Stack:** Python 3.9+, PyQt5 (QTreeWidget), LiSP Property system, JSON-RPC test harness

**Spec:** `docs/specs/2026-04-10-collapsible-groups-design.md`

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `lisp/plugins/action_cues/group_cue.py` | Modify | Add `collapsed = Property(default=False)` |
| `lisp/plugins/list_layout/list_view.py` | Modify | Parent-aware add/move/remove, collapse sync, auto-expand, tree traversal helpers |
| `lisp/plugins/list_layout/list_widgets.py` | Modify | Remove 4-space indent hack from `NameWidget` |
| `lisp/plugins/list_layout/layout.py` | Modify | Collapse/expand all menu actions, fix `selected_cues` and friends for child items |
| `lisp/plugins/list_layout/view.py` | Modify | Fix `__listViewCurrentChanged` to handle child items |
| `lisp/plugins/list_layout/default.json` | Modify | Add `autoExpandOnPlay` setting |
| `lisp/plugins/list_layout/settings.py` | Modify | Add auto-expand checkbox to settings page |
| `tests/cues/test_group_cue.py` | Modify | Test `collapsed` property defaults and serialization |
| `tests/e2e/test_groups_e2e.py` | Modify | Add collapse/expand E2E tests |

---

### Task 1: Add `collapsed` Property to GroupCue

**Files:**
- Modify: `lisp/plugins/action_cues/group_cue.py:56-60`
- Test: `tests/cues/test_group_cue.py`

- [x] **Step 1: Write failing tests for the `collapsed` property**

Add to `tests/cues/test_group_cue.py` inside `TestGroupCueDefaults`:

```python
def test_default_collapsed_false(self, group):
    assert group.collapsed is False
```

Add a new test class after `TestGroupIdProperty`:

```python
class TestCollapsedProperty:
    def test_collapsed_default(self, mock_app):
        g = GroupCue(mock_app)
        assert g.collapsed is False

    def test_collapsed_serialized(self, mock_app):
        g = GroupCue(mock_app)
        g.collapsed = True
        props = g.properties()
        assert props["collapsed"] is True

    def test_collapsed_not_in_defaults_when_false(self, mock_app):
        g = GroupCue(mock_app)
        props = g.properties(defaults=False)
        assert "collapsed" not in props
```

- [x] **Step 2: Run tests to verify they fail**

Run: `poetry run pytest tests/cues/test_group_cue.py::TestGroupCueDefaults::test_default_collapsed_false tests/cues/test_group_cue.py::TestCollapsedProperty -v`

Expected: FAIL — `AttributeError: 'GroupCue' object has no attribute 'collapsed'`

- [x] **Step 3: Add the `collapsed` property**

In `lisp/plugins/action_cues/group_cue.py`, add after line 60 (`icon = Property(default="cue-group")`):

```python
    collapsed = Property(default=False)
```

- [x] **Step 4: Run tests to verify they pass**

Run: `poetry run pytest tests/cues/test_group_cue.py -v`

Expected: ALL PASS

- [x] **Step 5: Commit**

```bash
git add lisp/plugins/action_cues/group_cue.py tests/cues/test_group_cue.py
git commit -m "Add collapsed property to GroupCue for persistent collapse state"
```

---

### Task 2: Add `autoExpandOnPlay` Config Setting

**Files:**
- Modify: `lisp/plugins/list_layout/default.json`
- Modify: `lisp/plugins/list_layout/settings.py`

- [x] **Step 1: Add config default**

In `lisp/plugins/list_layout/default.json`, add after `"infoPanelFontSize": 12` (line 21), before the closing `}`:

```json
    "infoPanelFontSize": 12,
    "autoExpandOnPlay": true
```

(Note: add a comma after `12` and the new line.)

- [x] **Step 2: Add checkbox to settings page**

In `lisp/plugins/list_layout/settings.py`, add inside `__init__` after `self.selectionMode` (line 65):

```python
        self.autoExpandOnPlay = QCheckBox(self.defaultBehaviorsGroup)
        self.defaultBehaviorsGroup.layout().addWidget(
            self.autoExpandOnPlay
        )
```

In `retranslateUi`, add after the `selectionMode` setText (line 129):

```python
        self.autoExpandOnPlay.setText(
            translate(
                "ListLayout", "Auto-expand groups on play"
            )
        )
```

In `loadSettings`, add after `self.selectionMode.setChecked(...)` (line 158):

```python
        self.autoExpandOnPlay.setChecked(
            settings.get("autoExpandOnPlay", True)
        )
```

In `getSettings`, add to the returned dict after `"selectionMode"` (line 183):

```python
            "autoExpandOnPlay": self.autoExpandOnPlay.isChecked(),
```

- [x] **Step 3: Commit**

```bash
git add lisp/plugins/list_layout/default.json lisp/plugins/list_layout/settings.py
git commit -m "Add autoExpandOnPlay config setting to list layout"
```

---

### Task 3: Remove NameWidget Text-Indent Hack

**Files:**
- Modify: `lisp/plugins/list_layout/list_widgets.py:59-94`

- [x] **Step 1: Remove the 4-space indent from NameWidget**

In `lisp/plugins/list_layout/list_widgets.py`, replace the `_refresh` method (lines 77-85):

Old:
```python
    def _refresh(self):
        name = self._item.cue.name
        if self._item.cue.exclusive:
            name = "* " + name
        # Indent children of a group
        if self._item.cue.group_id:
            name = "    " + name

        super().setText(name)
```

New:
```python
    def _refresh(self):
        name = self._item.cue.name
        if self._item.cue.exclusive:
            name = "* " + name

        super().setText(name)
```

Also remove the `group_id` signal connection in `__init__` (lines 71-73) and the `__update_group` method (lines 93-94):

Old (lines 71-73):
```python
        self._item.cue.changed("group_id").connect(
            self.__update_group, Connection.QtQueued
        )
```

Remove those 3 lines.

Old (lines 93-94):
```python
    def __update_group(self, value):
        self._refresh()
```

Remove those 2 lines.

- [x] **Step 2: Commit**

```bash
git add lisp/plugins/list_layout/list_widgets.py
git commit -m "Remove text-indent hack from NameWidget, tree handles indentation"
```

---

### Task 4: Core CueListView — Tree Hierarchy and Item Lookup

This is the main change. The view becomes hierarchy-aware.

**Files:**
- Modify: `lisp/plugins/list_layout/list_view.py`

- [x] **Step 1: Add imports and tree item lookup helper**

At the top of `list_view.py`, add to the imports:

After `from lisp.application import Application` (line 29):

```python
from lisp.core.signal import Connection
```

After `from lisp.command.model import ...` (line 31):

```python
from lisp.plugins.action_cues.group_cue import GroupCue
```

Add a helper method to `CueListView` after `updateHeadersSizes` (after line 240). This maps a flat model index to the corresponding `QTreeWidgetItem` in the (potentially nested) tree:

```python
    def itemFromIndex(self, index):
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

    def indexFromItem(self, item):
        """Return the flat model index for a QTreeWidgetItem."""
        if item is None:
            return -1
        return item.cue.index

    def iterAllItems(self):
        """Yield all items in visual order (groups then children
        interleaved)."""
        for i in range(self.topLevelItemCount()):
            top = self.topLevelItem(i)
            yield top
            for j in range(top.childCount()):
                yield top.child(j)
```

- [x] **Step 2: Enable indentation**

In `__init__`, change line 125:

Old:
```python
        self.setIndentation(0)
```

New:
```python
        self.setIndentation(16)
```

- [x] **Step 3: Add `_group_items` dict and collapse signal connections**

In `__init__`, after `self.__scrollRangeGuard = False` (line 102), add:

```python
        self._group_items = {}  # {group_cue_id: QTreeWidgetItem}
        self._auto_expand = True
```

After the `currentItemChanged` connection (line 133), add:

```python
        self.itemCollapsed.connect(self.__itemCollapsed)
        self.itemExpanded.connect(self.__itemExpanded)
```

Add the signal handler methods after `__currentItemChanged` (after line 258):

```python
    def __itemCollapsed(self, item):
        if isinstance(item.cue, GroupCue):
            item.cue.collapsed = True

    def __itemExpanded(self, item):
        if isinstance(item.cue, GroupCue):
            item.cue.collapsed = False
```

- [x] **Step 4: Add `setAutoExpand` method**

Add after the collapse/expand handlers:

```python
    def setAutoExpand(self, enabled):
        self._auto_expand = enabled
```

- [x] **Step 5: Rewrite `__cueAdded` for parent-aware insertion**

Replace `__cueAdded` (lines 287-304):

```python
    def __cueAdded(self, cue):
        item = CueTreeWidgetItem(cue)
        item.setFlags(item.flags() & ~Qt.ItemIsDropEnabled)
        cue.property_changed.connect(self.__cuePropChanged)

        if isinstance(cue, GroupCue):
            # Insert group as top-level; count existing
            # top-level items to find the right position.
            pos = 0
            for i in range(self.topLevelItemCount()):
                if self.topLevelItem(i).cue.index < cue.index:
                    pos = i + 1
                else:
                    break
            self.insertTopLevelItem(pos, item)
            self._group_items[cue.id] = item
            item.setExpanded(not cue.collapsed)
            # Connect auto-expand on play
            cue.started.connect(
                self.__groupStarted, Connection.QtQueued
            )
        elif cue.group_id and cue.group_id in self._group_items:
            # Insert as child of the group item
            parent = self._group_items[cue.group_id]
            # Find correct child position by index
            child_pos = 0
            for j in range(parent.childCount()):
                if parent.child(j).cue.index < cue.index:
                    child_pos = j + 1
                else:
                    break
            parent.insertChild(child_pos, item)
        else:
            # Non-grouped cue, insert as top-level
            pos = 0
            for i in range(self.topLevelItemCount()):
                if self.topLevelItem(i).cue.index < cue.index:
                    pos = i + 1
                else:
                    break
            self.insertTopLevelItem(pos, item)

        self.__setupItemWidgets(item)
        self.__updateItemStyle(item)

        total = sum(
            1 + self.topLevelItem(i).childCount()
            for i in range(self.topLevelItemCount())
        )
        if total == 1:
            self.setCurrentItem(item)
        else:
            self.scrollToItem(item)

        self.setFocus()
```

- [x] **Step 6: Add `__groupStarted` handler**

After the new `__cueAdded`:

```python
    def __groupStarted(self, cue):
        if self._auto_expand and cue.id in self._group_items:
            item = self._group_items[cue.id]
            item.setExpanded(True)
            cue.collapsed = False
```

- [x] **Step 7: Rewrite `__cueMoved`**

Replace `__cueMoved` (lines 306-309):

```python
    def __cueMoved(self, before, after):
        item = self.itemFromIndex(before)
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

        self.__setupItemWidgets(item)
```

- [x] **Step 8: Rewrite `__cueRemoved`**

Replace `__cueRemoved` (lines 311-313):

```python
    def __cueRemoved(self, cue):
        cue.property_changed.disconnect(self.__cuePropChanged)

        if isinstance(cue, GroupCue):
            cue.started.disconnect(self.__groupStarted)
            self._group_items.pop(cue.id, None)

        item = self.itemFromIndex(cue.index)
        if item is None:
            return

        parent = item.parent()
        if parent is not None:
            parent.removeChild(item)
        else:
            idx = self.indexOfTopLevelItem(item)
            if idx >= 0:
                self.takeTopLevelItem(idx)
```

- [x] **Step 9: Rewrite `standbyIndex` and `setStandbyIndex`**

Replace `standbyIndex` (lines 215-216) and `setStandbyIndex` (lines 218-220):

```python
    def standbyIndex(self):
        return self.indexFromItem(self.currentItem())

    def setStandbyIndex(self, newIndex):
        item = self.itemFromIndex(newIndex)
        if item is not None:
            self.setCurrentItem(item)
```

- [x] **Step 10: Fix `__cuePropChanged` for non-top-level items**

Replace `__cuePropChanged` (lines 281-285):

```python
    def __cuePropChanged(self, cue, property_name, _):
        if property_name == "stylesheet":
            item = self.itemFromIndex(cue.index)
            if item is not None:
                self.__updateItemStyle(item)
        if property_name == "name":
            QTimer.singleShot(1, self.updateHeadersSizes)
        if property_name == "group_id":
            self.__cueGroupChanged(cue)

    def __cueGroupChanged(self, cue):
        """Reparent item when its group_id changes."""
        item = self.itemFromIndex(cue.index)
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

        self.__setupItemWidgets(item)
        self.__updateItemStyle(item)
```

- [x] **Step 11: Fix `__modelReset` to clear group tracking**

Replace `__modelReset` (lines 315-317):

```python
    def __modelReset(self):
        self._group_items.clear()
        self.reset()
        self.clear()
```

- [x] **Step 12: Commit**

```bash
git add lisp/plugins/list_layout/list_view.py
git commit -m "Make CueListView hierarchy-aware for collapsible groups"
```

---

### Task 5: Fix ListLayout for Tree Hierarchy

**Files:**
- Modify: `lisp/plugins/list_layout/layout.py`

- [x] **Step 1: Fix `selected_cues`**

Replace `selected_cues` (lines 294-298):

```python
    def selected_cues(self, cue_type=Cue):
        for item in self._view.listView.selectedItems():
            yield item.cue
```

- [x] **Step 2: Fix `select_all`, `deselect_all`, `invert_selection`**

Replace `select_all` (lines 310-314):

```python
    def select_all(self, cue_type=Cue):
        if self.selection_mode:
            for item in self._view.listView.iterAllItems():
                if isinstance(item.cue, cue_type):
                    item.setSelected(True)
```

Replace `deselect_all` (lines 316-319):

```python
    def deselect_all(self, cue_type=Cue):
        for item in self._view.listView.iterAllItems():
            if isinstance(item.cue, cue_type):
                item.setSelected(False)
```

Replace `invert_selection` (lines 321-325):

```python
    def invert_selection(self):
        if self.selection_mode:
            for item in self._view.listView.iterAllItems():
                item.setSelected(not item.isSelected())
```

- [x] **Step 3: Fix `_set_selection_mode` for child items**

In `_set_selection_mode` (line 416), replace the `topLevelItem` reference:

Old (line 414-416):
```python
            standby = self.standby_index()
            if standby >= 0:
                self._view.listView.topLevelItem(standby).setSelected(True)
```

New:
```python
            standby = self.standby_index()
            if standby >= 0:
                item = self._view.listView.itemFromIndex(standby)
                if item is not None:
                    item.setSelected(True)
```

- [x] **Step 4: Add collapse/expand all menu actions**

In `__init__`, after the `layout_menu.addSeparator()` block (after line 137), before `self.enable_view_resize_action` (line 139), add:

```python
        self.collapse_all_action = QAction(layout_menu)
        self.collapse_all_action.setShortcut(
            QKeySequence("Ctrl+Shift+[")
        )
        self.collapse_all_action.triggered.connect(
            self._collapse_all_groups
        )
        layout_menu.addAction(self.collapse_all_action)

        self.expand_all_action = QAction(layout_menu)
        self.expand_all_action.setShortcut(
            QKeySequence("Ctrl+Shift+]")
        )
        self.expand_all_action.triggered.connect(
            self._expand_all_groups
        )
        layout_menu.addAction(self.expand_all_action)

        layout_menu.addSeparator()
```

- [x] **Step 5: Add the handler methods and `autoExpandOnPlay` wiring**

Add after `_set_view_resize_enabled` (after line 435):

```python
    def _collapse_all_groups(self):
        from lisp.plugins.action_cues.group_cue import GroupCue

        for i in range(
            self._view.listView.topLevelItemCount()
        ):
            item = self._view.listView.topLevelItem(i)
            if isinstance(item.cue, GroupCue):
                item.setExpanded(False)
                item.cue.collapsed = True

    def _expand_all_groups(self):
        from lisp.plugins.action_cues.group_cue import GroupCue

        for i in range(
            self._view.listView.topLevelItemCount()
        ):
            item = self._view.listView.topLevelItem(i)
            if isinstance(item.cue, GroupCue):
                item.setExpanded(True)
                item.cue.collapsed = False
```

- [x] **Step 6: Wire `autoExpandOnPlay` config to the view**

In `__init__`, after the existing `_set_go_key_disabled_while_playing` load (after line 159), add:

```python
        self._view.listView.setAutoExpand(
            ListLayout.Config.get("autoExpandOnPlay", True)
        )
```

- [x] **Step 7: Add translations for new menu actions**

In `retranslate`, add after the existing entries:

```python
        self.collapse_all_action.setText(
            translate("ListLayout", "Collapse all groups")
        )
        self.expand_all_action.setText(
            translate("ListLayout", "Expand all groups")
        )
```

- [x] **Step 8: Commit**

```bash
git add lisp/plugins/list_layout/layout.py
git commit -m "Update ListLayout for tree hierarchy and add collapse/expand all"
```

---

### Task 6: Fix ListLayoutView Info Panel

**Files:**
- Modify: `lisp/plugins/list_layout/view.py:132-139`

- [x] **Step 1: Fix `__listViewCurrentChanged` to handle child items**

Replace `__listViewCurrentChanged` (lines 132-139):

```python
    def __listViewCurrentChanged(self, current, _):
        cue = None
        if current is not None:
            cue = current.cue

        self.infoPanel.cue = cue
```

This removes the `indexOfTopLevelItem` → `listModel.item(index)` lookup. Since `CueTreeWidgetItem` already stores a reference to the cue, we access it directly.

- [x] **Step 2: Commit**

```bash
git add lisp/plugins/list_layout/view.py
git commit -m "Fix info panel to read cue directly from tree item"
```

---

### Task 7: E2E Tests for Collapsible Groups

**Files:**
- Modify: `tests/e2e/test_groups_e2e.py`

- [x] **Step 1: Add collapse/expand persistence test**

Add a new test function after `test_9_save_load`:

```python
def test_11_collapse_persist(ids, group_id):
    print("\n═══ Test 11: Collapse Persistence ═══")

    # 11a: Set collapsed
    call("cue.set_property", {
        "id": group_id, "property": "collapsed",
        "value": True,
    })
    check("11a: Collapsed set",
          cue_prop(group_id, "collapsed") is True)

    # 11b: Save and reload
    save_path = "/tmp/lisp_collapse_test_session.lsp"
    call("session.save", {"path": save_path})
    call("session.load", {"path": save_path})
    time.sleep(2)

    cues = call("cue.list")
    group = next(
        c for c in sorted(cues, key=lambda c: c["index"])
        if c["_type_"] == "GroupCue"
    )
    gid = group["id"]

    check("11b: Collapsed persists after reload",
          cue_prop(gid, "collapsed") is True)

    # 11c: Default is not collapsed
    call("cue.set_property", {
        "id": gid, "property": "collapsed",
        "value": False,
    })
    check("11c: Can set back to expanded",
          cue_prop(gid, "collapsed") is False)

    return gid
```

- [x] **Step 2: Wire the new test into `main()`**

In the `try` block in `main()` (around line 693), add after the `test_10_edge_cases` call:

```python
        group_id = test_11_collapse_persist(ids, group_id)
```

Also update the `conftest.py` ignore list — add the new test is in the same file, so no change needed there.

- [x] **Step 3: Commit**

```bash
git add tests/e2e/test_groups_e2e.py
git commit -m "Add E2E tests for collapse state persistence"
```

---

### Task 8: Manual Smoke Test

- [x] **Step 1: Run the full unit test suite**

Run: `poetry run pytest tests/ -v`

Expected: ALL PASS

- [x] **Step 2: Run the E2E test suite**

Run: `poetry run python tests/e2e/test_groups_e2e.py`

Expected: ALL PASS (including new test_11)

- [x] **Step 3: Manual smoke test**

Start LiSP: `poetry run linux-show-player -l debug`

Verify:
1. Add several cues (drag audio files or use Add Cue menu)
2. Select 3+ cues, right-click → "Group selected" → group appears with expand arrow
3. Click arrow to collapse → children hide
4. Click again to expand → children reappear
5. Save session, close, reopen → collapsed state preserved
6. Start the group → it auto-expands
7. Layout menu → "Collapse all groups" collapses all
8. Layout menu → "Expand all groups" expands all
9. Ctrl+Shift+[ and Ctrl+Shift+] shortcuts work
10. Ungroup → children return to top-level, no crash
11. GO button skips child cues (same as before)

- [x] **Step 4: Final commit if any fixes needed**

```bash
git add -u
git commit -m "Fix issues found during smoke testing"
```

(Only if changes were needed.)
