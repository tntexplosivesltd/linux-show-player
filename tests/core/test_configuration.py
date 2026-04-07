import json

import pytest

from lisp.core.configuration import (
    ConfDict,
    ConfDictError,
    DummyConfiguration,
    JSONFileConfiguration,
)


# NOTE: ConfDict.__traverse (configuration.py:122) does not propagate the
# set_ flag on recursive calls. This means auto-creating intermediate dicts
# only works one level deep.  The test_deep_nested_set_bug test documents
# this existing behavior.


class TestConfDict:
    def test_get_set_simple(self):
        cd = ConfDict(root={"a": 1})
        assert cd.get("a") == 1

    def test_set_new_key(self):
        cd = ConfDict()
        cd.set("x", 42)
        assert cd.get("x") == 42

    def test_nested_access(self):
        cd = ConfDict(root={"a": {"b": {"c": 99}}})
        assert cd.get("a.b.c") == 99

    def test_nested_set_one_level(self):
        cd = ConfDict()
        cd.set("a.b", "value")
        assert cd.get("a.b") == "value"

    def test_deep_nested_set_bug(self):
        """ConfDict.__traverse does not propagate set_ flag beyond depth 1.
        a.b gets auto-created but a.b.c raises because the recursive call
        to __traverse on line 122 drops set_=True."""
        cd = ConfDict()
        with pytest.raises(ConfDictError):
            cd.set("a.b.c", "value")

    def test_getitem_setitem(self):
        cd = ConfDict()
        cd["key"] = "val"
        assert cd["key"] == "val"

    def test_get_missing_raises(self):
        cd = ConfDict()
        with pytest.raises(ConfDictError):
            cd.get("missing")

    def test_get_missing_with_default(self):
        cd = ConfDict()
        assert cd.get("missing", default="fallback") == "fallback"

    def test_pop(self):
        cd = ConfDict(root={"a": 1})
        val = cd.pop("a")
        assert val == 1
        with pytest.raises(ConfDictError):
            cd.get("a")

    def test_delitem(self):
        cd = ConfDict(root={"a": 1})
        del cd["a"]
        with pytest.raises(ConfDictError):
            cd.get("a")

    def test_contains(self):
        cd = ConfDict(root={"a": {"b": 1}})
        assert "a.b" in cd
        assert "a.c" not in cd
        assert "missing" not in cd

    def test_update(self):
        cd = ConfDict(root={"a": 1, "b": 2})
        cd.update({"b": 99, "c": 3})
        assert cd.get("a") == 1
        assert cd.get("b") == 99
        assert cd.get("c") == 3

    def test_deep_copy(self):
        cd = ConfDict(root={"a": [1, 2]})
        copy = cd.deep_copy()
        copy["a"].append(3)
        assert cd.get("a") == [1, 2]

    def test_set_returns_true_on_change(self):
        cd = ConfDict(root={"a": 1})
        assert cd.set("a", 2) is True

    def test_set_returns_false_on_no_change(self):
        cd = ConfDict(root={"a": 1})
        assert cd.set("a", 1) is False

    def test_empty_separator_raises(self):
        with pytest.raises(ValueError):
            ConfDict(sep="")

    def test_non_str_separator_raises(self):
        with pytest.raises(TypeError):
            ConfDict(sep=123)

    def test_non_dict_root_raises(self):
        with pytest.raises(TypeError):
            ConfDict(root="not_a_dict")


class TestDummyConfiguration:
    def test_changed_signal(self):
        conf = DummyConfiguration(root={"a": 1})
        changes = []

        # Must use named function, not lambda (weakref!)
        def on_changed(path, value):
            changes.append((path, value))

        conf.changed.connect(on_changed)
        conf.set("a", 2)
        assert changes == [("a", 2)]

    def test_no_signal_on_same_value(self):
        conf = DummyConfiguration(root={"a": 1})
        changes = []

        def on_changed(path, value):
            changes.append((path, value))

        conf.changed.connect(on_changed)
        conf.set("a", 1)
        assert changes == []

    def test_updated_signal(self):
        conf = DummyConfiguration(root={"a": 1, "b": 2})
        updates = []

        def on_updated(diff):
            updates.append(diff)

        conf.updated.connect(on_updated)
        conf.update({"a": 99})
        assert updates == [{"a": 99}]

    def test_update_no_signal_if_same(self):
        conf = DummyConfiguration(root={"a": 1})
        updates = []

        def on_updated(diff):
            updates.append(diff)

        conf.updated.connect(on_updated)
        conf.update({"a": 1})
        assert updates == []

    def test_read_write_noop(self):
        conf = DummyConfiguration()
        conf.read()
        conf.write()


class TestJSONFileConfiguration:
    def test_read_write_roundtrip(self, tmp_path):
        default_path = tmp_path / "default.json"
        user_path = tmp_path / "user.json"

        default_data = {"_version_": "1", "setting": "value"}
        default_path.write_text(json.dumps(default_data))

        conf = JSONFileConfiguration(str(user_path), str(default_path))
        assert conf.get("setting") == "value"

        conf.set("setting", "new_value")
        conf.write()

        conf2 = JSONFileConfiguration(
            str(user_path), str(default_path)
        )
        assert conf2.get("setting") == "new_value"

    def test_version_mismatch_resets(self, tmp_path):
        default_path = tmp_path / "default.json"
        user_path = tmp_path / "user.json"

        default_path.write_text(
            json.dumps({"_version_": "2", "x": "new"})
        )
        user_path.write_text(
            json.dumps({"_version_": "1", "x": "old"})
        )

        conf = JSONFileConfiguration(str(user_path), str(default_path))
        assert conf.get("x") == "new"

    def test_missing_user_file_copies_default(self, tmp_path):
        default_path = tmp_path / "default.json"
        user_path = tmp_path / "user.json"

        default_path.write_text(json.dumps({"_version_": "1", "a": 1}))

        conf = JSONFileConfiguration(str(user_path), str(default_path))
        assert conf.get("a") == 1
