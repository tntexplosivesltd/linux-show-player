"""M74: a live fade must not be lost when no buffer reaches the sync
element in time, and must not clobber a level it no longer owns.

GstPropertyController.set() anchors its control points on the next
buffer through the sync element (the identity "handoff"). Right after
play() the sink can take over a second to start pulling (seen on CI's
PulseAudio, pos stuck at 0 in PLAYING), so the handoff never fired, the
points were never set, and a fade-in cue stayed at live_volume 0 -
silent - for its whole run.

The fix anchors on the current position when the handoff times out,
and pins a completed fade at its target. The pin is gated on the
controller's generation, so a fade that finishes after its cue was
stopped (Volume.stop) or after another fade took the controller over
leaves their level alone.
"""

import threading
import time
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from lisp.core.fade_functions import FadeInType, FadeOutType
from lisp.plugins.gst_backend.gi_repository import Gst
from lisp.plugins.gst_backend import gst_fader, gst_properties
from lisp.plugins.gst_backend.elements.volume import Volume
from lisp.plugins.gst_backend.gst_fader import GstFader
from lisp.plugins.gst_backend.gst_properties import GstPropertyController

S = Gst.SECOND


@pytest.fixture(autouse=True)
def short_sync_timeout(monkeypatch):
    monkeypatch.setattr(gst_properties, "SYNC_TIMEOUT", 0.05)
    # The fake pipelines below stay stalled at position 0: keep the
    # fader's wait for the stream-time ramp short.
    monkeypatch.setattr(gst_fader, "MAX_STREAM_LAG", 0.2)


def _pipeline(position_ns=None, state=Gst.State.PLAYING):
    """A pipeline stand-in: reports `state` and answers position
    queries with `position_ns` (None = the query fails)."""
    pipeline = MagicMock()
    pipeline.get_state.return_value = (
        Gst.StateChangeReturn.SUCCESS, state, Gst.State.VOID_PENDING,
    )
    if position_ns is None:
        pipeline.query_position.return_value = (False, 0)
    else:
        pipeline.query_position.return_value = (True, position_ns)
    return pipeline


def _controller(pipeline):
    """A controller on a real volume element whose sync element sees
    no buffer unless the test delivers one (nothing is flowing)."""
    volume = Gst.ElementFactory.make("volume", None)
    identity = Gst.ElementFactory.make("identity", None)
    return GstPropertyController(pipeline, volume, identity, "volume")


def _points(ctrl):
    return [
        (p.timestamp, round(p.value, 6))
        for p in ctrl._control_source.get_all()
    ]


def _buffer(pts):
    # The callback only reads `pts`.
    return SimpleNamespace(pts=pts)


def _wait_until(predicate, timeout=2.0):
    deadline = time.monotonic() + timeout
    while not predicate():
        assert time.monotonic() < deadline, "timed out waiting"
        time.sleep(0.005)


def _set_in_thread(ctrl, points):
    """Run set() on a worker (as the fader does) and wait until its
    handoff handler is connected. Returns (thread, result dict)."""
    result = {}
    thread = threading.Thread(
        target=lambda: result.setdefault("gen", ctrl.set(points))
    )
    thread.start()
    deadline = time.monotonic() + 1
    while ctrl._handoff_handle is None and time.monotonic() < deadline:
        time.sleep(0.001)
    assert ctrl._handoff_handle is not None
    return thread, result


class TestSyncTimeout:
    def test_anchors_at_current_position(self):
        ctrl = _controller(_pipeline(position_ns=5 * S))

        generation = ctrl.set({0: 0.0, 1000: 1.0})

        assert generation is not None
        assert _points(ctrl) == [(5 * S, 0.0), (6 * S, 1.0)]
        assert ctrl.delay == 0
        assert ctrl._handoff_handle is None

    def test_failed_query_waits_for_the_first_buffer(self):
        # Anchoring at 0 would put the ramp before the stream's start
        # for media with a start offset: wait for real data instead.
        ctrl = _controller(_pipeline(position_ns=None))

        generation = ctrl.set({0: 0.0, 1000: 1.0})

        assert generation is not None
        assert _points(ctrl) == []
        assert ctrl._handoff_handle is not None

        ctrl._set_control_points(None, _buffer(3 * S), generation)

        assert _points(ctrl) == [(3 * S, 0.0), (4 * S, 1.0)]
        assert ctrl._handoff_handle is None

    def test_not_playing_anchors_nothing(self):
        pipeline = _pipeline(position_ns=0, state=Gst.State.READY)
        ctrl = _controller(pipeline)

        generation = ctrl.set({0: 0.0, 1000: 1.0})

        assert generation is None
        assert _points(ctrl) == []
        assert ctrl._handoff_handle is None
        pipeline.query_position.assert_not_called()

    def test_late_handoff_after_fallback_is_ignored(self):
        ctrl = _controller(_pipeline(position_ns=5 * S))
        generation = ctrl.set({0: 0.0, 1000: 1.0})

        ctrl._set_control_points(None, _buffer(9 * S), generation)

        assert _points(ctrl) == [(5 * S, 0.0), (6 * S, 1.0)]
        assert ctrl.delay == 0


