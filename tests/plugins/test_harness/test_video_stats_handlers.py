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

"""Unit tests for the video.stats RPC handler (projection counters).

The perf E2E is its only other user, and that skips without a display,
so the sink shapes it walks are pinned here with fakes.
"""

from types import SimpleNamespace

import pytest

from lisp.plugins.gst_backend.gst_backend import GstBackend
from lisp.plugins.test_harness import handlers
from lisp.plugins.test_harness.dispatcher import Dispatcher


class FakeStats:
    def __init__(self, rendered, dropped, rate):
        self._values = {
            "rendered": rendered, "dropped": dropped, "average-rate": rate,
        }

    def get_value(self, key):
        return self._values[key]


class FakeElement:
    """Just enough GObject: find_property / get_property."""

    def __init__(self, **props):
        self._props = props

    def find_property(self, name):
        return object() if name in self._props else None

    def get_property(self, name):
        return self._props[name]


def base_sink(rendered=100, dropped=2, rate=25.0):
    return FakeElement(stats=FakeStats(rendered, dropped, rate))


class FakeCompositor:
    def __init__(self, proj_sink=None, registrations=()):
        self.pipeline = object()
        self._proj_sink = proj_sink
        self._registrations = list(registrations)

    def canvas_size(self):
        return (1920, 1080)

    def projection_sink(self):
        return self._proj_sink

    def registrations(self):
        return list(self._registrations)


class FakeMedia:
    def __init__(self, sink):
        self._sink = sink

    def element(self, name):
        return self._sink if name == "VideoSink" else None


@pytest.fixture
def stats(monkeypatch):
    """Returns (call, set_compositor, cues): call() runs video.stats."""
    cues = []
    app = SimpleNamespace(cue_model=cues)
    d = Dispatcher()
    handlers.register_all(d, app, signal_manager=None)

    def set_compositor(compositor):
        monkeypatch.setattr(GstBackend, "_video_compositor", compositor)

    def call():
        resp = d.dispatch({
            "jsonrpc": "2.0", "id": 1, "method": "video.stats",
            "params": {},
        })
        assert "error" not in resp, resp
        return resp["result"]

    set_compositor(None)
    return call, set_compositor, cues


def test_no_compositor(stats):
    call, _, _ = stats
    assert call() == {"exists": False}


def test_compositor_without_pipeline(stats):
    call, set_compositor, _ = stats
    compositor = FakeCompositor()
    compositor.pipeline = None
    set_compositor(compositor)
    assert call() == {"exists": False}


def test_plain_base_sink(stats):
    call, set_compositor, _ = stats
    set_compositor(FakeCompositor(proj_sink=base_sink(100, 2, 25.0)))
    result = call()
    assert result["exists"] is True
    assert result["canvas"] == [1920, 1080]
    assert result["projection"] == {
        "rendered": 100, "dropped": 2, "average_rate": 25.0,
    }
    assert result["cues"] == []


def test_glimagesink_bin_reads_inner_sink(stats):
    """GstGLImageSinkBin has no stats; its "sink" child does."""
    call, set_compositor, _ = stats
    gl_bin = FakeElement(sink=base_sink(7, 0, 24.0))
    set_compositor(FakeCompositor(proj_sink=gl_bin))
    assert call()["projection"] == {
        "rendered": 7, "dropped": 0, "average_rate": 24.0,
    }


@pytest.mark.parametrize("sink", [
    FakeElement(),               # autovideosink: neither property
    FakeElement(sink=None),      # bin with no child yet
    FakeElement(sink=FakeElement()),  # child without stats
    None,                        # no sink (torn down)
])
def test_sink_without_stats_is_none(stats, sink):
    call, set_compositor, _ = stats
    set_compositor(FakeCompositor(proj_sink=sink))
    assert call()["projection"] is None


def test_cue_entries_carry_their_cue_id(stats):
    call, set_compositor, cues = stats
    sink_a = SimpleNamespace(video_appsink=base_sink(5, 0, 25.0))
    sink_b = SimpleNamespace(video_appsink=None)
    orphan = SimpleNamespace(video_appsink=None)
    reg_a = SimpleNamespace(frame_seen=True, caps=None)
    reg_b = SimpleNamespace(frame_seen=False, caps=None)
    reg_o = SimpleNamespace(frame_seen=False, caps=None)
    cues.extend([
        SimpleNamespace(id="plain"),  # no media (e.g. an action cue)
        SimpleNamespace(id="cue-a", media=FakeMedia(sink_a)),
        SimpleNamespace(id="cue-b", media=FakeMedia(sink_b)),
    ])
    set_compositor(FakeCompositor(
        proj_sink=base_sink(),
        registrations=[(sink_a, reg_a), (sink_b, reg_b), (orphan, reg_o)],
    ))

    entries = call()["cues"]

    assert [e["cue_id"] for e in entries] == ["cue-a", "cue-b", None]
    assert entries[0]["frame_seen"] is True
    assert entries[0]["appsink"]["rendered"] == 5
    assert entries[1]["appsink"] is None
    assert entries[0]["caps"] is None
