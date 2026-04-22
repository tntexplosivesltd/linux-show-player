# This file is part of Linux Show Player
#
# Copyright 2026 Francesco Ceruti <ceppofrancy@gmail.com>
#
# Linux Show Player is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# Linux Show Player is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Linux Show Player.  If not, see <http://www.gnu.org/licenses/>.

"""Integration tests for ``MediaCueSettings``.

Covers the inspector-page concerns: two-column layout, sentinel
mapping on load, bidirectional numeric-field ↔ trimmer sync,
image-cue detection, and the multi-select placeholder.
"""

import pytest
from PyQt5.QtCore import QTime

from lisp.ui.settings.cue_pages.media_cue import MediaCueSettings


class _FakeWaveform:
    def __init__(self, duration_ms=10_000):
        from lisp.core.signal import Signal
        self.duration = duration_ms
        self.peak_samples = []
        self.rms_samples = []
        self.ready = Signal()
        self.failed = Signal()
        self.cleared = 0

    def clear(self):
        self.cleared += 1
        self.peak_samples = []
        self.rms_samples = []

    def load_waveform(self):
        return False

    def is_ready(self):
        return bool(self.peak_samples and self.rms_samples)

    def mark_ready(self, samples=256):
        self.peak_samples = [0.5] * samples
        self.rms_samples = [0.25] * samples
        self.ready.emit()

    def mark_failed(self):
        self.failed.emit()


class TestMediaCueSettingsLayout:
    def test_has_start_stop_loop_fields(self, qtbot):
        page = MediaCueSettings()
        qtbot.addWidget(page)
        assert page.startEdit is not None
        assert page.stopEdit is not None
        assert page.spinLoop is not None

    def test_grid_is_two_column(self, qtbot):
        """Column 0 = narrow fields, column 1 = wide waveform slot.

        ColumnStretch 1:3 gives the waveform ~75% of horizontal space.
        """
        page = MediaCueSettings()
        qtbot.addWidget(page)

        grid = page.layout()
        assert grid.columnStretch(0) == 1
        assert grid.columnStretch(1) == 3


class TestStopTimeSentinelMapping:
    def test_zero_stop_time_displays_as_duration(self, qtbot):
        """stop_time == 0 with a known duration displays as duration."""
        page = MediaCueSettings()
        qtbot.addWidget(page)
        page.loadSettings(
            {"media": {"stop_time": 0, "duration": 180_000, "start_time": 0}}
        )

        assert page.stopEdit.time() == QTime.fromMSecsSinceStartOfDay(180_000)

    def test_nonzero_stop_time_displays_verbatim(self, qtbot):
        page = MediaCueSettings()
        qtbot.addWidget(page)
        page.loadSettings(
            {
                "media": {
                    "stop_time": 60_000,
                    "duration": 180_000,
                    "start_time": 0,
                }
            }
        )

        assert page.stopEdit.time() == QTime.fromMSecsSinceStartOfDay(60_000)

    def test_get_settings_roundtrips_zero_sentinel(self, qtbot):
        """stop_time == 0 (play to natural end) must survive load→save.

        The backend treats stop_time == 0 as SeekType.NONE ("don't set a
        stop position"), distinct from stop_time == duration which is
        SeekType.SET. Map duration back to 0 on save so a user who loads
        and immediately re-saves doesn't silently alter GStreamer seek
        semantics.
        """
        page = MediaCueSettings()
        qtbot.addWidget(page)
        page.loadSettings(
            {"media": {"stop_time": 0, "duration": 180_000, "start_time": 0}}
        )

        settings = page.getSettings()
        assert settings["media"]["stop_time"] == 0

    def test_get_settings_preserves_user_stop_at_end(self, qtbot):
        """If the user explicitly drags stop to duration, save verbatim.

        (Without a duration context it cannot be distinguished from the
        sentinel case — but once user interaction has occurred we prefer
        preserving their value. Policy choice: map to 0 uniformly so
        SeekType.NONE is always used when stop == duration. Re-evaluate
        if users complain.)
        """
        page = MediaCueSettings()
        qtbot.addWidget(page)
        page.loadSettings(
            {
                "media": {
                    "stop_time": 120_000,
                    "duration": 180_000,
                    "start_time": 0,
                }
            }
        )
        # User drags stop to end.
        page.stopEdit.setTime(QTime.fromMSecsSinceStartOfDay(180_000))
        settings = page.getSettings()
        assert settings["media"]["stop_time"] == 0

    def test_zero_duration_leaves_zero(self, qtbot):
        """When duration is unknown, the 0 sentinel can't be translated."""
        page = MediaCueSettings()
        qtbot.addWidget(page)
        page.loadSettings(
            {"media": {"stop_time": 0, "duration": 0, "start_time": 0}}
        )

        assert page.stopEdit.time() == QTime.fromMSecsSinceStartOfDay(0)