class TestHandoff:
    def test_handoff_anchors_at_buffer_pts(self, monkeypatch):
        monkeypatch.setattr(gst_properties, "SYNC_TIMEOUT", 5)
        pipeline = _pipeline(position_ns=2 * S)
        ctrl = _controller(pipeline)
        thread, result = _set_in_thread(ctrl, {0: 0.0, 1000: 1.0})

        ctrl._set_control_points(None, _buffer(3 * S), ctrl._generation)
        thread.join(1)

        assert not thread.is_alive()
        assert result["gen"] is not None
        assert _points(ctrl) == [(3 * S, 0.0), (4 * S, 1.0)]
        assert ctrl.delay == 1000
        assert ctrl._handoff_handle is None
        # The timeout fallback never ran.
        pipeline.get_state.assert_not_called()

    def test_failing_handoff_still_wakes_set(self, monkeypatch):
        monkeypatch.setattr(gst_properties, "SYNC_TIMEOUT", 5)
        pipeline = _pipeline(position_ns=0)
        pipeline.query_position.side_effect = RuntimeError("boom")
        ctrl = _controller(pipeline)
        thread, result = _set_in_thread(ctrl, {0: 0.0, 1000: 1.0})

        with pytest.raises(RuntimeError):
            ctrl._set_control_points(
                None, _buffer(3 * S), ctrl._generation
            )
        thread.join(1)

        assert not thread.is_alive()
        assert result["gen"] == ctrl._generation
        assert ctrl._handoff_handle is None

    def test_stale_generation_handoff_is_ignored(self):
        ctrl = _controller(_pipeline(position_ns=None))
        first = ctrl.set({0: 0.0, 1000: 1.0})
        ctrl.set({0: 0.5, 1000: 0.2})

        ctrl._set_control_points(None, _buffer(3 * S), first)

        assert _points(ctrl) == []


class TestOwnership:
    def test_reset_supersedes_the_fade(self):
        ctrl = _controller(_pipeline(position_ns=0))
        generation = ctrl.set({0: 0.0, 1000: 1.0})
        apply = MagicMock()

        ctrl.reset()

        assert ctrl.finish(generation, apply) is False
        apply.assert_not_called()
        assert _points(ctrl) == []

    def test_later_set_supersedes_the_fade(self):
        ctrl = _controller(_pipeline(position_ns=0))
        first = ctrl.set({0: 0.0, 1000: 1.0})
        ctrl.set({0: 0.5, 1000: 0.2})
        apply = MagicMock()

        assert ctrl.finish(first, apply) is False
        apply.assert_not_called()
        assert _points(ctrl) == [(0, 0.5), (S, 0.2)]

    def test_finish_clears_then_applies(self):
        ctrl = _controller(_pipeline(position_ns=0))
        generation = ctrl.set({0: 0.0, 1000: 1.0})
        seen = []

        assert ctrl.finish(
            generation, lambda: seen.append(_points(ctrl))
        ) is True
        assert seen == [[]]
        # Finished once: a second finish is a no-op.
        assert ctrl.finish(generation, MagicMock()) is False

    def test_finish_applies_even_if_clearing_fails(self):
        ctrl = _controller(_pipeline(position_ns=0))
        generation = ctrl.set({0: 0.0, 1000: 1.0})
        ctrl._control_source = MagicMock()
        ctrl._control_source.unset_all.side_effect = RuntimeError("boom")
        apply = MagicMock()

        with pytest.raises(RuntimeError):
            ctrl.finish(generation, apply)
        apply.assert_called_once()

    def test_unanchored_takeover_clears_the_old_points(self):
        # A second fade on a paused/stopped pipeline anchors nothing;
        # the fade it superseded can no longer finish(), so its points
        # must not stay bound with no owner (they would play out on
        # resume and ignore the newer fade).
        pipeline = _pipeline(position_ns=0)
        ctrl = _controller(pipeline)
        first = ctrl.set({0: 0.0, 1000: 1.0})
        assert _points(ctrl) != []

        pipeline.get_state.return_value = (
            Gst.StateChangeReturn.SUCCESS,
            Gst.State.PAUSED,
            Gst.State.VOID_PENDING,
        )
        assert ctrl.set({0: 1.0, 1000: 0.2}) is None

        assert _points(ctrl) == []
        assert ctrl.finish(first, MagicMock()) is False

    def test_reset_wakes_a_waiting_set(self, monkeypatch):
        monkeypatch.setattr(gst_properties, "SYNC_TIMEOUT", 5)
        ctrl = _controller(_pipeline(position_ns=0))
        thread, result = _set_in_thread(ctrl, {0: 0.0, 1000: 1.0})

        ctrl.reset()
        thread.join(1)

        assert not thread.is_alive()
        assert ctrl.finish(result["gen"], MagicMock()) is False
        assert _points(ctrl) == []


