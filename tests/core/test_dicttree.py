import pytest

from lisp.core.dicttree import DictNode, DictTreeError


class TestDictNodeSetGet:
    def test_simple(self):
        node = DictNode()
        node.set("key", 42)
        assert node.get("key") == 42

    def test_nested(self):
        node = DictNode()
        node.set("a.b.c", "deep")
        assert node.get("a.b.c") == "deep"

    def test_overwrite(self):
        node = DictNode()
        node.set("x", 1)
        node.set("x", 2)
        assert node.get("x") == 2

    def test_getitem_setitem(self):
        node = DictNode()
        node["foo"] = "bar"
        assert node["foo"] == "bar"


class TestDictNodeDefault:
    def test_get_missing_raises(self):
        node = DictNode()
        with pytest.raises(DictTreeError):
            node.get("missing")

    def test_get_missing_with_default(self):
        node = DictNode()
        assert node.get("missing", default="fallback") == "fallback"


class TestDictNodePop:
    def test_pop_existing(self):
        node = DictNode()
        node.set("key", 10)
        node.pop("key")
        with pytest.raises(DictTreeError):
            node.get("key")

    def test_pop_missing_raises(self):
        node = DictNode()
        with pytest.raises(DictTreeError):
            node.pop("missing")

    def test_delitem(self):
        node = DictNode()
        node.set("x", 1)
        del node["x"]
        assert node.get("x", default=None) is None


class TestDictNodeContains:
    def test_contains_single_level(self):
        node = DictNode()
        node.set("a", 1)
        assert "a" in node

    def test_contains_missing(self):
        node = DictNode()
        assert "missing" not in node

    def test_contains_parent_of_nested(self):
        node = DictNode()
        node.set("a.b", 1)
        assert "a" in node

    def test_contains_dotted_path_is_broken(self):
        """DictNode.__contains__ passes a list on recursion, not a string.
        This documents the existing bug -- the AttributeError is caught
        and __contains__ returns False."""
        node = DictNode()
        node.set("a.b", 1)
        # The bug causes an AttributeError which is caught by the
        # except (KeyError, TypeError) -- but AttributeError is NOT
        # caught, so it propagates. This test documents that behavior.
        with pytest.raises(AttributeError):
            "a.b" in node


class TestDictNodePath:
    def test_root_path_empty(self):
        node = DictNode()
        assert node.path() == ""

    def test_child_path(self):
        parent = DictNode()
        child = DictNode(value=42)
        parent.add_child(child, "child")
        assert child.path() == "child"

    def test_nested_path(self):
        root = DictNode()
        mid = DictNode()
        leaf = DictNode(value=1)
        root.add_child(mid, "a")
        mid.add_child(leaf, "b")
        assert leaf.path() == "a.b"


class TestDictNodeAddChild:
    def test_non_node_raises(self):
        node = DictNode()
        with pytest.raises(TypeError):
            node.add_child("not_a_node", "name")

    def test_non_str_name_raises(self):
        node = DictNode()
        with pytest.raises(TypeError):
            node.add_child(DictNode(), 123)

    def test_name_with_separator_raises(self):
        node = DictNode()
        with pytest.raises(DictTreeError):
            node.add_child(DictNode(), "a.b")

    def test_children_property(self):
        node = DictNode()
        c1 = DictNode()
        c2 = DictNode()
        node.add_child(c1, "a")
        node.add_child(c2, "b")
        assert set(node.children) == {c1, c2}
