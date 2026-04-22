"""Unit tests for the _fader_coordinator helper module."""
from unittest.mock import MagicMock

from lisp.cues.media_cue import MediaCue
from lisp.plugins.action_cues._fader_coordinator import build_affected_set
from lisp.plugins.action_cues.group_cue import GroupCue


class TestBuildAffectedSet:
    def _make_media_cue(self, cue_id="media-1"):
        cue = MagicMock(spec=MediaCue)
        cue.id = cue_id
        return cue

    def test_single_media_target(self):
        target = self._make_media_cue()
        assert build_affected_set(target) == [target]

    def test_group_target_flattens_children(self):
        child_a = self._make_media_cue("a")
        child_b = self._make_media_cue("b")
        group = MagicMock(spec=GroupCue)
        group.id = "g1"
        group._resolve_children.return_value = [child_a, child_b]

        assert build_affected_set(group) == [child_a, child_b]

    def test_nested_group_flattens_recursively(self):
        leaf_a = self._make_media_cue("a")
        leaf_b = self._make_media_cue("b")

        inner = MagicMock(spec=GroupCue)
        inner.id = "inner"
        inner._resolve_children.return_value = [leaf_a, leaf_b]

        outer = MagicMock(spec=GroupCue)
        outer.id = "outer"
        outer._resolve_children.return_value = [inner]

        assert build_affected_set(outer) == [leaf_a, leaf_b]

    def test_non_running_still_included(self):
        """build_affected_set does NOT filter by state; the filter lives
        in collect_live_faders so the calling cue's action still fires on
        all children via the group cascade."""
        child = self._make_media_cue("any-state")
        group = MagicMock(spec=GroupCue)
        group.id = "g1"
        group._resolve_children.return_value = [child]

        assert build_affected_set(group) == [child]
