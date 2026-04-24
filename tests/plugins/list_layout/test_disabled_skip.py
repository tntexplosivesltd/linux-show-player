"""Tests for list-layout advance & chain loops skipping disabled
cues. We don't instantiate a real ListLayout — we exercise the skip
logic directly against a stubbed list model so the tests stay fast
and free of Qt event loops."""

from unittest.mock import MagicMock

import pytest

from lisp.cues.cue import Cue


class _StubModel:
    """Minimal stand-in for `CueListModel`: supports len() and
    `item(index)`. Items carry `index` attributes like real cues."""
    def __init__(self, cues):
        self._cues = cues
        for i, c in enumerate(cues):
            c.index = i

    def __len__(self):
        return len(self._cues)

    def item(self, index):
        return self._cues[index]


def _make_layout(mock_app, cues):
    """Wire up just enough of ListLayout that
    `_advance_standby_past_children` works in isolation."""
    from lisp.plugins.list_layout.layout import ListLayout

    layout = ListLayout.__new__(ListLayout)  # skip heavy __init__
    layout.app = mock_app
    layout._list_model = _StubModel(cues)
    layout._standby_index = 0

    def set_standby(idx):
        layout._standby_index = max(0, min(idx, len(cues) - 1))

    def standby_index():
        return layout._standby_index

    layout.set_standby_index = set_standby
    layout.standby_index = standby_index
    layout.standby_cue = lambda: (
        cues[layout._standby_index]
        if 0 <= layout._standby_index < len(cues)
        else None
    )
    return layout


def _cue(mock_app, name, disabled=False, group_id=""):
    c = Cue(app=mock_app)
    c.name = name
    c.disabled = disabled
    c.group_id = group_id
    return c


class TestAdvanceStandbyPastChildren:
    def test_skips_disabled_cue(self, mock_app):
        mock_app.cue_model = MagicMock()
        mock_app.cue_model.get.return_value = None  # no groups

        a = _cue(mock_app, "A")
        b = _cue(mock_app, "B", disabled=True)
        c = _cue(mock_app, "C")
        layout = _make_layout(mock_app, [a, b, c])

        layout._advance_standby_past_children(advance=1)

        assert layout.standby_index() == 2

    def test_skips_chain_of_disabled(self, mock_app):
        mock_app.cue_model = MagicMock()
        mock_app.cue_model.get.return_value = None

        cues = [
            _cue(mock_app, "A"),
            _cue(mock_app, "B", disabled=True),
            _cue(mock_app, "C", disabled=True),
            _cue(mock_app, "D"),
        ]
        layout = _make_layout(mock_app, cues)

        layout._advance_standby_past_children(advance=1)

        assert layout.standby_index() == 3

    def test_stops_at_end_when_all_downstream_disabled(
        self, mock_app,
    ):
        mock_app.cue_model = MagicMock()
        mock_app.cue_model.get.return_value = None

        cues = [
            _cue(mock_app, "A"),
            _cue(mock_app, "B", disabled=True),
        ]
        layout = _make_layout(mock_app, cues)

        # Should try to advance past B, hit the end, return cleanly.
        layout._advance_standby_past_children(advance=1)

        # Contract: no exception, no infinite loop; final index
        # stays inside the list.
        assert 0 <= layout.standby_index() < len(cues)
