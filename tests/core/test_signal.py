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

    def test_emit_survives_gc_during_iteration(self):
        """A weakref-backed slot whose owner is dropped during emit
        (by another slot in the same emit, triggering GC) must not
        crash with `RuntimeError: dictionary changed size during
        iteration`.

        Regression test for the original race the snapshot fix
        addresses: __slots is mutated by __remove_slot when a
        weakref's _expired callback fires during GC, and the lock
        is reentrant so the GC callback can re-enter __remove_slot
        on the same thread that's iterating.
        """
        signal = Signal()
        order = []

        class Receiver:
            def __init__(self, name):
                self.name = name

            def handler(self, *_a, **_k):
                order.append(self.name)

        gc_target = [Receiver("victim")]

        def gc_trigger(*_a, **_k):
            # Drop the only strong reference to gc_target[0] so its
            # weakref can expire, then force GC. Pre-fix, this
            # caused __remove_slot to mutate __slots while emit was
            # iterating it.
            order.append("trigger")
            gc_target.clear()
            gc.collect()

        signal.connect(gc_trigger)
        signal.connect(gc_target[0].handler)

        # Must reach here without RuntimeError. The victim handler
        # may or may not run depending on emit's snapshot timing —
        # what matters is that the iteration completes cleanly.
        signal.emit()
        assert "trigger" in order

    def test_call_handles_weakref_expiring_between_check_and_call(self):
        """Slot.call must tolerate the weakref returning None
        between liveness check and invocation. Pre-fix this was a
        pure TypeError on `None()`; with snapshot-based emit
        releasing the lock before slot calls, the window is wider.
        """
        from lisp.core.signal import Slot

        class Obj:
            def handler(self):
                pass

        obj = Obj()
        slot = Slot(obj.handler)
        # Drop the only strong reference; the underlying WeakMethod
        # now resolves to None.
        del obj
        gc.collect()

        # Pre-fix this raised TypeError caught by the inner except
        # and warning-logged. Post-fix it's a clean no-op.
        slot.call()


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
