import pytest

from lisp.core.has_properties import HasProperties, HasInstanceProperties
from lisp.core.properties import Property, InstanceProperty


class SimpleObj(HasProperties):
    x = Property(default=10)
    y = Property(default="hello")


class ChildObj(SimpleObj):
    z = Property(default=True)


class TestHasPropertiesMeta:
    def test_properties_names(self):
        obj = SimpleObj()
        assert obj.properties_names() == {"x", "y"}

    def test_inheritance(self):
        obj = ChildObj()
        assert obj.properties_names() == {"x", "y", "z"}


class TestPropertiesDefaults:
    def test_instance_defaults(self):
        obj = SimpleObj()
        defaults = obj.properties_defaults()
        assert defaults == {"x": 10, "y": "hello"}

    def test_class_defaults(self):
        defaults = SimpleObj.class_defaults()
        assert defaults == {"x": 10, "y": "hello"}

    def test_child_class_defaults(self):
        defaults = ChildObj.class_defaults()
        assert defaults == {"x": 10, "y": "hello", "z": True}


class TestProperties:
    def test_get_properties(self):
        obj = SimpleObj()
        props = obj.properties()
        assert props == {"x": 10, "y": "hello"}

    def test_get_properties_no_defaults(self):
        obj = SimpleObj()
        props = obj.properties(defaults=False)
        assert props == {}

    def test_get_properties_after_change(self):
        obj = SimpleObj()
        obj.x = 99
        props = obj.properties(defaults=False)
        assert props == {"x": 99}

    def test_properties_with_filter(self):
        obj = SimpleObj()
        props = obj.properties_names(
            filter=lambda s: {n for n in s if n == "x"}
        )
        assert props == {"x"}


class TestUpdateProperties:
    def test_update(self):
        obj = SimpleObj()
        obj.update_properties({"x": 42, "y": "world"})
        assert obj.x == 42
        assert obj.y == "world"

    def test_update_ignores_unknown(self):
        obj = SimpleObj()
        obj.update_properties({"x": 1, "unknown": "ignored"})
        assert obj.x == 1
        assert not hasattr(obj, "unknown") or "unknown" not in (
            obj.properties_names()
        )


class TestChangedSignals:
    def test_property_changed_signal(self):
        obj = SimpleObj()
        changes = []

        def on_change(instance, name, value):
            changes.append((name, value))

        obj.property_changed.connect(on_change)
        obj.x = 99
        assert ("x", 99) in changes

    def test_named_changed_signal(self):
        obj = SimpleObj()
        values = []

        def on_x_changed(value):
            values.append(value)

        obj.changed("x").connect(on_x_changed)
        obj.x = 42
        assert values == [42]

    def test_changed_invalid_name_raises(self):
        obj = SimpleObj()
        with pytest.raises(ValueError):
            obj.changed("nonexistent")

    def test_changed_signal_cached(self):
        obj = SimpleObj()
        s1 = obj.changed("x")
        s2 = obj.changed("x")
        assert s1 is s2


class TestHasInstanceProperties:
    def test_instance_property(self):
        class Obj(HasInstanceProperties):
            def __init__(self):
                super().__init__()
                self.dynamic = InstanceProperty(default=5)

        obj = Obj()
        assert obj.dynamic == 5

    def test_instance_property_set(self):
        class Obj(HasInstanceProperties):
            def __init__(self):
                super().__init__()
                self.dynamic = InstanceProperty(default=0)

        obj = Obj()
        obj.dynamic = 42
        assert obj.dynamic == 42

    def test_instance_property_in_names(self):
        class Obj(HasInstanceProperties):
            x = Property(default=1)

            def __init__(self):
                super().__init__()
                self.dyn = InstanceProperty(default=2)

        obj = Obj()
        assert "dyn" in obj.properties_names()
        assert "x" in obj.properties_names()
