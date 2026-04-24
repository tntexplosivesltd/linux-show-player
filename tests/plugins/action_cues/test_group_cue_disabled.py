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

    def test_playlist_advance_after_leading_sibling_disabled(
        self, mock_app,
    ):
        """Operator disables an earlier-played sibling while a
        later child is playing. When the playing child ends, the
        next enabled child must still play (index drift guard).

        Timeline: [A, B, C] all enabled. A plays, ends, B starts.
        Operator disables A mid-B. B ends. _playlist_index is 1
        (B's position when playable = [A, B, C]). After A is
        disabled, playable = [B, C] and _playlist_index=1 would
        naively point past B's current position. C must still
        play; fix locates the ended child by id in the full list.
        """
        group, children = _group_with_children(
            mock_app,
            [("A", False), ("B", False), ("C", False)],
        )
        group.group_mode = "playlist"
        for c in children:
            c.execute = MagicMock()
        # Simulate: B is the currently-playing child (index 1 in
        # the full enabled playable list), A was played before.
        group._playlist_index = 1
        group._state = group._state | CueState.Running
        group._connected_children = set()
        group._disconnect_child = MagicMock()

        # Now operator disables A.
        children[0].disabled = True

        # B ends naturally.
        group._on_playlist_child_ended(children[1])

        # C (index 2 in full list, index 1 in post-disable
        # playable list) must fire; B must not re-fire.
        children[0].execute.assert_not_called()
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

        # Explicit Start — exercises the guard directly (Default
        # would remap through super().execute() and then hit
        # exclusive_manager mocks that would add noise).
        group.execute(CueAction.Start)

        # Guard fires: no playable children, no child fired.
        for c in children:
            c.execute.assert_not_called()

    def test_default_on_running_disabled_group_reaches_stop(
        self, mock_app,
    ):
        """A group that's playing when disabled must still be
        stoppable via CueAction.Default — otherwise Stop All /
        operator-triggered Default on the group would be swallowed
        by the playable-children guard."""
        group, children = _group_with_children(
            mock_app,
            [("A", False), ("B", False)],
        )
        group.group_mode = "parallel"
        # Group is in Running state and becomes disabled (so
        # _resolve_playable_children() == [] for the cascade).
        group._state = CueState.Running
        group.disabled = True
        group.stop = MagicMock()

        # Set up app managers so Cue.execute's exclusive block
        # does not interfere (it short-circuits on start actions
        # that would transition; we're testing a stop action).
        mock_app.exclusive_manager = MagicMock()
        mock_app.exclusive_manager.is_start_blocked.return_value = False
        mock_app.video_exclusive_manager = MagicMock()
        mock_app.video_exclusive_manager.is_start_blocked.return_value = False

        group.execute(CueAction.Default)

        group.stop.assert_called_once()
