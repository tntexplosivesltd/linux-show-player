import threading

from lisp.core.decorators import memoize, locked_function, locked_method


class TestMemoize:
    def test_caches_result(self):
        call_count = 0

        @memoize
        def fn(x):
            nonlocal call_count
            call_count += 1
            return x * 2

        assert fn(5) == 10
        assert fn(5) == 10
        assert call_count == 1

    def test_different_args_not_cached(self):
        @memoize
        def fn(x):
            return x * 2

        assert fn(1) == 2
        assert fn(2) == 4

    def test_cache_attribute(self):
        @memoize
        def fn(x):
            return x

        fn(1)
        assert len(fn.cache) == 1


class TestLockedFunction:
    def test_basic_call(self):
        @locked_function
        def fn(x):
            return x + 1

        assert fn(5) == 6

    def test_thread_safety(self):
        results = []

        @locked_function
        def fn(val):
            results.append(val)

        threads = [threading.Thread(target=fn, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert sorted(results) == list(range(10))

    def test_with_custom_lock(self):
        lock = threading.RLock()

        @locked_function(lock=lock)
        def fn():
            return 42

        assert fn() == 42

    def test_non_blocking(self):
        @locked_function(blocking=False)
        def fn():
            return "ok"

        assert fn() == "ok"


class TestLockedMethod:
    def test_basic_call(self):
        class Obj:
            @locked_method
            def method(self, x):
                return x * 2

        assert Obj().method(5) == 10

    def test_per_instance_lock(self):
        class Obj:
            @locked_method
            def method(self):
                return id(self)

        a, b = Obj(), Obj()
        assert a.method() != b.method()
