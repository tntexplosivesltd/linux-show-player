"""Tests for VideoCompositor build-plan and register bookkeeping."""

from unittest.mock import MagicMock, patch

from lisp.plugins.gst_backend import video_compositor as vc


class TestPlanPipeline:
    def test_gl_plan_when_gl_available(self):
        # All GL factories present → GL plan.
        with patch.object(vc, "_have_factory", return_value=True):
            plan = vc.plan_pipeline()
        assert plan["gl"] is True
        assert plan["upload"] == "glupload ! glcolorconvert"
        assert plan["sink"] == "glimagesink"

    def test_gl_plan_uses_mixer_element_not_bin(self):
        # glvideomixer is a GstGLMixerBin whose release_pad over-unrefs
        # on GStreamer 1.24: the first cue release frees the mixer and
        # the next cue's attach segfaults. Use the element directly.
        with patch.object(vc, "_have_factory", return_value=True):
            plan = vc.plan_pipeline()
        assert plan["mixer"] == "glvideomixerelement"

    def test_gl_plan_probes_the_factories_it_uses(self):
        probed = []

        def fake(name):
            probed.append(name)
            return True

        with patch.object(vc, "_have_factory", side_effect=fake):
            vc.plan_pipeline()
        for name in ("glupload", "glcolorconvert", "glvideomixerelement",
                     "glimagesink"):
            assert name in probed

    def test_fallback_plan_when_no_gl(self):
        # GL mixer missing → system-memory fallback, no upload.
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
        comp.pipeline = MagicMock()  # built (None means shut down)
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

    def test_unregister_forgets_then_detaches_after_linger(self):
        comp = self._comp()
        sched = _FakeScheduler(comp)
        sink = object()
        with patch.object(comp, "_attach", return_value=vc.Registration()):
            comp.register(sink)
        with patch.object(comp, "_detach") as detach:
            comp.unregister(sink)
            assert comp.is_registered(sink) is False
            detach.assert_not_called()  # lingering, not yet released
            sched.fire(vc.LINGER_MS)
        detach.assert_called_once()

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


class TestShutdown:
    """The projection pipeline must be NULLed at plugin finalize, before
    the session and Qt windows are torn down — otherwise its GL sinks
    keep rendering into dying X windows (BadDrawable, exit segfault)."""

    def _comp(self):
        out, mon = _fake_windows()

        def fake_build(self):
            self.pipeline = MagicMock()
            self.mixer = MagicMock()
            self._sync_handler = 42
            return True

        with patch.object(vc.VideoCompositor, "_build", fake_build):
            return vc.VideoCompositor(out, mon)

    def test_shutdown_nulls_pipeline_and_disables(self):
        comp = self._comp()
        pipeline = comp.pipeline
        comp.shutdown()
        pipeline.set_state.assert_called_once_with(vc.Gst.State.NULL)
        pipeline.get_bus.return_value.disconnect.assert_called_once_with(42)
        assert comp.available is False
        assert comp.register(object()) is None

    def test_shutdown_forgets_registrations(self):
        comp = self._comp()
        with patch.object(comp, "_attach", return_value=vc.Registration()):
            comp.register(object())
        comp.shutdown()
        assert comp.active_others(object()) is False

    def test_shutdown_is_idempotent(self):
        comp = self._comp()
        pipeline = comp.pipeline
        comp.shutdown()
        comp.shutdown()
        pipeline.set_state.assert_called_once()

    def test_shutdown_when_build_failed(self):
        out, mon = _fake_windows()
        with patch.object(vc.VideoCompositor, "_build", autospec=True,
                          return_value=False):
            comp = vc.VideoCompositor(out, mon)
        comp.shutdown()  # pipeline None — must not raise


