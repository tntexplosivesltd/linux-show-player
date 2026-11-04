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
