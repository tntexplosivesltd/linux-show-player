"""Deleting a group through the cue model must remove the group's own row.

When a cue is removed, CueListModel re-indexes the remaining cues before
CueListView.__cueRemoved runs, so the first surviving cue takes the
removed cue's old index. For a group, __cueRemoved first moves the
group's children up to the parent level (a child with that same index
lands *before* the group's row), then looked the row to delete up by
``cue.index`` -- finding the child, not the group. The child's row was
deleted and the group's stayed on screen.

Wired end to end (CueModel -> CueListModel -> CueListView) so the real
re-indexing and handlers run, unlike the bypassing tests in
test_list_view_nested_remove.py.
"""

import pytest

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


def _tree(view):
    """The tree as nested (id, [children]) tuples, in display order."""
    def walk(item):
        return (
            item.cue.id,
            [walk(item.child(j)) for j in range(item.childCount())],
        )

    return [
        walk(view.topLevelItem(i))
        for i in range(view.topLevelItemCount())
    ]


def _add_all(cue_model, *cues):
    for index, cue in enumerate(cues):
        cue.index = index
        cue_model.add(cue)


def test_delete_top_level_group_removes_group_row(wired):
    cue_model, view, app = wired
    g = GroupCue(id="g", app=app)
    a = Cue(id="a", app=app)
    b = Cue(id="b", app=app)
    a.group_id = b.group_id = "g"
    g.children = ["a", "b"]
    _add_all(cue_model, g, a, b)
    assert _tree(view) == [("g", [("a", []), ("b", [])])]

    cue_model.remove(g)

    assert _tree(view) == [("a", []), ("b", [])]
    assert "g" not in view._group_items


def test_delete_nested_group_removes_group_row(wired):
    cue_model, view, app = wired
    o = GroupCue(id="o", app=app)
    i = GroupCue(id="i", app=app)
    a = Cue(id="a", app=app)
    b = Cue(id="b", app=app)
    i.group_id = "o"
    a.group_id = b.group_id = "i"
    o.children = ["i"]
    i.children = ["a", "b"]
    _add_all(cue_model, o, i, a, b)
    assert _tree(view) == [("o", [("i", [("a", []), ("b", [])])])]

    cue_model.remove(i)

    assert _tree(view) == [("o", [("a", []), ("b", [])])]


def test_delete_leaf_removes_its_own_row(wired):
    """Regression guard for the plain-cue path."""
    cue_model, view, app = wired
    g = GroupCue(id="g", app=app)
    a = Cue(id="a", app=app)
    b = Cue(id="b", app=app)
    c = Cue(id="c", app=app)
    a.group_id = b.group_id = "g"
    g.children = ["a", "b"]
    _add_all(cue_model, g, a, b, c)

    cue_model.remove(b)

    assert _tree(view) == [("g", [("a", [])]), ("c", [])]