class TestRemaining:
    """How much of the anchored ramp is still ahead in stream time."""

    def test_stalled_stream_has_the_whole_ramp_left(self):
        ctrl = _controller(_pipeline(position_ns=0))
        generation = ctrl.set({0: 0.0, 500: 0.5, 1000: 1.0})

        assert ctrl.remaining(generation) == 1000

    def test_flowing_stream_counts_down(self):
        pipeline = _pipeline(position_ns=0)
        ctrl = _controller(pipeline)
        generation = ctrl.set({0: 0.0, 1000: 1.0})

        pipeline.query_position.return_value = (True, 600 * Gst.MSECOND)
        assert ctrl.remaining(generation) == 400
        pipeline.query_position.return_value = (True, 2 * S)
        assert ctrl.remaining(generation) == 0

    def test_failed_query_has_nothing_left(self):
        pipeline = _pipeline(position_ns=0)
        ctrl = _controller(pipeline)
        generation = ctrl.set({0: 0.0, 1000: 1.0})

        pipeline.query_position.return_value = (False, 0)
        assert ctrl.remaining(generation) == 0

    def test_unanchored_ramp_has_the_whole_ramp_left(self):
        # The position query failed, so the ramp waits for its first
        # buffer: none of it has played yet.
        ctrl = _controller(_pipeline(position_ns=None))
        generation = ctrl.set({0: 0.0, 1000: 1.0})

        assert ctrl.remaining(generation) == 1000

    def test_handoff_anchor_counts_the_sink_delay(self, monkeypatch):
        # The normal path: the anchor is the next buffer's pts, ahead
        # of the playback position by the downstream buffering.
        monkeypatch.setattr(gst_properties, "SYNC_TIMEOUT", 5)
        pipeline = _pipeline(position_ns=2 * S)
        ctrl = _controller(pipeline)
        thread, result = _set_in_thread(ctrl, {0: 0.0, 1000: 1.0})
        ctrl._set_control_points(None, _buffer(3 * S), ctrl._generation)
        thread.join(1)
        generation = result["gen"]
        assert ctrl.delay == 1000

        assert ctrl.remaining(generation) == 2000
        pipeline.query_position.return_value = (True, 3500 * Gst.MSECOND)
        assert ctrl.remaining(generation) == 500
        pipeline.query_position.return_value = (True, 4 * S)
        assert ctrl.remaining(generation) == 0

    def test_loop_wrap_ends_the_wait(self):
        # GstMedia loops with a non-flushing seek to start_time: the
        # position falls far behind the anchor and never reaches the
        # ramp's end, so there is nothing to wait for.
        pipeline = _pipeline(position_ns=5 * S)
        ctrl = _controller(pipeline)
        generation = ctrl.set({0: 0.0, 1000: 1.0})
        assert ctrl.remaining(generation) == 1000

        pipeline.query_position.return_value = (True, 300 * Gst.MSECOND)
        assert ctrl.remaining(generation) == 0

    def test_backward_seek_inside_the_ramp_ends_the_wait(self):
        pipeline = _pipeline(position_ns=5 * S)
        ctrl = _controller(pipeline)
        generation = ctrl.set({0: 0.0, 1000: 1.0})
        pipeline.query_position.return_value = (True, 5600 * Gst.MSECOND)
        assert ctrl.remaining(generation) == 400

        pipeline.query_position.return_value = (True, 5300 * Gst.MSECOND)
        assert ctrl.remaining(generation) == 0

    def test_paused_pipeline_ends_the_wait(self):
        # Stream time is frozen: waiting on it would only delay the
        # fade's end (and anything following it) by MAX_STREAM_LAG.
        pipeline = _pipeline(position_ns=0)
        ctrl = _controller(pipeline)
        generation = ctrl.set({0: 0.0, 1000: 1.0})

        pipeline.get_state.return_value = (
            Gst.StateChangeReturn.SUCCESS,
            Gst.State.PAUSED,
            Gst.State.VOID_PENDING,
        )
        assert ctrl.remaining(generation) == 0

    def test_superseded_fade_has_nothing_to_wait_for(self):
        ctrl = _controller(_pipeline(position_ns=0))
        generation = ctrl.set({0: 0.0, 1000: 1.0})
        ctrl.reset()

        assert ctrl.remaining(generation) is None
        assert ctrl.remaining(None) is None