class TestFitRect:
    """Cue video is scaled to fit the canvas, aspect preserved and
    centred — the mixer otherwise places it at native size at (0,0)."""

    def test_same_aspect_fills_canvas(self):
        assert vc.fit_rect(640, 360, 1, 1, 1920, 1080) == (0, 0, 1920, 1080)

    def test_small_4_3_is_pillarboxed(self):
        # 320x240 → height-bound: 1440x1080, centred horizontally.
        assert vc.fit_rect(320, 240, 1, 1, 1920, 1080) == (240, 0, 1440, 1080)

    def test_wide_is_letterboxed(self):
        # 2.39:1 → width-bound.
        x, y, w, h = vc.fit_rect(2390, 1000, 1, 1, 1920, 1080)
        assert (x, w) == (0, 1920)
        assert h == round(1920 * 1000 / 2390)
        assert y == (1080 - h) // 2

    def test_pixel_aspect_ratio_respected(self):
        # Anamorphic DV PAL 720x576 with PAR 64/45 is 16:9 on screen.
        assert vc.fit_rect(720, 576, 64, 45, 1920, 1080) == (0, 0, 1920, 1080)

    def test_degenerate_input_falls_back_to_full_canvas(self):
        assert vc.fit_rect(0, 0, 1, 1, 1920, 1080) == (0, 0, 1920, 1080)


class TestFitRegistration:
    def test_sets_mixer_pad_geometry_from_caps(self):
        out, mon = _fake_windows()
        with patch.object(vc.VideoCompositor, "_build", autospec=True,
                          return_value=True):
            comp = vc.VideoCompositor(out, mon)
        reg = vc.Registration()
        reg.mix_pad = MagicMock()
        caps = vc.Gst.Caps.from_string(
            "video/x-raw,width=320,height=240,"
            "pixel-aspect-ratio=1/1,framerate=30/1")
        comp.fit_registration(reg, caps)
        reg.mix_pad.set_property.assert_any_call("xpos", 240)
        reg.mix_pad.set_property.assert_any_call("ypos", 0)
        reg.mix_pad.set_property.assert_any_call("width", 1440)
        reg.mix_pad.set_property.assert_any_call("height", 1080)


class TestCanvasSizeFor:
    """Canvas follows the output window's render area (physical px)."""

    def test_plain(self):
        assert vc.canvas_size_for(1920, 1080, 1.0) == (1920, 1080)

    def test_windowed_odd_size_rounded_down_to_even(self):
        # The measured single-screen case: a near-square window.
        assert vc.canvas_size_for(1054, 1057, 1.0) == (1054, 1056)

    def test_hidpi_uses_physical_pixels(self):
        assert vc.canvas_size_for(1280, 800, 2.0) == (2560, 1600)

    def test_never_shown_widget_falls_back(self):
        # A QWidget that was never laid out reports 100x30.
        assert vc.canvas_size_for(100, 30, 1.0) == (
            vc.COMP_WIDTH, vc.COMP_HEIGHT)

    def test_zero_falls_back(self):
        assert vc.canvas_size_for(0, 0, 1.0) == (
            vc.COMP_WIDTH, vc.COMP_HEIGHT)


class TestCanvasCaps:
    """Canvas caps name the exact memory type. ``(ANY)`` features break
    live renegotiation on GStreamer 1.24: glvideomixer's internal
    glcolorconvert cannot fixate them and the pipeline errors with
    not-negotiated on the first canvas resize."""

    def test_gl_path_pins_gl_memory(self):
        caps = vc._canvas_caps(640, 480, gl=True)
        assert caps.get_features(0).contains("memory:GLMemory")
        assert not caps.get_features(0).is_any()

    def test_fallback_path_is_system_memory(self):
        caps = vc._canvas_caps(640, 480, gl=False)
        assert caps.get_features(0).contains("memory:SystemMemory")
        assert not caps.get_features(0).is_any()

    def test_size(self):
        struct = vc._canvas_caps(640, 480, gl=True).get_structure(0)
        assert struct.get_int("width") == (True, 640)
        assert struct.get_int("height") == (True, 480)