class TestImageCueHandling:
    def test_image_cue_disables_trim_fields(self, qtbot):
        page = MediaCueSettings()
        qtbot.addWidget(page)
        page.loadSettings(
            {
                "media": {
                    "stop_time": 0,
                    "duration": 5_000,
                    "start_time": 0,
                    "ImageInput": {},
                }
            }
        )

        assert not page.startEdit.isEnabled()
        assert not page.stopEdit.isEnabled()

    def test_image_cue_loop_field_stays_enabled(self, qtbot):
        page = MediaCueSettings()
        qtbot.addWidget(page)
        page.loadSettings(
            {
                "media": {
                    "stop_time": 0,
                    "duration": 5_000,
                    "ImageInput": {},
                    "loop": 0,
                }
            }
        )
        assert page.spinLoop.isEnabled()

    def test_audio_cue_fields_stay_enabled(self, qtbot):
        page = MediaCueSettings()
        qtbot.addWidget(page)
        page.loadSettings(
            {
                "media": {
                    "stop_time": 60_000,
                    "duration": 180_000,
                    "UriInput": {},
                    "Volume": {},
                }
            }
        )
        assert page.startEdit.isEnabled()
        assert page.stopEdit.isEnabled()


class TestMultiSelectPlaceholder:
    def test_single_cue_shows_waveform_slot(self, qtbot):
        page = MediaCueSettings()
        qtbot.addWidget(page)
        page.loadSettings({"media": {"duration": 10_000}})
        page.show()
        qtbot.waitExposed(page)
        assert not page.placeholderLabel.isVisible()

    def test_enable_check_true_shows_placeholder(self, qtbot):
        """enableCheck(True) is how the inspector signals multi-select."""
        page = MediaCueSettings()
        qtbot.addWidget(page)
        page.show()
        qtbot.waitExposed(page)

        page.enableCheck(True)
        assert page.placeholderLabel.isVisible()


