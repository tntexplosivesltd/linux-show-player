import gc

import pytest

from lisp.core.signal import Signal, Connection, slot_id


class TestSignalConnectEmit:
    def test_emit_calls_function(self):
        signal = Signal()
        results = []

        def handler(val):
            results.append(val)

        signal.connect(handler)
        signal.emit(42)
        assert results == [42]

    def test_emit_calls_method(self):
        signal = Signal()

        class Receiver:
            def __init__(self):
                self.received = []

            def handler(self, val):
                self.received.append(val)

        r = Receiver()
        signal.connect(r.handler)
        signal.emit("hello")
        assert r.received == ["hello"]

    def test_emit_multiple_args(self):
        signal = Signal()
        results = []

        def handler(a, b):
            results.append((a, b))

        signal.connect(handler)
        signal.emit(1, 2)
        assert results == [(1, 2)]

    def test_no_args_slot(self):
        """Signal emitting args can connect to slot with no params."""
        signal = Signal()
        called = []

        def handler():
            called.append(True)

        signal.connect(handler)
        signal.emit("ignored_arg")
        assert called == [True]


class TestSignalMultipleSlots:
    def test_multiple_handlers(self):
        signal = Signal()
        results = []

        def h1(v):
            results.append(("h1", v))

        def h2(v):
            results.append(("h2", v))

        signal.connect(h1)
        signal.connect(h2)
        signal.emit("x")
        assert ("h1", "x") in results
        assert ("h2", "x") in results

    def test_duplicate_connect_ignored(self):
        signal = Signal()
        results = []

        def handler(v):
            results.append(v)

        signal.connect(handler)
        signal.connect(handler)
        signal.emit(1)
        # Should only be called once
        assert results == [1]


class TestSignalDisconnect:
    def test_disconnect_specific(self):
        signal = Signal()
        results = []

        def handler(v):
            results.append(v)

        signal.connect(handler)
        signal.disconnect(handler)
        signal.emit(1)
        assert results == []

    def test_disconnect_all(self):
        signal = Signal()
        results = []

        def h1(v):
            results.append(v)

        def h2(v):
            results.append(v)

        signal.connect(h1)
        signal.connect(h2)
        signal.disconnect()
        signal.emit(1)
        assert results == []


class TestSignalWeakRef:
    def test_method_cleaned_on_gc(self):
        """Weak refs to methods get cleaned up when the object dies."""
        signal = Signal()

        class Obj:
            def handler(self):
                pass

        obj = Obj()
        signal.connect(obj.handler)
        del obj
        gc.collect()

        # Emitting should not raise — dead slot is silently skipped
        signal.emit()


class TestSignalConnectionModes:
    def test_invalid_mode_raises(self):
        signal = Signal()

        def handler():
            pass

        with pytest.raises(ValueError):
            signal.connect(handler, mode="invalid")


class TestSlotId:
    def test_function_id(self):
        def fn():
            pass

        sid = slot_id(fn)
        assert sid == id(fn)

    def test_method_id_is_tuple(self):
        class Obj:
            def method(self):
                pass

        obj = Obj()
        sid = slot_id(obj.method)
        assert isinstance(sid, tuple)
        assert len(sid) == 2

    def test_different_instances_different_ids(self):
        class Obj:
            def method(self):
                pass

        a, b = Obj(), Obj()
        assert slot_id(a.method) != slot_id(b.method)
