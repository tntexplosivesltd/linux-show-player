from lisp.core.properties import (
    Property,
    WriteOnceProperty,
    InstanceProperty,
)


class TestProperty:
    def test_default_value(self):
        class Obj:
            x = Property(default=42)
        assert Obj().x == 42

    def test_set_and_get(self):
        class Obj:
            x = Property(default=0)
        o = Obj()
        o.x = 99
        assert o.x == 99

    def test_instance_isolation(self):
        class Obj:
            x = Property(default=0)
        a, b = Obj(), Obj()
        a.x = 10
        assert b.x == 0

    def test_default_list_copied(self):
        class Obj:
            items = Property(default=[1, 2])
        a, b = Obj(), Obj()
        a.items.append(3)
        assert b.items == [1, 2]

    def test_default_dict_copied(self):
        class Obj:
            data = Property(default={"a": 1})
        a, b = Obj(), Obj()
        a.data["b"] = 2
        assert "b" not in b.data

    def test_class_access_returns_descriptor(self):
        class Obj:
            x = Property(default=0)
        assert isinstance(Obj.x, Property)

    def test_meta(self):
        p = Property(default=0, some_meta="value")
        assert p.meta == {"some_meta": "value"}


class TestWriteOnceProperty:
    def test_initial_write(self):
        class Obj:
            x = WriteOnceProperty()
        o = Obj()
        o.x = 42
        assert o.x == 42

    def test_second_write_ignored(self):
        class Obj:
            x = WriteOnceProperty()
        o = Obj()
        o.x = 42
        o.x = 99
        assert o.x == 42

    def test_default_none(self):
        class Obj:
            x = WriteOnceProperty()
        # Default is None, so first set works
        o = Obj()
        assert o.x is None


class TestInstanceProperty:
    def test_default_value(self):
        p = InstanceProperty(default=10)
        assert p.__pget__() == 10

    def test_set_value(self):
        p = InstanceProperty(default=0)
        p.__pset__(42)
        assert p.__pget__() == 42

    def test_default_preserved(self):
        p = InstanceProperty(default=5)
        p.__pset__(99)
        assert p.default == 5
