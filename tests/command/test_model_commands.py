from unittest.mock import MagicMock, call

from lisp.command.model import (
    ModelAddItemsCommand,
    ModelRemoveItemsCommand,
    ModelMoveItemCommand,
)


class TestModelAddItemsCommand:
    def test_do_adds_items(self):
        model = MagicMock()
        items = [MagicMock(), MagicMock()]
        cmd = ModelAddItemsCommand(model, *items)
        cmd.do()
        assert model.add.call_count == 2

    def test_undo_removes_items(self):
        model = MagicMock()
        items = [MagicMock(), MagicMock()]
        cmd = ModelAddItemsCommand(model, *items)
        cmd.do()
        cmd.undo()
        assert model.remove.call_count == 2

    def test_redo_adds_again(self):
        model = MagicMock()
        item = MagicMock()
        cmd = ModelAddItemsCommand(model, item)
        cmd.do()
        cmd.undo()
        cmd.redo()
        assert model.add.call_count == 2  # do + redo


class TestModelRemoveItemsCommand:
    def test_do_removes_items(self):
        model = MagicMock()
        item = MagicMock()
        cmd = ModelRemoveItemsCommand(model, item)
        cmd.do()
        model.remove.assert_called_once_with(item)

    def test_undo_adds_back(self):
        model = MagicMock()
        item = MagicMock()
        cmd = ModelRemoveItemsCommand(model, item)
        cmd.do()
        cmd.undo()
        model.add.assert_called_once_with(item)


class TestModelMoveItemCommand:
    def test_do_moves(self):
        model = MagicMock()
        cmd = ModelMoveItemCommand(model, 0, 5)
        cmd.do()
        model.move.assert_called_once_with(0, 5)

    def test_undo_moves_back(self):
        model = MagicMock()
        cmd = ModelMoveItemCommand(model, 0, 5)
        cmd.do()
        cmd.undo()
        assert model.move.call_args_list == [call(0, 5), call(5, 0)]

    def test_redo(self):
        model = MagicMock()
        cmd = ModelMoveItemCommand(model, 2, 7)
        cmd.do()
        cmd.undo()
        cmd.redo()
        assert model.move.call_args_list == [
            call(2, 7),
            call(7, 2),
            call(2, 7),
        ]