def _volume(live, saved=1.0, pipeline=None):
    """A real Volume element whose controller sees a stalled playing
    pipeline (no buffers, position 0), as in M74."""
    volume = Volume(Gst.Pipeline())
    volume.volume_controller._pipeline = pipeline or _pipeline(0)
    volume.volume = saved
    volume.live_volume = live
    return volume


def _fade_in_thread(fader, duration, to_value, fade_type):
    fader.prepare()
    result = {}
    thread = threading.Thread(
        target=lambda: result.setdefault(
            "ended", fader.fade(duration, to_value, fade_type)
        )
    )
    thread.start()
    return thread, result


class TestFaderPinsTarget:
    def test_completed_fade_ends_at_target(self):
        volume = _volume(live=0.0)
        fader = GstFader(volume, "live_volume")
        fader.prepare()

        ended = fader.fade(0.1, 0.8, FadeInType.Linear)

        assert ended
        assert volume.live_volume == pytest.approx(0.8)
        assert _points(volume.volume_controller) == []

    def test_interrupted_fade_is_not_pinned(self):
        volume = _volume(live=0.0)
        fader = GstFader(volume, "live_volume")
        thread, result = _fade_in_thread(fader, 5.0, 0.8, FadeInType.Linear)

        _wait_until(lambda: volume.volume_controller._anchor is not None)
        fader.stop()
        thread.join(1)

        assert not thread.is_alive()
        assert result["ended"] is False
        assert volume.live_volume == pytest.approx(0.0)

    def test_fade_finishing_after_cue_stop_keeps_saved_volume(self):
        # A StopCue's Fade & Stop runs its own GstFader: the target
        # ending (or being stopped) mid-fade does not stop it. When it
        # completes it must not pin 0 over the level Volume.stop()
        # restored, or the cue's next plain GO plays silent.
        volume = _volume(live=1.0, saved=1.0)
        fader = GstFader(volume, "live_volume")
        thread, result = _fade_in_thread(fader, 1.0, 0, FadeOutType.Linear)

        # Stop only once the fade owns the controller.
        _wait_until(lambda: volume.volume_controller._anchor is not None)
        volume.stop()
        thread.join(2)

        assert result["ended"] is True
        assert volume.live_volume == pytest.approx(1.0)

    def test_overlapping_fade_keeps_the_later_level(self):
        # Every fader on a Volume shares its one controller: a fade
        # overtaken by a VolumeControl fade must not jump back to its
        # own target when its wall-clock duration runs out.
        volume = _volume(live=0.0)
        fade_in = GstFader(volume, "live_volume")
        thread, result = _fade_in_thread(fade_in, 1.5, 1.0, FadeInType.Linear)

        _wait_until(lambda: volume.volume_controller._anchor is not None)
        assert thread.is_alive()
        volume_control = GstFader(volume, "live_volume")
        volume_control.prepare()
        assert volume_control.fade(0.1, 0.3, FadeOutType.Linear)
        assert volume.live_volume == pytest.approx(0.3)
        thread.join(2)

        assert result["ended"] is True
        assert volume.live_volume == pytest.approx(0.3)

    def test_fade_on_stopped_pipeline_leaves_level(self):
        # A VolumeControl aimed at a stopped cue anchors nothing, so
        # it must not set that cue's starting level either.
        volume = _volume(
            live=0.5, pipeline=_pipeline(0, state=Gst.State.READY)
        )
        fader = GstFader(volume, "live_volume")
        fader.prepare()

        assert fader.fade(0.1, 0.0, FadeOutType.Linear)
        assert volume.live_volume == pytest.approx(0.5)