def _caps(width, height):
    return vc.Gst.Caps.from_string(
        f"video/x-raw,width={width},height={height},"
        "pixel-aspect-ratio=1/1,framerate=30/1")


class TestCanvasSizing:
    def _comp(self, canvas_size=None):
        out, mon = _fake_windows()

        def fake_build(self):
            self.pipeline = MagicMock()
            self.mixer = MagicMock()
            self._canvas_filter = MagicMock()
            self._bg_pad = MagicMock()
            return True

        kwargs = {} if canvas_size is None else {"canvas_size": canvas_size}
        with patch.object(vc.VideoCompositor, "_build", fake_build):
            return vc.VideoCompositor(out, mon, **kwargs)

    def _reg(self, comp, caps):
        reg = vc.Registration()
        reg.mix_pad = MagicMock()
        comp.fit_registration(reg, caps)
        reg.mix_pad.reset_mock()
        return reg

    def test_default_canvas_size(self):
        comp = self._comp()
        assert comp.canvas_size() == (vc.COMP_WIDTH, vc.COMP_HEIGHT)

    def test_fit_uses_current_canvas(self):
        # A 4:3 clip on a 4:3 canvas fills it — no stacked bars.
        comp = self._comp(canvas_size=(1024, 768))
        reg = vc.Registration()
        reg.mix_pad = MagicMock()
        comp.fit_registration(reg, _caps(320, 240))
        reg.mix_pad.set_property.assert_any_call("width", 1024)
        reg.mix_pad.set_property.assert_any_call("height", 768)
        assert reg.caps is not None

    def test_set_canvas_size_updates_filter_and_background(self):
        comp = self._comp()
        comp.set_canvas_size(1024, 768)
        assert comp.canvas_size() == (1024, 768)
        caps = comp._canvas_filter.set_property.call_args[0][1]
        struct = caps.get_structure(0)
        assert struct.get_int("width") == (True, 1024)
        assert struct.get_int("height") == (True, 768)
        comp._bg_pad.set_property.assert_any_call("width", 1024)
        comp._bg_pad.set_property.assert_any_call("height", 768)

    def test_set_canvas_size_refits_registrations(self):
        comp = self._comp()
        with patch.object(comp, "_attach",
                          side_effect=lambda s: self._reg(comp, _caps(320,
                                                                      240))):
            comp.register(object())
        reg = next(iter(comp._registrations.values()))
        comp.set_canvas_size(1024, 768)
        reg.mix_pad.set_property.assert_any_call("xpos", 0)
        reg.mix_pad.set_property.assert_any_call("width", 1024)

    def test_set_canvas_size_skips_unfitted_registration(self):
        comp = self._comp()
        reg = vc.Registration()
        reg.mix_pad = MagicMock()
        with patch.object(comp, "_attach", return_value=reg):
            comp.register(object())
        comp.set_canvas_size(1024, 768)  # reg.caps None — not fitted yet
        reg.mix_pad.set_property.assert_not_called()

    def test_set_canvas_size_noop_when_unchanged(self):
        comp = self._comp(canvas_size=(1024, 768))
        comp.set_canvas_size(1024, 768)
        comp._canvas_filter.set_property.assert_not_called()

    def test_set_canvas_size_after_shutdown_is_safe(self):
        comp = self._comp()
        comp.shutdown()
        comp.set_canvas_size(1024, 768)  # must not raise



class _FakeScheduler:
    """Stands in for GLib.timeout_add: records (ms, fn, args) and lets a
    test fire the callbacks scheduled for a given delay."""

    def __init__(self, comp):
        self.pending = []
        comp._schedule = self.add

    def add(self, ms, fn, *args):
        self.pending.append((ms, fn, args))
        return len(self.pending)

    def fire(self, ms):
        due = [p for p in self.pending if p[0] == ms]
        self.pending = [p for p in self.pending if p[0] != ms]
        for _ms, fn, args in due:
            fn(*args)


