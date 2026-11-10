# This file is part of Linux Show Player
#
# Copyright 2025 Thomas Sherlock
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

"""Image cues through the projection pump, end to end in-process.

The image NULL-on-EOS special case is gone: an image cue now goes
READY on its timer EOS like any cue, and its imagefreeze stream is
pumped like video. A real GstMedia (ImageInput -> VideoSink) feeds a
real projection appsrc -> fakesink on the shared clock; the cue's bus
messages go through GstMedia's own handler. Played twice, so a replay
from READY after EOS is covered too. No audio: an image has no audio
source, so VideoSink removes its audio sink before PAUSED.
"""

from unittest.mock import MagicMock, patch

import pytest

from lisp.plugins.gst_backend import elements as gst_elements
from lisp.plugins.gst_backend import video_compositor as vc
from lisp.plugins.gst_backend.gi_repository import Gst
from lisp.plugins.gst_backend.gst_media import GstMedia
from lisp.plugins.gst_backend.video_exclusive import active_video_sinks

_CM = "lisp.plugins.gst_backend.gst_backend.GstBackend.video_compositor"

DURATION_MS = 300


@pytest.fixture(scope="module", autouse=True)
def load_elements():
    gst_elements.load()


@pytest.fixture(scope="module")
def tiny_png(tmp_path_factory):
    path = tmp_path_factory.mktemp("image") / "slide.png"
    pipeline = Gst.parse_launch(
        "videotestsrc num-buffers=1 ! video/x-raw,width=32,height=24 "
        f"! pngenc ! filesink location={path}"
    )
    pipeline.set_state(Gst.State.PLAYING)
    msg = pipeline.get_bus().timed_pop_filtered(
        5 * Gst.SECOND, Gst.MessageType.EOS | Gst.MessageType.ERROR)
    pipeline.set_state(Gst.State.NULL)
    assert msg is not None and msg.type == Gst.MessageType.EOS
    return path


class _Projection:
    """A stand-in compositor around a real appsrc -> fakesink pipeline
    that has been running (primed) before any cue joins, as the real
    projection does from process start."""

    def __init__(self):
        self.clock = Gst.SystemClock.obtain()
        self.pipeline = Gst.Pipeline.new("projection-image-test")
        self.pipeline.use_clock(self.clock)
        self.appsrc = Gst.ElementFactory.make("appsrc", None)
        vc._configure_appsrc(self.appsrc)
        sink = Gst.ElementFactory.make("fakesink", None)
        sink.set_property("sync", True)
        sink.set_property("signal-handoffs", True)
        self.pipeline.add(self.appsrc)
        self.pipeline.add(sink)
        assert self.appsrc.link(sink)
        self.rendered = 0
        self._primed = False
        sink.connect("handoff", self._on_handoff)

        comp = MagicMock()
        comp.pipeline = self.pipeline
        comp.clock.return_value = self.clock
        comp.latency.side_effect = lambda: vc.query_min_latency(
            self.pipeline)
        comp.register.side_effect = self._register

        def fit(reg, caps):
            reg.caps = caps

        comp.fit_registration.side_effect = fit
        self.comp = comp

    def _on_handoff(self, _sink, _buf, _pad):
        if self._primed:
            self.rendered += 1
        else:
            self._primed = True

    def _register(self, _sink):
        reg = vc.Registration()
        reg.appsrc = self.appsrc
        return reg

    def start(self):
        self.pipeline.set_state(Gst.State.PLAYING)
        caps = Gst.Caps.from_string(
            "video/x-raw,format=I420,width=16,height=16,framerate=30/1")
        self.appsrc.set_property("caps", caps)
        prime = Gst.Buffer.new_allocate(None, 16 * 16 * 3 // 2, None)
        prime.pts = self.clock.get_time() - self.pipeline.get_base_time()
        self.appsrc.push_buffer(prime)
        deadline = self.clock.get_time() + 5 * Gst.SECOND
        while not self._primed and self.clock.get_time() < deadline:
            self.pipeline.get_bus().timed_pop(10 * Gst.MSECOND)
        assert self._primed

    def stop(self):
        self.pipeline.set_state(Gst.State.NULL)


def _play_until_eos(media):
    """media.play(), then dispatch the cue's bus to GstMedia until the
    image timer's EOS has been handled (no main loop runs here)."""
    ended = []

    def on_eos(_media):
        ended.append(True)

    media.eos.connect(on_eos)
    media.play()
    bus = media._GstMedia__pipeline.get_bus()
    deadline = Gst.SystemClock.obtain().get_time() + 5 * Gst.SECOND
    while not ended and Gst.SystemClock.obtain().get_time() < deadline:
        msg = bus.timed_pop(20 * Gst.MSECOND)
        if msg is not None:
            media._GstMedia__on_message(bus, msg)
            assert msg.type != Gst.MessageType.ERROR, (
                msg.parse_error()[0].message)
    media.eos.disconnect(on_eos)
    assert ended, "image cue never reached EOS"


def test_image_frames_reach_projection_and_eos_unregisters(tiny_png):
    projection = _Projection()
    projection.start()
    media = None
    try:
        with patch(_CM, return_value=projection.comp):
            media = GstMedia()
            media.pipe = ("ImageInput", "VideoSink")
            image = media.elements[0]
            image.uri = f"file://{tiny_png}"
            image.duration = DURATION_MS
            sink = media.element("VideoSink")

            for run in range(2):  # the replay comes from READY
                before = projection.rendered
                projection.comp.reset_mock()
                _play_until_eos(media)

                # imagefreeze frames were pumped and shown, so the
                # handoff hook fired for a lingering predecessor.
                assert projection.rendered > before, f"run {run}"
                projection.comp.frame_ready.assert_called()
                # The timer EOS ended the cue like any other.
                projection.comp.unregister.assert_called_once_with(sink)
                assert not active_video_sinks.contains(sink)
                assert media._GstMedia__pipeline.get_state(0)[1] == (
                    Gst.State.READY)
    finally:
        if media is not None:
            with patch(_CM, return_value=None):
                media.stop()
        projection.stop()
