"""Smoke tests for the hibernating icon variation."""
from lisp.ui.icons import IconTheme


def test_hibernating_entry_in_variations_dict():
    variations = IconTheme._CUE_TYPE_VARIATIONS
    assert "-hibernating" in variations
    entry = variations["-hibernating"]
    assert entry["fill"] == "#5AF"
    assert entry["stroke"] == "#5AF"
    assert entry["opacity"] == "1"


def test_hibernating_icon_loads_non_blank():
    IconTheme.set_theme_name("lisp")
    icon = IconTheme.get("speaker-hibernating")
    assert icon is not None
    assert not icon.isNull()


def test_hibernating_icon_loads_for_action_stop():
    IconTheme.set_theme_name("lisp")
    icon = IconTheme.get("action-stop-hibernating")
    assert icon is not None
    assert not icon.isNull()
