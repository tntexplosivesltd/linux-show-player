"""Unit tests for the _fader_coordinator helper module."""
from unittest.mock import MagicMock

from lisp.cues.cue import CueState
from lisp.cues.media_cue import MediaCue
from lisp.plugins.action_cues._fader_coordinator import (
    build_affected_set,
    collect_live_faders,
)
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


class TestCollectLiveFaders:
    def _make_media_with_elements(self, element_map, state=CueState.Running):
        """element_map: {'Volume': volume_el_or_None, 'VideoAlpha': ...}"""
        cue = MagicMock(spec=MediaCue)
        cue.state = state
        cue.media = MagicMock()
        cue.media.element = lambda name: element_map.get(name)
        return cue

    def test_media_with_only_volume(self):
        volume_fader = MagicMock(name="volume_fader")
        volume_el = MagicMock()
        volume_el.get_fader.return_value = volume_fader

        cue = self._make_media_with_elements({"Volume": volume_el})

        faders = collect_live_faders([cue])
        assert faders == [volume_fader]
        volume_el.get_fader.assert_called_once_with("live_volume")

    def test_media_with_volume_and_alpha(self):
        volume_fader = MagicMock(name="vf")
        alpha_fader = MagicMock(name="af")
        volume_el = MagicMock()
        volume_el.get_fader.return_value = volume_fader
        alpha_el = MagicMock()
        alpha_el.get_fader.return_value = alpha_fader

        cue = self._make_media_with_elements({
            "Volume": volume_el, "VideoAlpha": alpha_el,
        })

        faders = collect_live_faders([cue])
        assert volume_fader in faders
        assert alpha_fader in faders
        assert len(faders) == 2

    def test_media_with_neither_element(self):
        cue = self._make_media_with_elements({})
        assert collect_live_faders([cue]) == []

    def test_non_media_cue_skipped(self):
        non_media = MagicMock()
        non_media.state = CueState.Running
        del non_media.media  # no `media` attribute
        assert collect_live_faders([non_media]) == []

    def test_default_states_excludes_stopped(self):
        """Default `states=CueState.IsRunning` skips stopped cues."""
        volume_el = MagicMock()
        cue = self._make_media_with_elements(
            {"Volume": volume_el}, state=CueState.Stop
        )
        assert collect_live_faders([cue]) == []
        volume_el.get_fader.assert_not_called()

    def test_default_states_excludes_paused(self):
        """Default states skips paused cues too — StopCue only acts on
        running targets; ResumeCue opts in via the states param."""
        volume_el = MagicMock()
        cue = self._make_media_with_elements(
            {"Volume": volume_el}, state=CueState.Pause
        )
        assert collect_live_faders([cue]) == []

    def test_states_param_includes_paused_when_requested(self):
        """states=Pause|IsRunning collects faders from paused cues (this
        is how ResumeCue's happy path queries them)."""
        volume_fader = MagicMock(name="vf")
        volume_el = MagicMock()
        volume_el.get_fader.return_value = volume_fader

        cue = self._make_media_with_elements(
            {"Volume": volume_el}, state=CueState.Pause
        )

        faders = collect_live_faders(
            [cue], states=CueState.Pause | CueState.IsRunning
        )
        assert faders == [volume_fader]
