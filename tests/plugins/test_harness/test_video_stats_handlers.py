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

    invoked = []

    def fake_invoke(fn, timeout=10.0):
        # Stands in for the Qt main thread: records that the cue walk
        # was handed to it rather than run on the RPC thread.
        invoked.append(fn)
        return fn()

    monkeypatch.setattr(handlers, "invoke_on_main_thread", fake_invoke)
    call.invoked = invoked
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


def _cue_with_sink(cue_id):
    sink = SimpleNamespace(video_appsink=None)
    return SimpleNamespace(id=cue_id, media=FakeMedia(sink)), sink


def test_cue_model_is_walked_on_the_main_thread_once(stats):
    """The cue model belongs to the main thread: video.stats hands the
    walk to it, once per call, not once per registration."""
    call, set_compositor, cues = stats
    regs = []
    for n in range(3):
        cue, sink = _cue_with_sink(f"cue-{n}")
        cues.append(cue)
        regs.append((sink, SimpleNamespace(frame_seen=False, caps=None)))
    set_compositor(FakeCompositor(registrations=regs))
    entries = call()["cues"]
    assert [e["cue_id"] for e in entries] == ["cue-0", "cue-1", "cue-2"]
    assert len(call.invoked) == 1


class _MutatingModel:
    """A cue model the main thread changes while the RPC thread would
    walk it: iterating it the way the old handler did (once per
    registration, off the main thread) changes its size mid-walk."""

    def __init__(self, cues):
        self._cues = {c.id: c for c in cues}
        self.on_main_thread = False

    def __iter__(self):
        for cue in self._cues.values():
            if not self.on_main_thread:
                self._cues[f"added-{len(self._cues)}"] = SimpleNamespace(
                    id="late")
            yield cue


def test_cue_added_during_the_call_does_not_break_it(monkeypatch):
    cue, sink = _cue_with_sink("cue-a")
    # A cue without media first, so the walk must go on past a change.
    model = _MutatingModel([SimpleNamespace(id="plain"), cue])
    app = SimpleNamespace(cue_model=model)
    d = Dispatcher()
    handlers.register_all(d, app, signal_manager=None)

    def on_main_thread(fn, timeout=10.0):
        model.on_main_thread = True
        try:
            return fn()
        finally:
            model.on_main_thread = False

    monkeypatch.setattr(handlers, "invoke_on_main_thread", on_main_thread)
    monkeypatch.setattr(GstBackend, "_video_compositor", FakeCompositor(
        registrations=[(sink, SimpleNamespace(frame_seen=True, caps=None))],
    ))
    resp = d.dispatch({"jsonrpc": "2.0", "id": 1, "method": "video.stats",
                       "params": {}})
    assert "error" not in resp, resp
    assert resp["result"]["cues"][0]["cue_id"] == "cue-a"
