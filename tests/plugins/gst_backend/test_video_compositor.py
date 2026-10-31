"""Tests for VideoCompositor build-plan and register bookkeeping."""

from unittest.mock import MagicMock, patch

from lisp.plugins.gst_backend import video_compositor as vc


class TestPlanPipeline:
    def test_gl_plan_when_gl_available(self):
        # All GL factories present → GL plan.
        with patch.object(vc, "_have_factory", return_value=True):
            plan = vc.plan_pipeline()
        assert plan["gl"] is True
        assert plan["upload"] == "glupload"
        assert plan["mixer"] == "glvideomixer"
        assert plan["sink"] == "glimagesink"

    def test_fallback_plan_when_no_gl(self):
        # glvideomixer missing → system-memory fallback, no upload.
        def fake(name):
            return name in ("compositor", "xvimagesink")

        with patch.object(vc, "_have_factory", side_effect=fake):
            plan = vc.plan_pipeline()
        assert plan["gl"] is False
        assert plan["upload"] is None
        assert plan["mixer"] == "compositor"
        assert plan["sink"] == "xvimagesink"

    def test_fallback_sink_autovideosink_when_no_xv(self):
        def fake(name):
            return name == "compositor"

        with patch.object(vc, "_have_factory", side_effect=fake):
            plan = vc.plan_pipeline()
        assert plan["sink"] == "autovideosink"


def _fake_windows():
    out = MagicMock()
    out.window_handle.return_value = 111
    mon = MagicMock()
    mon.window_handle.return_value = 222
    return out, mon


class TestVideoCompositorLifecycle:
    def test_available_true_when_pipeline_reaches_playing(self):
        out, mon = _fake_windows()

        def fake_build(self):
            self.pipeline = MagicMock()
            self.mixer = MagicMock()
            self._clock = MagicMock()
            return True

        with patch.object(vc.VideoCompositor, "_build", fake_build):
            comp = vc.VideoCompositor(out, mon)
        assert comp.available is True
        assert comp.clock() is comp._clock

    def test_available_false_when_build_fails(self):
        out, mon = _fake_windows()
        with patch.object(
            vc.VideoCompositor, "_build", autospec=True,
            return_value=False,
        ):
            comp = vc.VideoCompositor(out, mon)
        assert comp.available is False

    def test_window_handles_captured_before_build(self):
        # winId() creates the native window; it must happen on the
        # constructing (main) thread, not in the streaming-thread
        # prepare-window-handle callback.
        out, mon = _fake_windows()
        seen = {}

        def fake_build(self):
            seen["handles"] = (self._output_handle, self._monitor_handle)
            return True

        with patch.object(vc.VideoCompositor, "_build", fake_build):
            vc.VideoCompositor(out, mon)
        assert seen["handles"] == (111, 222)


class TestRegistrationBookkeeping:
    def _comp(self):
        out, mon = _fake_windows()
        with patch.object(vc.VideoCompositor, "_build", autospec=True,
                          return_value=True):
            comp = vc.VideoCompositor(out, mon)
        comp.available = True
        return comp

    def test_register_records_and_returns_handle(self):
        comp = self._comp()
        sink = object()
        with patch.object(comp, "_attach",
                          return_value=vc.Registration()) as attach:
            reg = comp.register(sink)
        attach.assert_called_once_with(sink)
        assert reg is not None
        assert comp.is_registered(sink) is True

    def test_register_returns_none_when_unavailable(self):
        comp = self._comp()
        comp.available = False
        assert comp.register(object()) is None

    def test_register_twice_returns_same_handle(self):
        comp = self._comp()
        sink = object()
        with patch.object(comp, "_attach",
                          return_value=vc.Registration()) as attach:
            first = comp.register(sink)
            second = comp.register(sink)
        attach.assert_called_once()
        assert first is second

    def test_unregister_detaches_and_forgets(self):
        comp = self._comp()
        sink = object()
        with patch.object(comp, "_attach", return_value=vc.Registration()):
            comp.register(sink)
        with patch.object(comp, "_detach") as detach:
            comp.unregister(sink)
        detach.assert_called_once()
        assert comp.is_registered(sink) is False

    def test_unregister_is_idempotent(self):
        comp = self._comp()
        with patch.object(comp, "_detach") as detach:
            comp.unregister(object())  # never registered
        detach.assert_not_called()

    def test_active_others_true_when_another_registered(self):
        comp = self._comp()
        a, b = object(), object()
        with patch.object(comp, "_attach", return_value=vc.Registration()):
            comp.register(a)
        assert comp.active_others(b) is True  # a is active, b asks
        assert comp.active_others(a) is False  # only a itself active

    def test_active_others_false_when_nothing_registered(self):
        comp = self._comp()
        assert comp.active_others(object()) is False


