"""Deleting a group and undoing must rebuild the *tree*, not just the model.

RemoveCuesCommand.undo() re-adds removed cues and restores the group_id /
children links CueModel.pop() rewrote. Each group_id write fires
property_changed -> CueListView.__cueGroupChanged, which reparents the
row under ``_group_items[group_id]`` -- but only if the group's row
already exists. __cueAdded places a re-added group's own row and never
adopts existing rows pointing at it, so restoring links *before* the
group is back leaves its children drawn as top-level rows while the
model (and playback) say they're inside it.

Wired end to end: CueModel -> CueListModel -> CueListView, so the real
add/remove/property_changed handlers run.
"""

import pytest

from lisp.command.group import RemoveCuesCommand
from lisp.cues.cue import Cue
from lisp.cues.cue_model import CueModel
from lisp.plugins.action_cues.group_cue import GroupCue
from lisp.plugins.list_layout.list_view import CueListView
from lisp.plugins.list_layout.models import CueListModel
from lisp.ui.icons import IconTheme


@pytest.fixture(autouse=True)
def _icon_theme():
    """List-column widgets pull icons via IconTheme at construction."""
    if IconTheme._GlobalTheme is None:
        IconTheme.set_theme_name("lisp")
    yield


@pytest.fixture
def wired(qapp, mock_app):
    cue_model = CueModel()
    mock_app.cue_model = cue_model
    view = CueListView(CueListModel(cue_model))
    yield cue_model, view, mock_app


def _item(view, cue):
    return view.cueItemAt(cue.index)


def _add(cue_model, cue, index):
    cue.index = index
    cue_model.add(cue)


def test_undo_delete_top_level_group_reparents_rows(wired):
    cue_model, view, app = wired
    g = GroupCue(id="g", app=app)
    a = Cue(id="a", app=app)
    b = Cue(id="b", app=app)
    a.group_id = b.group_id = "g"
    g.children = ["a", "b"]
    for i, cue in enumerate((g, a, b)):
        _add(cue_model, cue, i)

    group_item = view._group_items["g"]
    assert _item(view, a).parent() is group_item  # sanity

    cmd = RemoveCuesCommand(cue_model, g)
    cmd.do()
    assert _item(view, a).parent() is None  # promoted to top-level

    cmd.undo()

    group_item = view._group_items["g"]
    assert _item(view, a).parent() is group_item
    assert _item(view, b).parent() is group_item


def test_undo_delete_nested_group_reparents_rows(wired):
    cue_model, view, app = wired
    o = GroupCue(id="o", app=app)
    i = GroupCue(id="i", app=app)
    a = Cue(id="a", app=app)
    i.group_id = "o"
    a.group_id = "i"
    o.children = ["i"]
    i.children = ["a"]
    for idx, cue in enumerate((o, i, a)):
        _add(cue_model, cue, idx)

    cmd = RemoveCuesCommand(cue_model, i)
    cmd.do()
    assert _item(view, a).parent() is view._group_items["o"]

    cmd.undo()

    assert view._group_items["i"].parent() is view._group_items["o"]
    assert _item(view, a).parent() is view._group_items["i"]
