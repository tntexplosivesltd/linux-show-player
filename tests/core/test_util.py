from lisp.core.util import (
    dict_merge,
    dict_merge_diff,
    time_tuple,
    strtime,
    compose_url,
    natural_keys,
    rgetattr,
    rsetattr,
    rhasattr,
    subdict,
    EqEnum,
    FunctionProxy,
)


class TestDictMerge:
    def test_simple_merge(self):
        a = {"x": 1}
        dict_merge(a, {"y": 2})
        assert a == {"x": 1, "y": 2}

    def test_overwrite(self):
        a = {"x": 1}
        dict_merge(a, {"x": 5})
        assert a == {"x": 5}

    def test_nested_merge(self):
        a = {"a": {"b": 1, "c": 2}}
        dict_merge(a, {"a": {"c": 99, "d": 3}})
        assert a == {"a": {"b": 1, "c": 99, "d": 3}}

    def test_nested_overwrite_with_non_dict(self):
        a = {"a": {"b": 1}}
        dict_merge(a, {"a": "flat"})
        assert a == {"a": "flat"}

    def test_empty_merge(self):
        a = {"x": 1}
        dict_merge(a, {})
        assert a == {"x": 1}


class TestDictMergeDiff:
    def test_identical(self):
        assert dict_merge_diff({"a": 1}, {"a": 1}) == {}

    def test_different_value(self):
        assert dict_merge_diff({"a": 1}, {"a": 2}) == {"a": 2}

    def test_new_key(self):
        assert dict_merge_diff({"a": 1}, {"b": 2}) == {"b": 2}

    def test_nested_diff(self):
        d1 = {"a": {"b": 1, "c": 2}}
        d2 = {"a": {"b": 1, "c": 99}}
        assert dict_merge_diff(d1, d2) == {"a": {"c": 99}}

    def test_nested_identical(self):
        d = {"a": {"b": 1}}
        assert dict_merge_diff(d, d) == {}


class TestTimeTuple:
    def test_zero(self):
        assert time_tuple(0) == (0, 0, 0, 0)

    def test_milliseconds_only(self):
        assert time_tuple(999) == (0, 0, 0, 999)

    def test_one_second(self):
        assert time_tuple(1000) == (0, 0, 1, 0)

    def test_complex(self):
        # 1h 1m 1s 1ms = 3661001
        assert time_tuple(3661001) == (1, 1, 1, 1)

    def test_large_hours(self):
        # 100 hours
        assert time_tuple(100 * 3600 * 1000) == (100, 0, 0, 0)


class TestStrtime:
    def test_zero_no_accuracy(self):
        assert strtime(0) == "00:00.00"

    def test_zero_accuracy_2(self):
        assert strtime(0, accurate=2) == "00:00.00"

    def test_with_hours(self):
        assert strtime(3661000) == "01:01:01"

    def test_minutes_seconds_no_accuracy(self):
        assert strtime(65000) == "01:05.00"

    def test_accuracy_1(self):
        assert strtime(1500, accurate=1) == "00:01.50"

    def test_accuracy_2(self):
        assert strtime(1230, accurate=2) == "00:01.23"


class TestComposeUrl:
    def test_basic(self):
        assert compose_url("http", "localhost", 8080) == (
            "http://localhost:8080/"
        )

    def test_with_path(self):
        assert compose_url("http", "host", 80, "/api") == (
            "http://host:80/api"
        )

    def test_path_without_leading_slash(self):
        assert compose_url("http", "host", 80, "api") == (
            "http://host:80/api"
        )


class TestNaturalKeys:
    def test_text_only(self):
        assert natural_keys("abc") == ["abc"]

    def test_number_only(self):
        assert natural_keys("123") == ["", 123, ""]

    def test_mixed(self):
        assert natural_keys("z23a") == ["z", 23, "a"]

    def test_sorting(self):
        items = ["item17", "item4", "item1"]
        items.sort(key=natural_keys)
        assert items == ["item1", "item4", "item17"]


class TestRattr:
    def test_rgetattr_simple(self):
        class Obj:
            x = 42
        assert rgetattr(Obj(), "x") == 42

    def test_rgetattr_nested(self):
        class A:
            pass
        a = A()
        a.b = A()
        a.b.c = 99
        assert rgetattr(a, "b.c") == 99

    def test_rgetattr_default(self):
        class A:
            pass
        assert rgetattr(A(), "missing", "default") == "default"

    def test_rsetattr(self):
        class A:
            pass
        a = A()
        a.b = A()
        a.b.c = 0
        rsetattr(a, "b.c", 42)
        assert a.b.c == 42

    def test_rhasattr_single_level_true(self):
        class A:
            x = 1
        assert rhasattr(A(), "x") is True

    def test_rhasattr_single_level_false(self):
        class A:
            pass
        assert rhasattr(A(), "missing") is False

    def test_rhasattr_nested_is_broken(self):
        """rhasattr uses reduce(hasattr, ...) which returns bool after
        first level, so nested lookups always return False."""
        class A:
            pass
        a = A()
        a.b = A()
        a.b.c = 42
        assert rhasattr(a, "b.c") is False


class TestSubdict:
    def test_existing_keys(self):
        assert subdict({"a": 1, "b": 2, "c": 3}, ["a", "c"]) == {
            "a": 1,
            "c": 3,
        }

    def test_missing_keys_excluded(self):
        assert subdict({"a": 1}, ["a", "b"]) == {"a": 1}


class TestEqEnum:
    def test_eq_with_value(self):
        class E(EqEnum):
            A = 10

        assert E.A == 10

    def test_neq_with_wrong_value(self):
        class E(EqEnum):
            A = 10

        assert E.A != 11

    def test_neq_different_enum(self):
        class E1(EqEnum):
            A = 10

        class E2(EqEnum):
            A = 10

        assert E1.A != E2.A

    def test_hashable(self):
        class E(EqEnum):
            A = 10

        d = {E.A: "value"}
        assert d[E.A] == "value"


class TestFunctionProxy:
    def test_callable(self):
        fp = FunctionProxy(lambda x: x * 2)
        assert fp(5) == 10

    def test_stores_function(self):
        def fn():
            return 42
        fp = FunctionProxy(fn)
        assert fp.function is fn
