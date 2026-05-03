#!/usr/bin/env python3
"""Headless render the CueListView with a nested-group structure
and save the result as a PNG. Used for iterating on visual fixes
(column widths, paint clipping) without launching a GUI.

Run:
    poetry run python tools/render_cue_list.py [output.png]
"""
import os
import sys
import unittest.mock as mock

# Force offscreen Qt platform so this works without a display.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# Repo root on path
sys.path.insert(
    0,
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
)

from PyQt5.QtCore import QSize
from PyQt5.QtGui import QPixmap
from PyQt5.QtWidgets import QApplication

from lisp.core.configuration import DummyConfiguration
from lisp.cues.cue import Cue
from lisp.cues.cue_model import CueModel
from lisp.plugins.action_cues.group_cue import GroupCue
from lisp.plugins.list_layout.list_view import CueListView
from lisp.plugins.list_layout.models import CueListModel
from lisp.ui.icons import IconTheme


def build_app_mock():
    app_mock = mock.MagicMock()
    app_mock.conf = DummyConfiguration(root={
        "cue": {
            "interruptFade": 0,
            "interruptFadeType": "Linear",
            "fadeAction": 0,
            "fadeActionType": "Linear",
        }
    })
    return app_mock


def build_view():
    app_mock = build_app_mock()
    cue_model = CueModel()
    list_model = CueListModel(cue_model)
    app_mock.cue_model = cue_model

    view = CueListView(list_model)
    view.resize(900, 500)

    outer = GroupCue(id="outer", app=app_mock)
    cue_model.add(outer)

    inner = GroupCue(id="inner", app=app_mock)
    inner.group_id = "outer"
    cue_model.add(inner)

    leaf1 = Cue(id="leaf1", app=app_mock)
    leaf1.group_id = "inner"
    leaf1.name = "tone_B"
    cue_model.add(leaf1)

    leaf2 = Cue(id="leaf2", app=app_mock)
    leaf2.group_id = "inner"
    leaf2.name = "tone_C"
    cue_model.add(leaf2)

    sibling = Cue(id="sib", app=app_mock)
    sibling.group_id = "outer"
    sibling.name = "tone_A"
    cue_model.add(sibling)

    # Expand both groups so the column 0 indent reaches max
    view._group_items["outer"].setExpanded(True)
    view._group_items["inner"].setExpanded(True)

    return view


def main():
    out_path = sys.argv[1] if len(sys.argv) > 1 else "/tmp/cue_list.png"
    qapp = QApplication.instance() or QApplication(sys.argv)
    if IconTheme._GlobalTheme is None:
        IconTheme.set_theme_name("lisp")
    view = build_view()
    view.show()
    qapp.processEvents()
    view.repaint()
    qapp.processEvents()

    # Render the actual viewport on a black background so the
    # white/light status icons are visible.
    from PyQt5.QtCore import Qt
    pix = QPixmap(view.size())
    pix.fill(Qt.black)
    view.render(pix)
    pix.save(out_path, "PNG")

    # Also dump column widths and indent settings for diagnostic
    h = view.header()
    print(f"output: {out_path}")
    print(f"viewport size: {view.size().width()}x{view.size().height()}")
    print(f"setIndentation: {view.indentation()}")
    for i in range(h.count()):
        print(
            f"col {i}: width={h.sectionSize(i)} "
            f"resizeMode={h.sectionResizeMode(i)}"
        )
    # Status icon widget actual width per row
    for cue_id in ("outer", "sib", "inner", "leaf1", "leaf2"):
        item = view._group_items.get(cue_id)
        if item is None:
            # find leaf via cueItemAt
            from lisp.cues.cue_model import CueModel as _CM  # noqa
            for i in range(view.topLevelItemCount()):
                top = view.topLevelItem(i)
                # walk
                stack = [top]
                while stack:
                    it = stack.pop()
                    if it.cue.id == cue_id:
                        item = it
                        break
                    for j in range(it.childCount()):
                        stack.append(it.child(j))
                if item is not None:
                    break
        if item is None:
            continue
        widget = view.itemWidget(item, 0)
        if widget is None:
            print(f"{cue_id}: no widget")
            continue
        rect = view.visualItemRect(item)
        print(
            f"{cue_id}: depth={_depth(item)} row_h={rect.height()} "
            f"widget_size={widget.size().width()}x{widget.size().height()} "
            f"sizeHint={widget.sizeHint().width()}x{widget.sizeHint().height()}"
        )


def _depth(item):
    d = 0
    p = item.parent()
    while p is not None:
        d += 1
        p = p.parent()
    return d


if __name__ == "__main__":
    main()