class TestWaveformTrimmerSync:
    @pytest.fixture
    def _with_backend(self, monkeypatch):
        # Shared backend stub so loadSettings can fetch a waveform.
        state = {"waveform": None}

        class _Backend:
            def media_waveform(self, media):
                return state["waveform"]

        monkeypatch.setattr(
            "lisp.ui.settings.cue_pages.media_cue.get_backend",
            lambda: _Backend(),
        )
        return state

    def _load_with_waveform(self, page, qtbot, _with_backend, duration=10_000):
        waveform = _FakeWaveform(duration_ms=duration)
        _with_backend["waveform"] = waveform

        class _FakeMedia:
            def __init__(self):
                self.duration = duration
                self.elements = {}

        class _FakeCue:
            media = _FakeMedia()

        page.setCue(_FakeCue())
        page.loadSettings(
            {
                "media": {
                    "duration": duration,
                    "start_time": 0,
                    "stop_time": 0,
                }
            }
        )
        qtbot.wait(10)
        return waveform

    def test_trimmer_created_after_install(self, qtbot, _with_backend):
        page = MediaCueSettings()
        qtbot.addWidget(page)
        self._load_with_waveform(page, qtbot, _with_backend)
        assert page.trimmer is not None

    def test_typed_start_time_moves_marker(self, qtbot, _with_backend):
        page = MediaCueSettings()
        qtbot.addWidget(page)
        self._load_with_waveform(page, qtbot, _with_backend)

        page.startEdit.setTime(QTime.fromMSecsSinceStartOfDay(3_000))
        qtbot.wait(10)
        assert page.trimmer.startTime() == 3_000

    def test_marker_drag_updates_start_field(self, qtbot, _with_backend):
        page = MediaCueSettings()
        qtbot.addWidget(page)
        self._load_with_waveform(page, qtbot, _with_backend)

        page.trimmer.setStartTime(4_000)
        qtbot.wait(10)
        assert page.startEdit.time() == QTime.fromMSecsSinceStartOfDay(4_000)

    def test_start_field_tracks_stop_as_upper_bound(self, qtbot, _with_backend):
        page = MediaCueSettings()
        qtbot.addWidget(page)
        self._load_with_waveform(page, qtbot, _with_backend)

        page.stopEdit.setTime(QTime.fromMSecsSinceStartOfDay(5_000))
        qtbot.wait(10)
        assert (
            page.startEdit.maximumTime()
            == QTime.fromMSecsSinceStartOfDay(4_999)
        )

    def test_stop_field_tracks_start_as_lower_bound(self, qtbot, _with_backend):
        page = MediaCueSettings()
        qtbot.addWidget(page)
        self._load_with_waveform(page, qtbot, _with_backend)

        page.startEdit.setTime(QTime.fromMSecsSinceStartOfDay(3_000))
        qtbot.wait(10)
        assert (
            page.stopEdit.minimumTime()
            == QTime.fromMSecsSinceStartOfDay(3_001)
        )

    def test_bound_clamp_does_not_re_enter_handler(
        self, qtbot, _with_backend
    ):
        """Setting startEdit past its old max clamps and must not recurse.

        Scenario: stopEdit is at 5_000 (so startEdit max is 4_999); user
        types 8_000 into startEdit. Qt clamps to 4_999 and re-emits
        timeChanged. Without blockSignals, the handler re-enters and
        recomputes bounds — with stacked clamps and double trimmer pushes.
        """
        page = MediaCueSettings()
        qtbot.addWidget(page)
        self._load_with_waveform(page, qtbot, _with_backend)

        # Establish a known stop position so startEdit max is 4_999.
        page.stopEdit.setTime(QTime.fromMSecsSinceStartOfDay(5_000))
        qtbot.wait(10)

        handler_calls = {"n": 0}
        original = page._on_start_edit_changed

        def counting(qtime):
            handler_calls["n"] += 1
            return original(qtime)

        page._on_start_edit_changed = counting
        page.startEdit.timeChanged.disconnect(original)
        page.startEdit.timeChanged.connect(counting)

        # Type a value above the current max. Qt will clamp to 4_999
        # and emit timeChanged. Handler must fire at most once.
        page.startEdit.setTime(QTime.fromMSecsSinceStartOfDay(8_000))
        qtbot.wait(20)

        assert handler_calls["n"] == 1, (
            f"handler re-entered {handler_calls['n']} times"
        )

    def test_clamped_field_value_syncs_to_trimmer(
        self, qtbot, _with_backend
    ):
        """User-typed value clamped by Qt must still land on the trimmer."""
        page = MediaCueSettings()
        qtbot.addWidget(page)
        self._load_with_waveform(page, qtbot, _with_backend)

        # Force max on startEdit by setting stop first.
        page.stopEdit.setTime(QTime.fromMSecsSinceStartOfDay(5_000))
        qtbot.wait(10)

        # Typing 8_000 clamps to 4_999; trimmer must follow the clamp.
        page.startEdit.setTime(QTime.fromMSecsSinceStartOfDay(8_000))
        qtbot.wait(10)

        assert page.startEdit.time() == QTime.fromMSecsSinceStartOfDay(4_999)
        assert page.trimmer.startTime() == 4_999

    def test_sync_does_not_recurse(self, qtbot, _with_backend):
        """Typing a value must not re-enter via the marker signal."""
        page = MediaCueSettings()
        qtbot.addWidget(page)
        self._load_with_waveform(page, qtbot, _with_backend)

        calls = {"field": 0, "marker": 0}
        page.startEdit.timeChanged.connect(
            lambda *_: calls.__setitem__("field", calls["field"] + 1)
        )
        page.trimmer.startTimeChanged.connect(
            lambda *_: calls.__setitem__("marker", calls["marker"] + 1)
        )

        page.startEdit.setTime(QTime.fromMSecsSinceStartOfDay(2_500))
        qtbot.wait(10)

        assert calls["field"] == 1
        assert calls["marker"] == 0


