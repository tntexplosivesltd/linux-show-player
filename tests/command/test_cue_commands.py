"""Unit tests for `lisp.command.cue.UpdateCuesCommand`."""

import pytest

from lisp.command.cue import UpdateCuesCommand
from lisp.core.has_properties import HasProperties
from lisp.core.properties import Property


class _Cue(HasProperties):
    name = Property(default="")
    mapping = Property(default={})


def _cues():
    a, b = _Cue(), _Cue()
    a.name, a.mapping = "a", {"midi": 1}
    b.name, b.mapping = "b", {"midi": 2}
    return a, b


def test_one_dict_applies_to_every_cue():
    a, b = _cues()

    UpdateCuesCommand({"name": "x"}, [a, b]).do()

    assert (a.name, b.name) == ("x", "x")


def test_a_list_applies_one_dict_per_cue():
    a, b = _cues()

    UpdateCuesCommand(
        [{"mapping": {"midi": 1, "key": 9}}, {"mapping": {"midi": 2}}],
        [a, b],
    ).do()

    assert a.mapping == {"midi": 1, "key": 9}
    assert b.mapping == {"midi": 2}


def test_per_cue_undo_and_redo():
    a, b = _cues()
    command = UpdateCuesCommand([{"name": "x"}, {"name": "y"}], [a, b])

    command.do()
    command.undo()
    assert (a.name, b.name) == ("a", "b")

    command.redo()
    assert (a.name, b.name) == ("x", "y")


def test_list_length_must_match_the_cues():
    with pytest.raises(ValueError):
        UpdateCuesCommand([{"name": "x"}], list(_cues()))


def test_a_tuple_is_per_cue_too():
    a, b = _cues()

    UpdateCuesCommand(({"name": "x"}, {"name": "y"}), [a, b]).do()

    assert (a.name, b.name) == ("x", "y")


def test_per_cue_elements_must_be_dicts():
    with pytest.raises(TypeError):
        UpdateCuesCommand([{"name": "x"}, "oops"], list(_cues()))


def test_cues_may_be_a_generator():
    a, b = _cues()

    command = UpdateCuesCommand(
        [{"name": "x"}, {"name": "y"}], (cue for cue in (a, b))
    )
    command.do()
    command.undo()

    assert (a.name, b.name) == ("a", "b")


def test_mapping_types_survive_redo():
    from collections import OrderedDict
    from types import MappingProxyType

    a, b = _cues()
    command = UpdateCuesCommand(
        [OrderedDict(name="x"), MappingProxyType({"name": "y"})], [a, b]
    )
    command.do()
    command.undo()
    command.redo()

    assert (a.name, b.name) == ("x", "y")

    shared = UpdateCuesCommand(OrderedDict(name="z"), [a, b])
    shared.do()
    shared.undo()
    shared.redo()
    assert (a.name, b.name) == ("z", "z")


def test_nested_mapping_types_survive_redo():
    # `str()` writes a nested OrderedDict / mappingproxy / namedtuple
    # as a call, which `literal_eval` rejects, so normalising only the
    # top level isn't enough.
    from collections import OrderedDict, namedtuple
    from types import MappingProxyType

    Row = namedtuple("Row", "target action")
    a, b = _cues()
    command = UpdateCuesCommand(
        [
            {"mapping": OrderedDict(midi=OrderedDict(note=1))},
            {"mapping": MappingProxyType({"rows": [Row("x", "Start")]})},
        ],
        [a, b],
    )
    command.do()
    command.undo()
    command.redo()

    assert a.mapping == {"midi": {"note": 1}}
    assert b.mapping == {"rows": [("x", "Start")]}

    shared = UpdateCuesCommand(
        {"mapping": OrderedDict(midi=MappingProxyType({"note": 2}))}, [a, b]
    )
    shared.do()
    shared.undo()
    shared.redo()
    assert a.mapping == b.mapping == {"midi": {"note": 2}}


def test_empty_and_non_empty_per_cue_updates_mix():
    a, b = _cues()
    command = UpdateCuesCommand([{}, {"mapping": {"key": 1}}], [a, b])

    command.do()
    assert a.mapping == {"midi": 1}
    assert b.mapping == {"key": 1}

    command.undo()
    assert b.mapping == {"midi": 2}


def test_lists_of_tuples_round_trip_through_redo():
    a, b = _cues()
    rows = {"mapping": {"midi": [("a", "Start"), ("b", "Stop")]}}
    command = UpdateCuesCommand([rows, {}], [a, b])

    command.do()
    command.undo()
    command.redo()

    assert a.mapping == {"midi": [("a", "Start"), ("b", "Stop")]}
