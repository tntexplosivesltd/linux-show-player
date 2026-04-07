from lisp.core.class_based_registry import ClassBasedRegistry


class TestClassBasedRegistry:
    def test_add_and_filter(self):
        reg = ClassBasedRegistry()
        reg.add("item", object)
        assert "item" in list(reg.filter(object))

    def test_subclass_filter(self):
        reg = ClassBasedRegistry()
        reg.add("object-item", object)
        reg.add("list-item", list)
        assert "list-item" in list(reg.filter(list))
        assert "object-item" in list(reg.filter(list))

    def test_filter_excludes_unrelated(self):
        reg = ClassBasedRegistry()
        reg.add("list-item", list)
        assert "list-item" not in list(reg.filter(dict))

    def test_duplicate_add_ignored(self):
        reg = ClassBasedRegistry()
        reg.add("item", object)
        reg.add("item", object)
        assert list(reg.filter(object)).count("item") == 1

    def test_remove(self):
        reg = ClassBasedRegistry()
        reg.add("item", object)
        reg.remove("item")
        assert "item" not in list(reg.filter(object))

    def test_clear(self):
        reg = ClassBasedRegistry()
        reg.add("a", object)
        reg.add("b", list)
        reg.clear()
        assert list(reg.filter(object)) == []

    def test_clear_class(self):
        reg = ClassBasedRegistry()
        reg.add("a", object)
        reg.add("b", object)
        reg.clear_class(object)
        assert list(reg.filter(object)) == []

    def test_ref_classes(self):
        reg = ClassBasedRegistry()
        reg.add("a", object)
        reg.add("b", list)
        assert set(reg.ref_classes()) == {object, list}