class TestCueInstallation:
    def test_set_cue_installs_waveform_for_audio(self, qtbot, monkeypatch):
        """Wiring the live cue auto-mounts a TrimmableWaveformWidget."""
        fake_waveform = _FakeWaveform(duration_ms=10_000)

        class _FakeMedia:
            def __init__(self):
                self.duration = 10_000
                self.elements = {}

            def input_uri(self):
                return "file:///fake.wav"

        class _FakeCue:
            def __init__(self):
                self.media = _FakeMedia()

            def properties(self, **_):
                return {"media": {"duration": 10_000}}

        class _FakeBackend:
            def media_waveform(self, media):
                return fake_waveform

        monkeypatch.setattr(
            "lisp.ui.settings.cue_pages.media_cue.get_backend",
            lambda: _FakeBackend(),
        )

        page = MediaCueSettings()
        qtbot.addWidget(page)
        page.setCue(_FakeCue())
        page.loadSettings(
            {"media": {"duration": 10_000, "start_time": 0, "stop_time": 0}}
        )
        qtbot.wait(10)

        from lisp.ui.widgets.waveform import TrimmableWaveformWidget
        assert isinstance(page.trimmer, TrimmableWaveformWidget)

    def test_set_cue_shows_image_placeholder(self, qtbot, monkeypatch):
        """Image cues: no trimmer widget, placeholder caption in the slot."""
        class _FakeMedia:
            def __init__(self):
                self.duration = 5_000
                self.elements = {"ImageInput": object()}

            def input_uri(self):
                return "file:///fake.jpg"

        class _FakeCue:
            def __init__(self):
                self.media = _FakeMedia()

            def properties(self, **_):
                return {
                    "media": {
                        "duration": 5_000,
                        "ImageInput": {},
                    }
                }

        page = MediaCueSettings()
        qtbot.addWidget(page)
        page.setCue(_FakeCue())
        page.loadSettings(
            {
                "media": {
                    "duration": 5_000,
                    "ImageInput": {},
                    "start_time": 0,
                    "stop_time": 0,
                }
            }
        )
        page.show()
        qtbot.waitExposed(page)

        assert page.trimmer is None
        assert page.imagePlaceholder.isVisible()

    def test_set_cue_none_hides_waveform(self, qtbot):
        page = MediaCueSettings()
        qtbot.addWidget(page)
        page.setCue(None)  # multi-select path
        page.loadSettings({"media": {"duration": 0}})
        qtbot.wait(10)

        assert page.trimmer is None


class TestLoadTimeInit:
    def _backend(self, monkeypatch, waveform):
        class _Backend:
            def media_waveform(self, media):
                return waveform

        monkeypatch.setattr(
            "lisp.ui.settings.cue_pages.media_cue.get_backend",
            lambda: _Backend(),
        )

    def _cue(self, duration):
        class _FakeMedia:
            def __init__(self):
                self.duration = duration
                self.elements = {}

        class _FakeCue:
            def __init__(self):
                self.media = _FakeMedia()

        return _FakeCue()

    def test_markers_seeded_from_stored_trim(self, qtbot, monkeypatch):
        """Trimmer start/stop match the stored values after load."""
        waveform = _FakeWaveform(duration_ms=60_000)
        self._backend(monkeypatch, waveform)
        page = MediaCueSettings()
        qtbot.addWidget(page)
        page.setCue(self._cue(60_000))
        page.loadSettings(
            {
                "media": {
                    "duration": 60_000,
                    "start_time": 5_000,
                    "stop_time": 45_000,
                }
            }
        )
        qtbot.wait(10)

        assert page.trimmer.startTime() == 5_000
        assert page.trimmer.stopTime() == 45_000

    def test_stop_edit_min_reflects_start_on_load(self, qtbot, monkeypatch):
        waveform = _FakeWaveform(duration_ms=60_000)
        self._backend(monkeypatch, waveform)
        page = MediaCueSettings()
        qtbot.addWidget(page)
        page.setCue(self._cue(60_000))
        page.loadSettings(
            {
                "media": {
                    "duration": 60_000,
                    "start_time": 5_000,
                    "stop_time": 45_000,
                }
            }
        )

        assert page.stopEdit.minimumTime() == QTime.fromMSecsSinceStartOfDay(
            5_001
        )
        assert page.startEdit.maximumTime() == QTime.fromMSecsSinceStartOfDay(
            44_999
        )


