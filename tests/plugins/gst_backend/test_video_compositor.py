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
        sink = object()
        with patch.object(comp, "_attach", return_value=vc.Registration()):
            comp.register(sink)
        comp.shutdown()
        assert comp.is_registered(sink) is False

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
        self.removed = []
        self._next_id = 0
        comp._schedule = self.add
        comp._unschedule = self.remove

    def add(self, ms, fn, *args):
        self._next_id += 1
        self.pending.append((ms, fn, args, self._next_id))
        return self._next_id

    def remove(self, timer_id):
        self.removed.append(timer_id)
        self.pending = [p for p in self.pending if p[3] != timer_id]

    def fire(self, ms):
        due = [p for p in self.pending if p[0] == ms]
        self.pending = [p for p in self.pending if p[0] != ms]
        for _ms, fn, args, _id in due:
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

    def test_lingering_cue_is_no_longer_registered(self):
        comp, _ = self._comp()
        a = object()
        self._register(comp, a)
        comp.unregister(a)
        assert comp.is_registered(a) is False

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

    def test_frame_ready_from_unregistered_reg_releases_nothing(self):
        # A's stop raced its own first frame: A is lingering, and its
        # late frame_ready must not hand off (release) its peers.
        comp, sched = self._comp()
        a, b = object(), object()
        reg_a = self._register(comp, a)
        comp.unregister(a)
        self._register(comp, b)
        sched.pending.clear()
        comp.frame_ready(reg_a)
        assert sched.pending == []
        assert reg_a.frame_seen is False

    def test_shutdown_cancels_pending_timers(self):
        comp, sched = self._comp()
        a = object()
        self._register(comp, a)
        comp.unregister(a)  # schedules linger + cap
        assert len(sched.pending) == 2
        comp.shutdown()
        assert sched.pending == []
        assert len(sched.removed) == 2

    def test_fired_timer_is_not_cancelled_again(self):
        comp, sched = self._comp()
        a = object()
        self._register(comp, a)
        comp.unregister(a)
        sched.fire(vc.LINGER_MS)  # releases (no successor)
        comp.shutdown()
        assert len(sched.removed) == 1  # only the cap timer


def _drain(sched):
    """Fire every pending timer, earliest delay first, including timers
    the callbacks schedule, until none are left."""
    while sched.pending:
        sched.fire(min(p[0] for p in sched.pending))


class TestRegistrationChurn:
    """Many register/unregister cycles, in the patterns a show
    produces (playlist hand-offs, standalone stops, a stop racing the
    first frame, quick restarts), must leave nothing behind: no
    registrations, lingering regs, tracked timers or pending
    callbacks, and every branch detached exactly once."""

    def _comp(self):
        comp, sched = TestHandoffLinger._comp(self)
        detached = []
        real_detach = comp._detach

        def detach(reg):
            detached.append(reg)
            real_detach(reg)  # against the MagicMock pipeline/mixer

        comp._detach = detach
        return comp, sched, detached

    def _attach(self, _sink):
        reg = vc.Registration()
        reg.appsrc = MagicMock()
        reg.upload = MagicMock()
        reg.mix_pad = MagicMock()
        return reg

    def test_churn_leaks_nothing(self):
        import random

        rng = random.Random(1234)  # reproducible mix of patterns
        comp, sched, detached = self._comp()
        attached = []

        def attach(sink):
            reg = self._attach(sink)
            attached.append(reg)
            return reg

        current = None
        with patch.object(comp, "_attach", side_effect=attach):
            for _ in range(300):
                sink = object()
                reg = comp.register(sink)
                pattern = rng.choice(
                    ("handoff", "standalone", "race", "restart"))
                if pattern == "race" and current is not None:
                    comp.unregister(current)  # stop before 1st frame
                    comp.frame_ready(reg)
                else:
                    comp.frame_ready(reg)
                    if current is not None:
                        comp.unregister(current)
                if pattern == "restart":
                    comp.unregister(sink)
                    reg = comp.register(sink)  # fresh attach
                    comp.frame_ready(reg)
                if rng.random() < 0.5:
                    _drain(sched)  # sometimes timers interleave
                current = sink
            comp.unregister(current)
        _drain(sched)

        assert comp._registrations == {}
        assert comp._lingering == []
        assert comp._timers == set()
        assert sched.pending == []
        assert len(attached) == len(detached)
        assert {id(r) for r in attached} == {id(r) for r in detached}


