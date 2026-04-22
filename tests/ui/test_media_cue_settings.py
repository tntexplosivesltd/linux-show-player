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

    def clear(self):
        self.peak_samples = []
        self.rms_samples = []


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

    def test_get_settings_returns_typed_value_verbatim(self, qtbot):
        """No sentinel translation on save — what the user sees is what persists."""
        page = MediaCueSettings()
        qtbot.addWidget(page)
        page.loadSettings(
            {"media": {"stop_time": 0, "duration": 180_000, "start_time": 0}}
        )

        settings = page.getSettings()
        assert settings["media"]["stop_time"] == 180_000

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
