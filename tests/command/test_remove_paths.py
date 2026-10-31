"""The user-facing delete paths must use RemoveCuesCommand.

ModelRemoveItemsCommand can't undo the group-hierarchy rewrites that
CueModel.pop() makes; reverting either call site to it would leave the
rest of the unit suite green, so pin both explicitly.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

from lisp.command.group import RemoveCuesCommand
from lisp.cues.cue_model import CueModel
from lisp.layout.cue_layout import CueLayout
from lisp.plugins.test_harness import handlers
from lisp.plugins.test_harness.dispatcher import Dispatcher


def test_layout_remove_cues_pushes_remove_cues_command():
    # CueLayout is abstract; _remove_cues only needs app + cue_model.
    app = MagicMock()
    layout = SimpleNamespace(app=app, cue_model=CueModel())

    CueLayout._remove_cues(layout, [MagicMock()])

    (command,), _ = app.commands_stack.do.call_args
    assert isinstance(command, RemoveCuesCommand)


def test_harness_cue_remove_pushes_remove_cues_command(monkeypatch):
    monkeypatch.setattr(
        handlers, "invoke_on_main_thread", lambda fn, timeout=10.0: fn()
    )
    cue = SimpleNamespace(id="c1")
    app = MagicMock()
    app.session = SimpleNamespace()
    app.cue_model.get.return_value = cue
    d = Dispatcher()
    handlers.register_all(d, app, signal_manager=None)

    d.dispatch({
        "jsonrpc": "2.0", "id": 1,
        "method": "cue.remove", "params": {"id": "c1"},
    })

    (command,), _ = app.commands_stack.do.call_args
    assert isinstance(command, RemoveCuesCommand)