class TestFaderFollowsStreamTime:
    """The fader's timer runs on the wall clock, the ramp in stream
    time. After a stalled start (M74) the ramp ends later than the
    timer: pinning on the timer would jump the level up mid-ramp."""

    def test_waits_for_a_late_ramp_before_pinning(self, monkeypatch):
        monkeypatch.setattr(gst_fader, "MAX_STREAM_LAG", 5)
        pipeline = _pipeline(position_ns=0)
        volume = _volume(live=0.0, pipeline=pipeline)
        fader = GstFader(volume, "live_volume")
        started = time.monotonic()
        thread, result = _fade_in_thread(fader, 0.1, 0.8, FadeInType.Linear)

        # The wall-clock duration has passed but the stream has not
        # moved: the ramp is still ahead, so no pin yet.
        time.sleep(0.4)
        assert thread.is_alive()
        assert volume.live_volume == pytest.approx(0.0)

        # The stream reaches the ramp's end: the fade completes.
        pipeline.query_position.return_value = (True, 10 * S)
        thread.join(1)

        assert not thread.is_alive()
        assert result["ended"] is True
        assert time.monotonic() - started >= 0.4
        assert volume.live_volume == pytest.approx(0.8)

    def test_wait_is_bounded_when_the_stream_never_moves(self):
        # MAX_STREAM_LAG is 0.2 s here (fixture).
        volume = _volume(live=0.0)
        fader = GstFader(volume, "live_volume")
        fader.prepare()
        started = time.monotonic()

        assert fader.fade(0.1, 0.8, FadeInType.Linear)

        elapsed = time.monotonic() - started
        assert 0.25 <= elapsed < 2.0
        assert volume.live_volume == pytest.approx(0.8)

    def test_stop_during_the_wait_interrupts_without_pinning(
        self, monkeypatch
    ):
        monkeypatch.setattr(gst_fader, "MAX_STREAM_LAG", 5)
        volume = _volume(live=0.0)
        ctrl = volume.volume_controller
        waiting = threading.Event()
        remaining = ctrl.remaining

        def spy(generation):
            waiting.set()
            return remaining(generation)

        ctrl.remaining = spy
        fader = GstFader(volume, "live_volume")
        thread, result = _fade_in_thread(fader, 0.1, 0.8, FadeInType.Linear)

        # remaining() is only asked once the wall-clock wait is over.
        assert waiting.wait(2)
        fader.stop()
        thread.join(1)

        assert not thread.is_alive()
        assert result["ended"] is False
        assert volume.live_volume == pytest.approx(0.0)

    def test_healthy_stream_does_not_wait_extra(self, monkeypatch):
        # Handoff-anchored ramp, with the sink `delay` ahead, on a
        # stream that plays in real time: the fade ends at about
        # delay + duration, not at MAX_STREAM_LAG.
        monkeypatch.setattr(gst_properties, "SYNC_TIMEOUT", 5)
        monkeypatch.setattr(gst_fader, "MAX_STREAM_LAG", 5)
        pipeline = _pipeline(position_ns=0)
        t0 = time.monotonic()
        pipeline.query_position.side_effect = lambda fmt: (
            True,
            int((time.monotonic() - t0) * S),
        )
        volume = _volume(live=0.0, pipeline=pipeline)
        ctrl = volume.volume_controller
        fader = GstFader(volume, "live_volume")
        started = time.monotonic()
        thread, result = _fade_in_thread(fader, 0.3, 0.8, FadeInType.Linear)

        _wait_until(lambda: ctrl._handoff_handle is not None)
        position = int((time.monotonic() - t0) * S)
        ctrl._set_control_points(
            None, _buffer(position + 100 * Gst.MSECOND), ctrl._generation
        )
        thread.join(3)

        assert result["ended"] is True
        assert time.monotonic() - started < 1.0
        assert volume.live_volume == pytest.approx(0.8)

    def test_target_paused_mid_fade_does_not_wait(self, monkeypatch):
        # A VolumeControl fade is not stopped when its target pauses:
        # with the stream frozen it must still end on time.
        monkeypatch.setattr(gst_fader, "MAX_STREAM_LAG", 5)
        pipeline = _pipeline(position_ns=0)
        volume = _volume(live=0.0, pipeline=pipeline)
        fader = GstFader(volume, "live_volume")
        started = time.monotonic()
        thread, result = _fade_in_thread(fader, 0.2, 0.8, FadeInType.Linear)

        _wait_until(lambda: volume.volume_controller._anchor is not None)
        pipeline.get_state.return_value = (
            Gst.StateChangeReturn.SUCCESS,
            Gst.State.PAUSED,
            Gst.State.VOID_PENDING,
        )
        thread.join(3)

        assert result["ended"] is True
        assert time.monotonic() - started < 1.5

    def test_loop_wrap_mid_fade_does_not_wait(self, monkeypatch):
        monkeypatch.setattr(gst_fader, "MAX_STREAM_LAG", 5)
        pipeline = _pipeline(position_ns=5 * S)
        volume = _volume(live=1.0, pipeline=pipeline)
        fader = GstFader(volume, "live_volume")
        started = time.monotonic()
        thread, result = _fade_in_thread(fader, 0.2, 0, FadeOutType.Linear)

        _wait_until(lambda: volume.volume_controller._anchor is not None)
        pipeline.query_position.return_value = (True, 100 * Gst.MSECOND)
        thread.join(3)

        assert result["ended"] is True
        assert time.monotonic() - started < 1.5
        assert volume.live_volume == pytest.approx(0.0)