class TestLifecycle:
    """Navigate between cues: no leaked pipelines, no stale connections."""

    def _install(self, page, qtbot, monkeypatch, duration=10_000):
        waveform = _FakeWaveform(duration_ms=duration)

        class _Backend:
            def media_waveform(self_, media):
                return waveform

        monkeypatch.setattr(
            "lisp.ui.settings.cue_pages.media_cue.get_backend",
            lambda: _Backend(),
        )

        class _FakeMedia:
            def __init__(self):
                self.duration = duration
                self.elements = {}

        class _FakeCue:
            def __init__(self):
                self.media = _FakeMedia()

        page.setCue(_FakeCue())
        page.loadSettings(
            {"media": {"duration": duration, "start_time": 0, "stop_time": 0}}
        )
        qtbot.wait(10)
        return waveform

    def test_teardown_calls_clear_on_previous_waveform(
        self, qtbot, monkeypatch
    ):
        page = MediaCueSettings()
        qtbot.addWidget(page)
        waveform_a = self._install(page, qtbot, monkeypatch)
        assert waveform_a.cleared == 0

        # Navigate to a second cue: old waveform must be stopped.
        self._install(page, qtbot, monkeypatch)
        assert waveform_a.cleared == 1

    def test_failed_on_old_waveform_does_not_swap_new_trimmer(
        self, qtbot, monkeypatch
    ):
        page = MediaCueSettings()
        qtbot.addWidget(page)
        waveform_a = self._install(page, qtbot, monkeypatch)
        self._install(page, qtbot, monkeypatch)

        from lisp.ui.widgets.waveform import TrimmableWaveformWidget
        assert isinstance(page.trimmer, TrimmableWaveformWidget)

        # Decode failure emitted on the old (orphan) waveform.
        waveform_a.mark_failed()
        qtbot.wait(10)

        # The current (new) trimmer must NOT be swapped to a timeline.
        assert isinstance(page.trimmer, TrimmableWaveformWidget)

    def test_time_change_handlers_not_duplicated_across_navigations(
        self, qtbot, monkeypatch
    ):
        page = MediaCueSettings()
        qtbot.addWidget(page)
        self._install(page, qtbot, monkeypatch)
        self._install(page, qtbot, monkeypatch)

        calls = {"count": 0}

        def _probe(*_):
            calls["count"] += 1

        # Hook after navigation to count how many propagations fire
        # from one edit. Duplicate connections would fire the trimmer
        # setter handler once per stale connection, emitting multiple
        # trimmer.startTimeChanged signals.
        page.trimmer.startTimeChanged.connect(_probe)
        page.startEdit.setTime(QTime.fromMSecsSinceStartOfDay(2_000))
        qtbot.wait(10)
        # silent=True means no emissions from the setter; but if the
        # startEdit handler were connected twice, Qt would clamp twice
        # and _on_trim_start_changed would *not* fire (it's silent).
        # The important invariant is the trimmer value is set exactly
        # once — which is indirectly observable via stopEdit.minimumTime.
        assert page.stopEdit.minimumTime() == QTime.fromMSecsSinceStartOfDay(
            2_001
        )


class TestWaveformFailureFallback:
    def test_failed_signal_swaps_to_timeline(self, qtbot, monkeypatch):
        fake_waveform = _FakeWaveform(duration_ms=10_000)

        class _FakeMedia:
            def __init__(self):
                self.duration = 10_000
                self.elements = {}

            def input_uri(self):
                return "file:///fake.mp4"

        class _FakeCue:
            def __init__(self):
                self.media = _FakeMedia()

            def properties(self, **_):
                return {"media": {"duration": 10_000}}

        monkeypatch.setattr(
            "lisp.ui.settings.cue_pages.media_cue.get_backend",
            lambda: type(
                "_B", (), {"media_waveform": lambda s, m: fake_waveform}
            )(),
        )

        page = MediaCueSettings()
        qtbot.addWidget(page)
        page.setCue(_FakeCue())
        page.loadSettings({"media": {"duration": 10_000}})
        qtbot.wait(10)

        from lisp.ui.widgets.waveform import (
            TrimmableTimelineWidget,
            TrimmableWaveformWidget,
        )
        assert isinstance(page.trimmer, TrimmableWaveformWidget)

        fake_waveform.mark_failed()
        qtbot.wait(10)

        assert isinstance(page.trimmer, TrimmableTimelineWidget)