class TestSessionReload:
    """A session reload disposes the playing cue while its frame
    lingers, and the new session can register a cue straight away.
    The old reg must go exactly once (handed off to the new cue's first
    frame, or by its own timers), and the new cue must be untouched by
    the old one's late timers. Real VideoSinks (never started: no
    audio) drive the dispose → unregister path."""

    _CM = ("lisp.plugins.gst_backend.gst_backend.GstBackend."
           "video_compositor")

    def _setup(self):
        from lisp.plugins.gst_backend.elements.video_sink import (
            VideoSink,
        )

        comp, sched, detached = TestRegistrationChurn._comp(self)
        regs = {}

        def attach(sink):
            reg = TestRegistrationChurn._attach(self, sink)
            regs[sink] = reg
            return reg

        comp._attach = attach

        def sink():
            return VideoSink(vc.Gst.Pipeline())

        return comp, sched, detached, regs, sink

    def test_dispose_during_linger_then_new_registration(self):
        comp, sched, detached, regs, make_sink = self._setup()
        old, new = make_sink(), make_sink()
        with patch(self._CM, return_value=comp):
            old.play()
            comp.frame_ready(regs[old])
            old.dispose()  # session teardown: lingers
            new.play()  # new session, immediately
        assert comp.is_registered(new)
        assert regs[old] in comp._lingering
        comp.frame_ready(regs[new])  # new cue's first frame
        _drain(sched)
        assert detached == [regs[old]]  # once, and only the old one
        assert comp.is_registered(new)
        assert comp._lingering == []
        assert comp._timers == set()

    def test_new_cue_without_frames_old_reg_released_by_cap(self):
        # The new session's cue never shows a frame (e.g. paused at
        # once): the old frame must not stay up forever.
        comp, sched, detached, regs, make_sink = self._setup()
        old, new = make_sink(), make_sink()
        with patch(self._CM, return_value=comp):
            old.play()
            comp.frame_ready(regs[old])
            old.dispose()
            new.play()
        sched.fire(vc.LINGER_MS)
        assert detached == []  # waits for the successor's frame
        sched.fire(vc.LINGER_CAP_MS)
        assert detached == [regs[old]]
        assert comp.is_registered(new)
        _drain(sched)
        assert detached == [regs[old]]


class TestFailedBuild:
    """_build can fail after creating the pipeline (Phase 7 #3)."""

    def _comp(self):
        out, mon = _fake_windows()
        built = {}

        def fake_build(self):
            self.pipeline = built["pipeline"] = MagicMock()
            return False  # e.g. a link failed after Pipeline.new()

        with patch.object(vc.VideoCompositor, "_build", fake_build):
            comp = vc.VideoCompositor(out, mon)
        return comp, built["pipeline"]

    def test_half_built_pipeline_is_dropped(self):
        comp, pipeline = self._comp()
        assert comp.available is False
        assert comp.pipeline is None
        pipeline.set_state.assert_called_once_with(vc.Gst.State.NULL)

    def test_set_canvas_size_after_failed_build_is_safe(self):
        comp, _ = self._comp()
        comp.set_canvas_size(1024, 768)  # must not raise
        assert comp.canvas_size() == (1024, 768)