class TestDetachOrder:
    """Pump contract 4: no pad probe; appsrc is NULLed before the
    mixer pad is released (a probe-based teardown deadlocks)."""

    def _comp(self):
        out, mon = _fake_windows()
        with patch.object(vc.VideoCompositor, "_build", autospec=True,
                          return_value=True):
            comp = vc.VideoCompositor(out, mon)
        comp.pipeline = MagicMock()
        comp.mixer = MagicMock()
        return comp

    def _reg(self):
        reg = vc.Registration()
        reg.appsrc = MagicMock()
        reg.upload = MagicMock()
        reg.mix_pad = MagicMock()
        return reg

    def test_detach_nulls_appsrc_before_release(self):
        comp = self._comp()
        reg = self._reg()
        calls = MagicMock()
        calls.attach_mock(reg.appsrc.set_state, "appsrc_null")
        calls.attach_mock(comp.mixer.release_request_pad, "release")
        comp._detach(reg)
        names = [c[0] for c in calls.mock_calls]
        assert names.index("appsrc_null") < names.index("release")
        reg.appsrc.set_state.assert_called_once_with(vc.Gst.State.NULL)
        comp.mixer.release_request_pad.assert_called_once_with(
            reg.mix_pad)
        comp.pipeline.remove.assert_any_call(reg.appsrc)
        comp.pipeline.remove.assert_any_call(reg.upload)

    def test_detach_adds_no_pad_probe(self):
        comp = self._comp()
        reg = self._reg()
        comp._detach(reg)
        pad = reg.upload.get_static_pad.return_value
        pad.add_probe.assert_not_called()

    def test_detach_without_upload(self):
        comp = self._comp()
        reg = self._reg()
        reg.upload = None
        comp._detach(reg)
        reg.appsrc.get_static_pad.return_value.unlink.assert_called_once_with(
            reg.mix_pad)
        comp.mixer.release_request_pad.assert_called_once_with(
            reg.mix_pad)


class TestLatencyHelpers:
    """Pump contract 3."""

    def test_query_min_latency_returns_min(self):
        pipeline = MagicMock()
        pipeline.query.return_value = True
        with patch.object(vc.Gst.Query, "new_latency") as new_q:
            new_q.return_value.parse_latency.return_value = (
                True, 86 * vc.Gst.MSECOND, vc.Gst.SECOND)
            assert vc.query_min_latency(pipeline) == 86 * vc.Gst.MSECOND

    def test_query_min_latency_zero_when_query_fails(self):
        pipeline = MagicMock()
        pipeline.query.return_value = False
        assert vc.query_min_latency(pipeline) == 0

    def test_projection_pts_formula(self):
        ms = vc.Gst.MSECOND
        # rt 2s, cue started 1.5s after projection, cue latency 0,
        # projection latency 86ms → offset = 1500 - 86.
        pts = vc.projection_pts(
            running_time=2000 * ms,
            cue_base=11500 * ms,
            proj_base=10000 * ms,
            latency_offset=-86 * ms,
        )
        assert pts == (2000 + 1500 - 86) * ms
