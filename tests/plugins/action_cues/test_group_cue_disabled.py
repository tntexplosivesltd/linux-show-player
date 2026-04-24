"""Tests for GroupCue's playable-children filter and its use in
playlist and parallel playback paths."""

from unittest.mock import MagicMock

import pytest

from lisp.cues.cue import Cue, CueAction, CueState
from lisp.plugins.action_cues.group_cue import GroupCue


def _group_with_children(mock_app, child_specs):
    """Build a GroupCue with stub children.

    `child_specs` is a list of (name, disabled) tuples.
    """
    group = GroupCue(app=mock_app)
    children = []
    mapping = {}
    for name, disabled in child_specs:
        c = Cue(app=mock_app)
        c.name = name
        c.disabled = disabled
        c.group_id = group.id
        children.append(c)
        mapping[c.id] = c
    group.children = [c.id for c in children]

    mock_app.cue_model = MagicMock()
    mock_app.cue_model.get.side_effect = lambda id: (
        group if id == group.id else mapping.get(id)
    )
    return group, children


class TestResolvePlayableChildren:
    def test_excludes_disabled(self, mock_app):
        group, children = _group_with_children(
            mock_app,
            [("A", False), ("B", True), ("C", False)],
        )

        playable = group._resolve_playable_children()

        names = [c.name for c in playable]
        assert names == ["A", "C"]

    def test_excludes_missing_children(self, mock_app):
        group, children = _group_with_children(
            mock_app,
            [("A", False), ("B", False)],
        )
        group.children = group.children + ["ghost-id"]

        playable = group._resolve_playable_children()

        assert len(playable) == 2

    def test_when_group_itself_disabled_all_children_skipped(
        self, mock_app,
    ):
        group, children = _group_with_children(
            mock_app,
            [("A", False), ("B", False)],
        )
        group.disabled = True

        playable = group._resolve_playable_children()

        assert playable == []

    def test_all_children_returned_when_none_disabled(self, mock_app):
        group, children = _group_with_children(
            mock_app,
            [("A", False), ("B", False)],
        )

        playable = group._resolve_playable_children()

        assert len(playable) == 2


class TestPlaylistSkipsDisabled:
    def test_playlist_start_skips_leading_disabled_child(
        self, mock_app,
    ):
        """Playlist [A(disabled), B, C] starts B, not A."""
        group, children = _group_with_children(
            mock_app,
            [("A", True), ("B", False), ("C", False)],
        )
        group.group_mode = "playlist"
        for c in children:
            c.execute = MagicMock()

        group._start_playlist(
            group._resolve_playable_children(), fade=False,
        )

        children[0].execute.assert_not_called()
        children[1].execute.assert_called_once()
        children[2].execute.assert_not_called()

    def test_playlist_advance_skips_disabled_middle_child(
        self, mock_app,
    ):
        """When B(disabled) comes between A and C, A -> C."""
        group, children = _group_with_children(
            mock_app,
            [("A", False), ("B", True), ("C", False)],
        )
        group.group_mode = "playlist"
        for c in children:
            c.execute = MagicMock()
        group._playlist_index = 0
        group._state = group._state | CueState.Running
        group._connected_children = set()
        group._disconnect_child = MagicMock()

        group._on_playlist_child_ended(children[0])

        children[1].execute.assert_not_called()
        children[2].execute.assert_called_once()


class TestParallelSkipsDisabled:
    def test_parallel_starts_only_enabled_children(self, mock_app):
        group, children = _group_with_children(
            mock_app,
            [("A", True), ("B", False), ("C", True)],
        )
        group.group_mode = "parallel"
        for c in children:
            c.execute = MagicMock()

        group._start_parallel(
            group._resolve_playable_children(), fade=False,
        )

        children[0].execute.assert_not_called()
        children[1].execute.assert_called_once()
        children[2].execute.assert_not_called()

    def test_parallel_with_all_children_disabled_is_noop(
        self, mock_app,
    ):
        group, children = _group_with_children(
            mock_app,
            [("A", True), ("B", True)],
        )
        group.group_mode = "parallel"
        for c in children:
            c.execute = MagicMock()

        result = group.execute()

        # execute returns None (guard triggers) when nothing is
        # playable. No child is fired.
        assert result is None
        for c in children:
            c.execute.assert_not_called()