class TestBuildRaises:
    """A _build() step that raises rather than returning False must
    degrade to an unavailable compositor (audio only), not propagate
    and take the whole GstBackend down. The real _build runs; each
    failure is injected before the pipeline is started."""

    def test_missing_capsfilter_degrades(self):
        real_make = vc.Gst.ElementFactory.make

        def make(factory, name):
            if factory == "capsfilter":
                return None
            return real_make(factory, name)

        out, mon = _fake_windows()
        with patch.object(vc.Gst.ElementFactory, "make",
                          side_effect=make):
            comp = vc.VideoCompositor(out, mon)
        assert comp.available is False
        assert comp.pipeline is None

    def test_upload_bin_parse_error_degrades(self):
        plan = {"gl": True, "upload": "glupload ! glcolorconvert",
                "mixer": "compositor", "sink": "fakesink"}
        out, mon = _fake_windows()
        with patch.object(vc, "plan_pipeline", return_value=plan), \
                patch.object(vc, "_make_upload", side_effect=vc.GLib.Error(
                    "no element \"glupload\"")):
            comp = vc.VideoCompositor(out, mon)
        assert comp.available is False
        assert comp.pipeline is None


class TestAppsrcBounds:
    """Each cue's appsrc queue is bounded by time and leaks the
    oldest frame, so a stalled projection cannot grow it forever."""

    def test_real_appsrc_configuration(self):
        appsrc = vc.Gst.ElementFactory.make("appsrc", None)
        vc._configure_appsrc(appsrc)
        assert appsrc.get_property("max-time") == vc.APPSRC_MAX_QUEUE_TIME
        # Not the 200kB byte default (< one 1080p frame); the buffer
        # count is only a generous backstop (see below).
        assert appsrc.get_property("max-bytes") == 0
        assert (appsrc.get_property("max-buffers")
                == vc.APPSRC_MAX_QUEUE_BUFFERS)
        assert (appsrc.get_property("leaky-type")
                == vc.GstApp.AppLeakyType.DOWNSTREAM)
        assert appsrc.get_property("is-live") is True
        assert appsrc.get_property("max-latency") == vc.APPSRC_MAX_LATENCY

    def test_queue_bound_exceeds_pump_lead(self):
        from lisp.plugins.gst_backend.elements.video_sink import PUMP_LEAD

        assert vc.APPSRC_MAX_QUEUE_TIME >= 3 * PUMP_LEAD

    def test_non_advancing_pts_cannot_grow_the_queue(self):
        # A malformed file whose PTS never advances spans ~0 time, so
        # max-time never leaks; the buffer-count backstop must. The
        # live appsrc in a PAUSED pipeline never drains (a stalled
        # projection).
        Gst = vc.Gst
        pipeline = Gst.Pipeline.new()
        appsrc = Gst.ElementFactory.make("appsrc", None)
        vc._configure_appsrc(appsrc)
        sink = Gst.ElementFactory.make("fakesink", None)
        pipeline.add(appsrc)
        pipeline.add(sink)
        assert appsrc.link(sink)
        pipeline.set_state(Gst.State.PAUSED)
        try:
            for _ in range(3 * vc.APPSRC_MAX_QUEUE_BUFFERS):
                buf = Gst.Buffer.new_allocate(None, 16, None)
                buf.pts = 0
                appsrc.push_buffer(buf)
            level = appsrc.get_property("current-level-buffers")
        finally:
            pipeline.set_state(Gst.State.NULL)
        assert level <= vc.APPSRC_MAX_QUEUE_BUFFERS

    def test_buffer_backstop_is_far_above_a_healthy_queue(self):
        # A healthy queue holds MAX_QUEUE_TIME at most: 30 frames at
        # 60fps. The count must only ever bite on broken timestamps.
        assert vc.APPSRC_MAX_QUEUE_BUFFERS >= 2 * (
            vc.APPSRC_MAX_QUEUE_TIME * 60 // vc.Gst.SECOND)


class TestAttachRollback:
    """A failed attach must leave the projection pipeline as it was
    and return None (the cue then plays audio only) — Phase 7 #7."""

    GL_PLAN = {"gl": True, "upload": "glupload ! glcolorconvert",
               "mixer": "glvideomixerelement", "sink": "glimagesink"}

    def _comp(self):
        out, mon = _fake_windows()

        def fake_build(self):
            self.pipeline = MagicMock()
            self.mixer = MagicMock()
            self._plan = TestAttachRollback.GL_PLAN
            return True

        with patch.object(vc.VideoCompositor, "_build", fake_build):
            comp = vc.VideoCompositor(out, mon)
        return comp

    def _attach(self, comp, appsrc, upload):
        with patch.object(vc.Gst.ElementFactory, "make",
                          return_value=appsrc), \
                patch.object(vc, "_make_upload", return_value=upload), \
                patch.object(vc, "_configure_appsrc"):
            return comp.register(object())

    def _parts(self):
        appsrc = MagicMock()
        upload = MagicMock()
        appsrc.link.return_value = True
        upload.get_static_pad.return_value.link.return_value = (
            vc.Gst.PadLinkReturn.OK)
        appsrc.sync_state_with_parent.return_value = True
        upload.sync_state_with_parent.return_value = True
        return appsrc, upload

    def test_success_returns_registration(self):
        comp = self._comp()
        appsrc, upload = self._parts()
        reg = self._attach(comp, appsrc, upload)
        assert reg is not None
        assert reg.appsrc is appsrc and reg.upload is upload
        assert reg.mix_pad is comp.mixer.request_pad.return_value
        comp.pipeline.remove.assert_not_called()

    def test_upload_started_before_appsrc(self):
        # Dynamically added elements start downstream first: a live
        # appsrc started first can push stream-start/caps into the
        # still-NULL upload bin's flushing ghost pad.
        comp = self._comp()
        appsrc, upload = self._parts()
        order = MagicMock()
        order.attach_mock(appsrc.sync_state_with_parent, "appsrc")
        order.attach_mock(upload.sync_state_with_parent, "upload")
        self._attach(comp, appsrc, upload)
        assert [c[0] for c in order.mock_calls] == ["upload", "appsrc"]

    def test_attach_does_not_replan(self):
        comp = self._comp()
        appsrc, upload = self._parts()
        with patch.object(vc, "plan_pipeline") as plan:
            self._attach(comp, appsrc, upload)
        plan.assert_not_called()

    def test_no_mixer_pad_rolls_back(self):
        comp = self._comp()
        appsrc, upload = self._parts()
        comp.mixer.request_pad.return_value = None
        assert self._attach(comp, appsrc, upload) is None
        comp.pipeline.remove.assert_any_call(appsrc)
        comp.pipeline.remove.assert_any_call(upload)
        comp.mixer.release_request_pad.assert_not_called()
        assert not comp._registrations

    def test_mixer_link_failure_releases_pad(self):
        comp = self._comp()
        appsrc, upload = self._parts()
        upload.get_static_pad.return_value.link.return_value = (
            vc.Gst.PadLinkReturn.NOFORMAT)
        assert self._attach(comp, appsrc, upload) is None
        mix_pad = comp.mixer.request_pad.return_value
        comp.mixer.release_request_pad.assert_called_once_with(mix_pad)
        comp.pipeline.remove.assert_any_call(appsrc)
        comp.pipeline.remove.assert_any_call(upload)

    def test_upload_link_failure_rolls_back(self):
        comp = self._comp()
        appsrc, upload = self._parts()
        appsrc.link.return_value = False
        assert self._attach(comp, appsrc, upload) is None
        comp.mixer.request_pad.assert_not_called()
        comp.pipeline.remove.assert_any_call(appsrc)
        comp.pipeline.remove.assert_any_call(upload)

    def test_state_sync_failure_rolls_back(self):
        comp = self._comp()
        appsrc, upload = self._parts()
        upload.sync_state_with_parent.return_value = False
        assert self._attach(comp, appsrc, upload) is None
        comp.mixer.release_request_pad.assert_called_once()

    def test_no_appsrc_returns_none(self):
        comp = self._comp()
        assert self._attach(comp, None, MagicMock()) is None
        comp.pipeline.add.assert_not_called()


class TestDetachResilience:
    def test_failing_step_does_not_skip_the_rest(self):
        out, mon = _fake_windows()
        with patch.object(vc.VideoCompositor, "_build", autospec=True,
                          return_value=True):
            comp = vc.VideoCompositor(out, mon)
        comp.pipeline = MagicMock()
        comp.mixer = MagicMock()
        reg = vc.Registration()
        reg.appsrc = MagicMock()
        reg.upload = MagicMock()
        reg.mix_pad = MagicMock()
        reg.appsrc.set_state.side_effect = RuntimeError("boom")
        comp._detach(reg)
        comp.mixer.release_request_pad.assert_called_once_with(reg.mix_pad)
        comp.pipeline.remove.assert_any_call(reg.appsrc)
        comp.pipeline.remove.assert_any_call(reg.upload)


def _bus_message(kind, src):
    message = MagicMock()
    message.type = kind
    message.src = src
    err = MagicMock()
    err.message = "simulated"
    message.parse_error.return_value = (err, "dbg")
    message.parse_warning.return_value = (err, "dbg")
    return message


class TestBusErrors:
    """The projection bus is watched (Phase 7 #2): a pipeline-level
    ERROR disables the compositor and notifies; an ERROR inside one
    cue's branch drops only that cue's video."""

    def _comp(self):
        out, mon = _fake_windows()

        def fake_build(self):
            self.pipeline = MagicMock()
            self.mixer = MagicMock()
            return True

        with patch.object(vc.VideoCompositor, "_build", fake_build):
            comp = vc.VideoCompositor(out, mon)
        _FakeScheduler(comp)
        return comp

    def _register(self, comp, sink):
        def attach(_sink):
            reg = vc.Registration()
            reg.appsrc = MagicMock()
            reg.upload = MagicMock()
            reg.mix_pad = MagicMock()
            return reg

        with patch.object(comp, "_attach", side_effect=attach):
            return comp.register(sink)

    def test_pipeline_error_disables_and_notifies(self):
        comp = self._comp()
        pipeline = comp.pipeline
        self._register(comp, object())
        fired = []

        def on_failed():
            fired.append(True)

        comp.failed.connect(on_failed)
        # A shared element: its ancestry reaches the (top-level,
        # parentless) projection pipeline.
        pipeline.get_parent.return_value = None
        mixer_element = MagicMock()
        mixer_element.get_parent.return_value = pipeline
        comp._on_bus_message(
            None, _bus_message(vc.Gst.MessageType.ERROR, mixer_element))
        assert fired == [True]
        assert comp.available is False
        assert comp.pipeline is None
        pipeline.set_state.assert_called_with(vc.Gst.State.NULL)
        assert not comp._registrations
        assert comp.register(object()) is None

    def test_branch_error_drops_only_that_cue(self):
        comp = self._comp()
        a, b = object(), object()
        reg_a = self._register(comp, a)
        self._register(comp, b)
        # The error comes from an element inside A's upload bin.
        child = MagicMock()
        child.get_parent.return_value = reg_a.upload
        with patch.object(comp, "_detach") as detach:
            comp._on_bus_message(
                None, _bus_message(vc.Gst.MessageType.ERROR, child))
        detach.assert_called_once_with(reg_a)
        assert comp.available is True
        assert comp.is_registered(a) is False
        assert comp.is_registered(b) is True

    def _real_comp(self):
        """A compositor whose pipeline is a real (never started)
        Gst.Pipeline, so element parentage behaves as in production:
        pipeline.remove() really unparents a detached branch."""
        out, mon = _fake_windows()

        def fake_build(self):
            self.pipeline = vc.Gst.Pipeline.new("projection")
            self.mixer = MagicMock()
            return True

        with patch.object(vc.VideoCompositor, "_build", fake_build):
            comp = vc.VideoCompositor(out, mon)
        return comp, _FakeScheduler(comp)

    def _register_real(self, comp, sink):
        """Register a branch built from real elements: an appsrc and an
        upload bin (identity stands in for glupload ! glcolorconvert)."""

        def attach(_sink):
            reg = vc.Registration()
            reg.appsrc = vc.Gst.ElementFactory.make("appsrc", None)
            reg.upload = vc.Gst.parse_bin_from_description(
                "identity name=inner", True
            )
            comp.pipeline.add(reg.appsrc)
            comp.pipeline.add(reg.upload)
            assert reg.appsrc.link(reg.upload)
            return reg

        with patch.object(comp, "_attach", side_effect=attach):
            return comp.register(sink)

    def test_second_error_from_dropped_branch_is_ignored(self):
        """One failing branch posts two ERRORs before the main loop
        handles the first: the upload child's, then basesrc's
        'Internal data stream error' from the appsrc. The first drops
        the branch; the second must not take the projection down."""
        comp, _ = self._real_comp()
        other = object()
        reg = self._register_real(comp, object())
        self._register_real(comp, other)
        appsrc = reg.appsrc
        inner = reg.upload.get_by_name("inner")
        fired = []

        def on_failed():
            fired.append(True)

        comp.failed.connect(on_failed)
        comp._on_bus_message(
            None, _bus_message(vc.Gst.MessageType.ERROR, inner))
        comp._on_bus_message(
            None, _bus_message(vc.Gst.MessageType.ERROR, appsrc))
        assert fired == []
        assert comp.available is True
        assert comp.is_registered(other) is True

    def test_late_error_after_linger_release_is_ignored(self):
        comp, sched = self._real_comp()
        sink = object()
        reg = self._register_real(comp, sink)
        appsrc = reg.appsrc
        comp.unregister(sink)
        sched.fire(vc.LINGER_MS)  # no successor -> released
        assert appsrc.get_parent() is None
        comp._on_bus_message(
            None, _bus_message(vc.Gst.MessageType.ERROR, appsrc))
        assert comp.available is True

    def test_error_from_shared_element_still_shuts_down(self):
        comp, _ = self._real_comp()
        self._register_real(comp, object())
        tee = vc.Gst.ElementFactory.make("tee", None)
        comp.pipeline.add(tee)
        comp._on_bus_message(
            None, _bus_message(vc.Gst.MessageType.ERROR, tee))
        assert comp.available is False

    def test_warning_is_only_logged(self, caplog):
        comp = self._comp()
        self._register(comp, object())
        src = MagicMock()
        src.get_parent.return_value = None
        comp._on_bus_message(
            None, _bus_message(vc.Gst.MessageType.WARNING, src))
        assert comp.available is True
        assert "simulated" in caplog.text


class TestRebuildAfterFailure:
    """A shared-pipeline ERROR no longer ends video for the rest of the
    process: the compositor tears the pipeline down, then rebuilds it
    on the main loop with backoff (REBUILD_BACKOFF_MS), and gives up
    after the last attempt. A failure long after a good rebuild starts
    the backoff over. shutdown() (finalize) cancels a pending
    rebuild."""

    _MONO = "lisp.plugins.gst_backend.video_compositor.time.monotonic"

    def _comp(self):
        out, mon = _fake_windows()

        def fake_build(self):
            self.pipeline = MagicMock()
            self.pipeline.get_parent.return_value = None
            self.mixer = MagicMock()
            return True

        with patch.object(vc.VideoCompositor, "_build", fake_build):
            comp = vc.VideoCompositor(out, mon)
        sched = _FakeScheduler(comp)
        builds = []

        def rebuild_ok():
            fake_build(comp)
            builds.append(True)
            return True

        comp._build = MagicMock(side_effect=rebuild_ok)
        events = {"failed": 0, "restored": 0, "gave_up": 0}
        handlers = {}
        for name in events:
            def handler(name=name):
                events[name] += 1
            handlers[name] = handler  # strong ref: signals are weak
            getattr(comp, name).connect(handler)
        comp._test_handlers = handlers
        return comp, sched, events

    def _fail(self, comp):
        """A pipeline-level ERROR (from an element of the pipeline)."""
        element = MagicMock()
        element.get_parent.return_value = comp.pipeline
        comp._on_bus_message(
            None, _bus_message(vc.Gst.MessageType.ERROR, element))

    def test_failure_tears_down_and_schedules_rebuild(self):
        comp, sched, events = self._comp()
        old = comp.pipeline
        self._fail(comp)
        old.set_state.assert_called_with(vc.Gst.State.NULL)
        assert comp.available is False
        assert comp.pipeline is None
        assert events["failed"] == 1
        assert [p[0] for p in sched.pending] == [vc.REBUILD_BACKOFF_MS[0]]

    def test_rebuild_restores_the_projection(self):
        comp, sched, events = self._comp()
        self._fail(comp)
        sched.fire(vc.REBUILD_BACKOFF_MS[0])
        assert comp.available is True
        assert comp.pipeline is not None
        assert events["restored"] == 1

    def test_failed_rebuilds_back_off_then_give_up(self):
        comp, sched, events = self._comp()
        comp._build = MagicMock(return_value=False)
        self._fail(comp)
        for delay in vc.REBUILD_BACKOFF_MS:
            assert [p[0] for p in sched.pending] == [delay]
            sched.fire(delay)
        assert sched.pending == []
        assert comp._build.call_count == len(vc.REBUILD_BACKOFF_MS)
        assert comp.available is False
        assert events["gave_up"] == 1
        assert events["restored"] == 0

    def test_rebuild_that_raises_counts_as_failed(self):
        comp, sched, events = self._comp()
        comp._build = MagicMock(side_effect=RuntimeError("GL gone"))
        self._fail(comp)
        sched.fire(vc.REBUILD_BACKOFF_MS[0])
        assert comp.available is False
        assert [p[0] for p in sched.pending] == [vc.REBUILD_BACKOFF_MS[1]]

    def test_quick_refailure_escalates_backoff(self):
        comp, sched, events = self._comp()
        with patch(self._MONO, return_value=1000.0):
            self._fail(comp)
            sched.fire(vc.REBUILD_BACKOFF_MS[0])
            self._fail(comp)  # fails again right after the rebuild
        assert [p[0] for p in sched.pending] == [vc.REBUILD_BACKOFF_MS[1]]

    def test_failure_long_after_rebuild_resets_backoff(self):
        comp, sched, events = self._comp()
        with patch(self._MONO, return_value=1000.0):
            self._fail(comp)
            sched.fire(vc.REBUILD_BACKOFF_MS[0])
        later = 1000.0 + vc.REBUILD_STABLE_MS / 1000 + 1
        with patch(self._MONO, return_value=later):
            self._fail(comp)
        assert [p[0] for p in sched.pending] == [vc.REBUILD_BACKOFF_MS[0]]

    def test_refailure_with_no_attempts_left_only_gives_up(self):
        # Every rebuild succeeds and the pipeline dies again at once:
        # the last failure must not announce a restart that will never
        # come ("restarting" then "could not be restarted").
        comp, sched, events = self._comp()
        with patch(self._MONO, return_value=1000.0):
            for delay in vc.REBUILD_BACKOFF_MS:
                self._fail(comp)
                sched.fire(delay)
            assert events["restored"] == len(vc.REBUILD_BACKOFF_MS)
            failed_before = events["failed"]
            self._fail(comp)
        assert events["failed"] == failed_before
        assert events["gave_up"] == 1
        assert sched.pending == []

    def test_shutdown_cancels_pending_rebuild(self):
        comp, sched, events = self._comp()
        self._fail(comp)
        comp.shutdown()  # finalize during the backoff
        assert sched.pending == []
        comp._rebuild()  # a timer that fired anyway: still a no-op
        comp._build.assert_not_called()
        assert comp.available is False

    def test_failure_drops_registrations_of_dead_pipeline(self):
        comp, sched, events = self._comp()
        sink = object()
        with patch.object(comp, "_attach", return_value=vc.Registration()):
            comp.register(sink)
        self._fail(comp)
        assert comp.is_registered(sink) is False
        sched.fire(vc.REBUILD_BACKOFF_MS[0])
        assert comp.is_registered(sink) is False  # re-attach is explicit

    def test_real_pipeline_fail_rebuild_reregister(self):
        """The real _build/_teardown/_attach cycle on GStreamer, with
        the software plan into fakesinks: no window, GL or audio."""
        plan = {"gl": False, "upload": None, "mixer": "compositor",
                "sink": "fakesink"}
        out, mon = _fake_windows()
        with patch.object(vc, "plan_pipeline", return_value=plan):
            comp = vc.VideoCompositor(out, mon, canvas_size=(64, 48))
            try:
                assert comp.available is True
                sched = _FakeScheduler(comp)
                first = comp.pipeline
                sink = object()
                assert comp.register(sink) is not None
                comp._fail()
                assert comp.pipeline is None
                assert first.get_state(0)[1] == vc.Gst.State.NULL
                sched.fire(vc.REBUILD_BACKOFF_MS[0])
                assert comp.available is True
                assert comp.pipeline is not first
                ret, state, _ = comp.pipeline.get_state(vc.Gst.SECOND)
                assert state == vc.Gst.State.PLAYING
                reg = comp.register(sink)  # re-attach on the new one
                assert reg is not None
                assert reg.appsrc.get_parent() is comp.pipeline
            finally:
                comp.shutdown()

    def test_branch_error_does_not_rebuild(self):
        comp, sched, events = self._comp()
        reg = vc.Registration()
        reg.appsrc = MagicMock()
        reg.appsrc.get_parent.return_value = comp.pipeline
        with patch.object(comp, "_attach", return_value=reg):
            comp.register(object())
        with patch.object(comp, "_detach"):
            comp._on_bus_message(
                None, _bus_message(vc.Gst.MessageType.ERROR, reg.appsrc))
        assert events["failed"] == 0
        assert sched.pending == []


class TestLatencyCache:
    """One cached projection latency for every cue's pump (Phase 7
    #4), instead of each pump walking the GL pipeline."""

    _QL = "lisp.plugins.gst_backend.video_compositor.query_min_latency"

    def _comp(self):
        out, mon = _fake_windows()

        def fake_build(self):
            self.pipeline = MagicMock()
            self.mixer = MagicMock()
            return True

        with patch.object(vc.VideoCompositor, "_build", fake_build):
            return vc.VideoCompositor(out, mon)

    def test_cached_within_ttl(self):
        comp = self._comp()
        with patch(self._QL, return_value=86) as query:
            assert comp.latency() == 86
            assert comp.latency() == 86
        query.assert_called_once_with(comp.pipeline)

    def test_requeried_after_ttl(self):
        comp = self._comp()
        with patch(self._QL, return_value=86) as query, \
                patch.object(vc.time, "monotonic_ns",
                             side_effect=[0, vc.LATENCY_CACHE_NS + 1]):
            comp.latency()
            comp.latency()
        assert query.call_count == 2

    def test_latency_message_invalidates(self):
        comp = self._comp()
        with patch(self._QL, return_value=86) as query:
            comp.latency()
            comp._on_bus_message(
                None, _bus_message(vc.Gst.MessageType.LATENCY, None))
            comp.latency()
        assert query.call_count == 2

    def test_detach_invalidates(self):
        comp = self._comp()
        reg = vc.Registration()
        reg.appsrc = MagicMock()
        reg.mix_pad = MagicMock()
        with patch(self._QL, return_value=86) as query:
            comp.latency()
            comp._detach(reg)
            comp.latency()
        assert query.call_count == 2

    def test_zero_when_shut_down(self):
        comp = self._comp()
        comp.shutdown()
        assert comp.latency() == 0