class TestHandoffLinger:
    """A stopped/ended cue's last frame stays on screen until the next
    cue's first frame is up (seamless playlist advance), or goes black
    after LINGER_MS when nothing follows (standalone stop/end)."""

    def _comp(self):
        out, mon = _fake_windows()

        def fake_build(self):
            self.pipeline = MagicMock()
            self.mixer = MagicMock()
            return True

        with patch.object(vc.VideoCompositor, "_build", fake_build):
            comp = vc.VideoCompositor(out, mon)
        return comp, _FakeScheduler(comp)

    def _register(self, comp, sink):
        with patch.object(comp, "_attach",
                          side_effect=lambda s: vc.Registration()):
            return comp.register(sink)

    def test_lingering_cue_does_not_block_next(self):
        comp, _ = self._comp()
        a, b = object(), object()
        self._register(comp, a)
        comp.unregister(a)
        assert comp.active_others(b) is False

    def test_standalone_end_goes_black_after_linger(self):
        comp, sched = self._comp()
        a = object()
        reg_a = self._register(comp, a)
        with patch.object(comp, "_detach") as detach:
            comp.unregister(a)
            sched.fire(vc.LINGER_MS)
        detach.assert_called_once_with(reg_a)

    def test_handoff_holds_until_successor_frame(self):
        comp, sched = self._comp()
        a, b = object(), object()
        reg_a = self._register(comp, a)
        with patch.object(comp, "_detach") as detach:
            comp.unregister(a)
            reg_b = self._register(comp, b)  # playlist advance
            sched.fire(vc.LINGER_MS)
            detach.assert_not_called()  # B has no frame yet: hold A
            comp.frame_ready(reg_b)
            sched.fire(vc.HANDOFF_RELEASE_MS)
        detach.assert_called_once_with(reg_a)

    def test_successor_already_showing_releases_at_linger(self):
        comp, sched = self._comp()
        a, b = object(), object()
        reg_a = self._register(comp, a)
        with patch.object(comp, "_detach") as detach:
            comp.unregister(a)
            reg_b = self._register(comp, b)
            comp.frame_ready(reg_b)
            sched.fire(vc.LINGER_MS)
            sched.fire(vc.HANDOFF_RELEASE_MS)
        detach.assert_called_once_with(reg_a)

    def test_cap_releases_if_successor_never_shows(self):
        comp, sched = self._comp()
        a, b = object(), object()
        reg_a = self._register(comp, a)
        with patch.object(comp, "_detach") as detach:
            comp.unregister(a)
            self._register(comp, b)
            sched.fire(vc.LINGER_MS)
            sched.fire(vc.LINGER_CAP_MS)
        detach.assert_called_once_with(reg_a)

    def test_release_is_idempotent(self):
        comp, sched = self._comp()
        a = object()
        self._register(comp, a)
        with patch.object(comp, "_detach") as detach:
            comp.unregister(a)
            sched.fire(vc.LINGER_MS)
            sched.fire(vc.LINGER_CAP_MS)
        detach.assert_called_once()

    def test_frame_ready_without_lingering_schedules_nothing(self):
        comp, sched = self._comp()
        reg = self._register(comp, object())
        comp.frame_ready(reg)
        assert sched.pending == []

    def test_reregister_while_lingering_attaches_fresh(self):
        # Playlist loop A→B→A: A's old registration may still linger.
        comp, sched = self._comp()
        a = object()
        first = self._register(comp, a)
        comp.unregister(a)
        second = self._register(comp, a)
        assert second is not first
        assert comp.is_registered(a) is True

    def test_timers_after_shutdown_are_harmless(self):
        comp, sched = self._comp()
        a = object()
        self._register(comp, a)
        comp.unregister(a)
        comp.shutdown()
        with patch.object(comp, "_detach") as detach:
            sched.fire(vc.LINGER_MS)
            sched.fire(vc.LINGER_CAP_MS)
        detach.assert_not_called()
