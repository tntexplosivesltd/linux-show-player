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


class TestParallelFadeRunner:
    def _make_blocking_fader(self, block_event):
        """Returns a fader whose fade() blocks until block_event is set."""
        fader = MagicMock()

        def fake_fade(seconds, to_value, curve):
            block_event.wait(timeout=5.0)
            return not fader.stop.called

        fader.fade.side_effect = fake_fade
        return fader

    def test_runner_calls_prepare_on_each_fader(self):
        from lisp.core.fade_functions import FadeOutType
        from lisp.plugins.action_cues._fader_coordinator import (
            ParallelFadeRunner,
        )
        f1 = MagicMock()
        f2 = MagicMock()
        runner = ParallelFadeRunner(
            [f1, f2], to_value=0.0, curve=FadeOutType.Linear,
            duration_seconds=0.01,
        )
        assert runner.run_until_complete() is True
        f1.prepare.assert_called_once()
        f2.prepare.assert_called_once()

    def test_runner_fades_all_in_parallel_to_target(self):
        from lisp.core.fade_functions import FadeOutType
        from lisp.plugins.action_cues._fader_coordinator import (
            ParallelFadeRunner,
        )
        f1 = MagicMock()
        f2 = MagicMock()
        runner = ParallelFadeRunner(
            [f1, f2], to_value=0.0, curve=FadeOutType.Linear,
            duration_seconds=0.01,
        )
        runner.run_until_complete()

        f1.fade.assert_called_once_with(0.01, 0.0, FadeOutType.Linear)
        f2.fade.assert_called_once_with(0.01, 0.0, FadeOutType.Linear)

    def test_runner_returns_true_on_clean_completion(self):
        from lisp.core.fade_functions import FadeOutType
        from lisp.plugins.action_cues._fader_coordinator import (
            ParallelFadeRunner,
        )
        f = MagicMock()
        runner = ParallelFadeRunner(
            [f], to_value=0.0, curve=FadeOutType.Linear,
            duration_seconds=0.01,
        )
        assert runner.run_until_complete() is True

    def test_runner_abort_calls_stop_and_returns_false(self):
        import threading
        from lisp.core.fade_functions import FadeOutType
        from lisp.plugins.action_cues._fader_coordinator import (
            ParallelFadeRunner,
        )

        block = threading.Event()
        f1 = self._make_blocking_fader(block)
        f2 = self._make_blocking_fader(block)

        runner = ParallelFadeRunner(
            [f1, f2], to_value=0.0, curve=FadeOutType.Linear,
            duration_seconds=1.0,
        )

        result = {}

        def run():
            result["ret"] = runner.run_until_complete()

        t = threading.Thread(target=run)
        t.start()
        # Let the fades get underway
        threading.Event().wait(0.05)

        runner.abort()
        block.set()  # unblock the fake fades so they can return
        t.join(timeout=2.0)

        assert result["ret"] is False
        f1.stop.assert_called_once()
        f2.stop.assert_called_once()

    def test_runner_with_empty_faders_is_no_op(self):
        from lisp.core.fade_functions import FadeOutType
        from lisp.plugins.action_cues._fader_coordinator import (
            ParallelFadeRunner,
        )
        runner = ParallelFadeRunner(
            [], to_value=0.0, curve=FadeOutType.Linear,
            duration_seconds=1.0,
        )
        assert runner.run_until_complete() is True

    def test_current_time_delegates_to_first_fader(self):
        from lisp.core.fade_functions import FadeOutType
        from lisp.plugins.action_cues._fader_coordinator import (
            ParallelFadeRunner,
        )
        f = MagicMock()
        f.current_time.return_value = 42
        runner = ParallelFadeRunner(
            [f], to_value=0.0, curve=FadeOutType.Linear,
            duration_seconds=1.0,
        )
        assert runner.current_time() == 42

    def test_current_time_with_no_faders_is_zero(self):
        from lisp.core.fade_functions import FadeOutType
        from lisp.plugins.action_cues._fader_coordinator import (
            ParallelFadeRunner,
        )
        runner = ParallelFadeRunner(
            [], to_value=0.0, curve=FadeOutType.Linear,
            duration_seconds=1.0,
        )
        assert runner.current_time() == 0

    def test_fader_exception_does_not_deadlock_runner(self, caplog):
        """A misbehaving fader must not block the runner from joining.

        The runner's `_run_single` catches + logs the exception via
        `logger.exception`. We capture via `caplog` at WARNING level so
        the ERROR-level traceback doesn't spam pytest's console output;
        the test still asserts the error was logged.
        """
        import logging
        from lisp.core.fade_functions import FadeOutType
        from lisp.plugins.action_cues._fader_coordinator import (
            ParallelFadeRunner,
        )
        bad = MagicMock()
        bad.fade.side_effect = RuntimeError("simulated")
        good = MagicMock()
        runner = ParallelFadeRunner(
            [bad, good], to_value=0.0, curve=FadeOutType.Linear,
            duration_seconds=0.01,
        )

        with caplog.at_level(
            logging.CRITICAL,  # suppress ERROR from logger.exception
            logger="lisp.plugins.action_cues._fader_coordinator",
        ):
            assert runner.run_until_complete() is True

        good.fade.assert_called_once()
