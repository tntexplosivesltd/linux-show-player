"""Status-icon selection — Hibernating must win over Pause."""
from unittest.mock import MagicMock

from lisp.cues.cue import CueState


class TestListLayoutStatusIcon:
    def _capture_icon_name(self, state):
        from lisp.plugins.list_layout.list_widgets import CueStatusIcons
        from lisp.plugins.list_layout import list_widgets as lw

        item = MagicMock()
        item.cue.icon = "speaker"
        item.cue.state = state

        captured = []

        class FakeIconTheme:
            @staticmethod
            def get(name):
                captured.append(name)
                icon = MagicMock()
                icon.isNull = lambda: False
                return icon

        original = lw.IconTheme
        lw.IconTheme = FakeIconTheme
        try:
            widget = CueStatusIcons.__new__(CueStatusIcons)
            widget._item = item
            widget.update = lambda: None
            widget.updateIcon()
        finally:
            lw.IconTheme = original
        return captured

    def test_hibernating_wins_over_pause(self):
        captured = self._capture_icon_name(
            CueState.Pause | CueState.Hibernating,
        )
        assert captured == ["speaker-hibernating"]

    def test_pause_only_still_uses_pause_variant(self):
        captured = self._capture_icon_name(CueState.Pause)
        assert captured == ["speaker-pause"]

    def test_running_unaffected(self):
        captured = self._capture_icon_name(CueState.Running)
        assert captured == ["speaker-running"]