class _Target:
    """A target with a mock controller, to check what the fader asks
    of it."""

    def __init__(self, value):
        self.live_volume = value
        self.controller = MagicMock()
        self.controller.delay = 0

    def get_controller(self, attribute):
        return self.controller


class TestFaderErrors:
    def test_finish_error_is_logged_not_raised(self, caplog):
        target = _Target(0.0)
        target.controller.set.return_value = 1
        target.controller.remaining.return_value = 0
        target.controller.finish.side_effect = RuntimeError("boom")
        fader = GstFader(target, "live_volume")
        fader.prepare()

        assert fader.fade(0.05, 0.8, FadeInType.Linear)
        assert "Could not finish the fade" in caplog.text
        assert fader._generation is None

    def test_generation_is_consumed_after_a_fade(self):
        volume = _volume(live=0.0)
        fader = GstFader(volume, "live_volume")
        fader.prepare()

        assert fader.fade(0.05, 0.8, FadeInType.Linear)
        assert fader._generation is None


class TestRealHandoff:
    """The real wiring: connect() must hand the generation to the
    callback, and the handler must disconnect itself from inside its
    own emission on the streaming thread. No audio device: fakesink."""

    def test_buffer_anchors_through_the_real_signal(self, monkeypatch):
        monkeypatch.setattr(gst_properties, "SYNC_TIMEOUT", 5)
        pipeline = Gst.parse_launch(
            "audiotestsrc is-live=true ! identity name=sync"
            " ! volume name=vol ! fakesink sync=true"
        )
        ctrl = GstPropertyController(
            pipeline,
            pipeline.get_by_name("vol"),
            pipeline.get_by_name("sync"),
            "volume",
        )
        pipeline.set_state(Gst.State.PLAYING)
        try:
            pipeline.get_state(5 * Gst.SECOND)
            started = time.monotonic()

            generation = ctrl.set({0: 0.0, 1000: 1.0})

            assert time.monotonic() - started < 2
            assert generation == ctrl._generation
            assert ctrl._handoff_handle is None
            points = ctrl._control_source.get_all()
            assert len(points) == 2
            assert points[1].timestamp - points[0].timestamp == S
            assert ctrl._anchor == points[0].timestamp
        finally:
            pipeline.set_state(Gst.State.NULL)


class TestFaderNoOps:
    def test_fade_to_current_value_leaves_controller_alone(self):
        target = _Target(0.8)
        fader = GstFader(target, "live_volume")
        fader.prepare()

        assert fader.fade(0.05, 0.8, FadeInType.Linear)
        target.controller.set.assert_not_called()
        target.controller.finish.assert_not_called()
        assert target.live_volume == 0.8

    def test_zero_duration_fade_leaves_controller_alone(self):
        target = _Target(0.0)
        fader = GstFader(target, "live_volume")
        fader.prepare()

        assert fader.fade(0, 0.8, FadeInType.Linear)
        target.controller.set.assert_not_called()
        target.controller.finish.assert_not_called()
        assert target.live_volume == 0.0
