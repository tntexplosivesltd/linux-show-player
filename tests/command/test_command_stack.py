from lisp.command.command import Command
from lisp.command.stack import CommandsStack


class StubCommand(Command):
    def __init__(self):
        self.did = 0
        self.undid = 0
        self.redid = 0

    def do(self):
        self.did += 1

    def undo(self):
        self.undid += 1

    def redo(self):
        self.redid += 1

    def log(self):
        return "stub"


class TestCommandsStackDo:
    def test_do_executes_command(self):
        stack = CommandsStack()
        cmd = StubCommand()
        stack.do(cmd)
        assert cmd.did == 1

    def test_do_emits_signal(self):
        stack = CommandsStack()
        done = []

        def on_done(c):
            done.append(c)

        stack.done.connect(on_done)
        cmd = StubCommand()
        stack.do(cmd)
        assert done == [cmd]


class TestCommandsStackUndo:
    def test_undo_last(self):
        stack = CommandsStack()
        cmd = StubCommand()
        stack.do(cmd)
        stack.undo_last()
        assert cmd.undid == 1

    def test_undo_empty_stack_noop(self):
        stack = CommandsStack()
        stack.undo_last()  # Should not raise

    def test_undo_emits_signal(self):
        stack = CommandsStack()
        undone = []

        def on_undone(c):
            undone.append(c)

        stack.undone.connect(on_undone)
        cmd = StubCommand()
        stack.do(cmd)
        stack.undo_last()
        assert undone == [cmd]


class TestCommandsStackRedo:
    def test_redo_last(self):
        stack = CommandsStack()
        cmd = StubCommand()
        stack.do(cmd)
        stack.undo_last()
        stack.redo_last()
        assert cmd.redid == 1

    def test_redo_empty_noop(self):
        stack = CommandsStack()
        stack.redo_last()  # Should not raise

    def test_do_clears_redo_stack(self):
        stack = CommandsStack()
        cmd1 = StubCommand()
        cmd2 = StubCommand()
        stack.do(cmd1)
        stack.undo_last()
        stack.do(cmd2)
        stack.redo_last()
        # cmd1 should not be redone since redo was cleared
        assert cmd1.redid == 0

    def test_redo_emits_signal(self):
        stack = CommandsStack()
        redone = []

        def on_redone(c):
            redone.append(c)

        stack.redone.connect(on_redone)
        cmd = StubCommand()
        stack.do(cmd)
        stack.undo_last()
        stack.redo_last()
        assert redone == [cmd]


class TestCommandsStackClear:
    def test_clear(self):
        stack = CommandsStack()
        stack.do(StubCommand())
        stack.clear()
        stack.undo_last()  # Should be noop
        stack.redo_last()  # Should be noop


class TestCommandsStackSaved:
    def test_is_saved_initially(self):
        stack = CommandsStack()
        assert stack.is_saved() is True

    def test_set_saved(self):
        stack = CommandsStack()
        cmd = StubCommand()
        stack.do(cmd)
        assert stack.is_saved() is False
        stack.set_saved()
        assert stack.is_saved() is True

    def test_not_saved_after_new_do(self):
        stack = CommandsStack()
        stack.do(StubCommand())
        stack.set_saved()
        stack.do(StubCommand())
        assert stack.is_saved() is False

    def test_saved_emits_signal(self):
        stack = CommandsStack()
        saved = []

        def on_saved():
            saved.append(True)

        stack.saved.connect(on_saved)
        stack.do(StubCommand())
        stack.set_saved()
        assert saved == [True]


class TestCommandsStackSize:
    def test_max_size(self):
        stack = CommandsStack(stack_size=2)
        cmd1, cmd2, cmd3 = StubCommand(), StubCommand(), StubCommand()
        stack.do(cmd1)
        stack.do(cmd2)
        stack.do(cmd3)  # cmd1 should be evicted
        stack.undo_last()
        stack.undo_last()
        stack.undo_last()  # noop — cmd1 already dropped
        assert cmd3.undid == 1
        assert cmd2.undid == 1
        assert cmd1.undid == 0  # was evicted from stack


class TestCommandDefaultRedo:
    def test_default_redo_calls_do(self):
        """Command.redo() default implementation calls self.do()."""

        class SimpleCommand(Command):
            def __init__(self):
                self.did = 0

            def do(self):
                self.did += 1

            def undo(self):
                pass

        cmd = SimpleCommand()
        cmd.redo()
        assert cmd.did == 1
