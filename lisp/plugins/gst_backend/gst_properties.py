# This file is part of Linux Show Player
#
# Copyright 2021 Francesco Ceruti <ceppofrancy@gmail.com>
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

from threading import Event, Lock

from lisp.core.properties import Property
from lisp.core.session_uri import SessionURI

from .gi_repository import GstController, Gst

# Seconds GstPropertyController.set() waits for a buffer to anchor on.
SYNC_TIMEOUT = 1
# Slack (ms) under the anchor before remaining() reads the position as
# having jumped back (a loop seam or a backward seek).
SEEK_BACK_TOLERANCE = 250


class GstProperty(Property):
    def __init__(
        self, element_name, property_name, default=None, adapter=None, **meta
    ):
        super().__init__(default=default, **meta)
        self.element_name = element_name
        self.property_name = property_name
        self.adapter = adapter

    def __set__(self, instance, value):
        super().__set__(instance, value)

        if instance is not None:
            if self.adapter is not None:
                value = self.adapter(value)

            element = getattr(instance, self.element_name)
            element.set_property(self.property_name, value)


class GstURIProperty(GstProperty):
    def __init__(self, element_name, property_name, **meta):
        super().__init__(
            element_name,
            property_name,
            default="",
            adapter=self._adapter,
            **meta,
        )

    def __set__(self, instance, value):
        super().__set__(instance, SessionURI(value))

    def __get__(self, instance, owner=None):
        value = super().__get__(instance, owner)
        if isinstance(value, SessionURI):
            if value.is_local:
                return value.relative_path
            else:
                return value.uri

        return value

    def _adapter(self, value: SessionURI):
        return value.uri


class GstLiveProperty(Property):
    def __init__(self, element_name, property_name, adapter=None, **meta):
        super().__init__(**meta)
        self.element_name = element_name
        self.property_name = property_name
        self.adapter = adapter

    def __get__(self, instance, owner=None):
        if instance is None:
            return self
        else:
            element = getattr(instance, self.element_name)
            return element.get_property(self.property_name)

    def __set__(self, instance, value):
        if self.adapter is not None:
            value = self.adapter(value)

        element = getattr(instance, self.element_name)
        element.set_property(self.property_name, value)


class GstPropertyController:
    """Control a Gst.Element (controllable) property.

    This class leverage the GstController "lib" functionalities, allowing
    their usage in a "live" context where timing and values must be determined
    on the fly.

    To achieve this behavior an "identy" element (sync_element) is used to
    synchronize the user "request" with the actual pipeline processing.

    For this mechanism to work correctly there should not be any significant
    buffering in upstream elements (e.g. queues).
    """

    def __init__(
        self,
        pipeline: Gst.Pipeline,
        element: Gst.Element,
        sync_element: Gst.Element,
        property_name: str,
        interpolation_mode: int = GstController.InterpolationMode.CUBIC_MONOTONIC,
    ):
        self._pipeline = pipeline
        self._element = element
        self._sync_element = sync_element
        self._property_name = property_name

        self._sync_event = Event()
        # Guards the control source and the fields below against the
        # handoff callback (GStreamer streaming thread), the fader
        # worker threads and Volume.stop().
        self._sync_lock = Lock()
        self._control_points = {}
        self._delay = 0
        # Bumped by every set() and reset(): a fade owns the control
        # source only while the generation set() returned is current.
        self._generation = 0
        self._handoff_handle = None
        # Stream time (ns) the current points are anchored at, or None
        # while they wait for their first buffer.
        self._anchor = None
        # Highest position remaining() has seen for the current points.
        self._seen_position = None

        self._control_source = GstController.InterpolationControlSource.new()
        self._control_source.set_property("mode", interpolation_mode)

        self._control_binding = GstController.DirectControlBinding.new_absolute(
            self._element, self._property_name, self._control_source
        )
        self._element.add_control_binding(self._control_binding)

    @property
    def delay(self):
        return self._delay

    def set(self, control_points: dict):
        """Set the control points to be used to change the value.

        The points are anchored on the next buffer through the sync
        element. Returns a generation token for `finish()`, or None
        when the pipeline is not playing and nothing was anchored.
        """
        with self._sync_lock:
            self._generation += 1
            generation = self._generation
            self._disconnect_handoff()
            self._control_points = dict(control_points)
            self._anchor = None
            self._delay = 0
            self._sync_event.clear()

            # The callback will be called the next time a buffer is
            # "processed" by the sync_element.
            self._handoff_handle = self._sync_element.connect(
                "handoff", self._set_control_points, generation
            )

        # Wait for the callback to set the flag.
        # A timeout is set to avoid deadlocking if the callback is never called,
        # this might happen if there are no more buffers to process.
        self._sync_event.wait(SYNC_TIMEOUT)
        if self._sync_event.is_set():
            # Anchored by the handoff, or superseded by reset().
            return generation

        # No buffer came in time. Right after play() the sink can take
        # over a second to start pulling (M74): before, the points were
        # then never set and a fade-in cue stayed silent. Queried
        # outside the lock: the streaming thread may be waiting on it.
        _, current, pending = self._pipeline.get_state(0)
        playing = Gst.State.PLAYING in (current, pending)
        ok, position = (
            self._pipeline.query_position(Gst.Format.TIME)
            if playing
            else (False, 0)
        )

        with self._sync_lock:
            if generation != self._generation or self._sync_event.is_set():
                # A late handoff anchored, or a reset()/set() took over.
                return generation

            if not playing:
                # Stopped or paused: leave the level alone, as before.
                # This fade took the controller over (the generation
                # moved on), so the superseded fade can no longer
                # finish(): clear its points, or they would play out
                # on resume with no owner and override this fade.
                self._disconnect_handoff()
                self._control_points = {}
                self._anchor = None
                self._control_source.unset_all()
                self._sync_event.set()
                return None

            if ok:
                # Anchor at the current position. That is the sink's
                # render position, slightly behind the next buffer's
                # pts (the downstream buffering the handoff path
                # measures as `delay`), so the ramp starts a few
                # buffers in; the alternative was no ramp at all.
                self._disconnect_handoff()
                self._apply_control_points(position)
                self._sync_event.set()
            # Otherwise the position is unknown (and anchoring at 0
            # would be wrong for media with a start offset): keep the
            # handoff connected, the first buffer anchors the ramp.
            return generation

    def finish(self, generation, apply=None) -> bool:
        """End the fade `set()` returned `generation` for.

        Clears the control points and then calls `apply` (e.g. to pin
        the final value), atomically, but only if no later set() or
        reset() has replaced the fade; returns whether it did.
        """
        with self._sync_lock:
            if generation is None or generation != self._generation:
                return False
            try:
                self._reset_locked()
            finally:
                if apply is not None:
                    apply()
            return True

    def remaining(self, generation):
        """Milliseconds of the ramp `set()` returned `generation` for
        still ahead of the playback position, in stream time.

        None if that fade no longer owns the points. The whole ramp
        while it still waits for its first buffer. 0 when there is
        nothing worth waiting for: the position is past the ramp's
        end or unknown, the pipeline is not playing (stream time is
        frozen), or the position has jumped back - a loop seam (a
        non-flushing seek to start_time) or a backward seek - so the
        stream will not reach the ramp's end.
        """
        with self._sync_lock:
            if generation is None or generation != self._generation:
                return None
            ramp_ms = max(self._control_points, default=0)
            anchor = self._anchor
            delay = self._delay
            seen = self._seen_position
        if anchor is None:
            return ramp_ms

        _, current, pending = self._pipeline.get_state(0)
        if Gst.State.PLAYING not in (current, pending):
            return 0
        ok, position = self._pipeline.query_position(Gst.Format.TIME)
        if not ok:
            return 0

        # A handoff anchor sits `delay` ahead of the position.
        floor = anchor - (max(delay, 0) + SEEK_BACK_TOLERANCE) * Gst.MSECOND
        if position < floor or (seen is not None and position < seen):
            return 0
        with self._sync_lock:
            if generation == self._generation:
                self._seen_position = position

        end = anchor + ramp_ms * Gst.MSECOND
        return max(0, (end - position) // Gst.MSECOND)

    def reset(self):
        with self._sync_lock:
            self._reset_locked()

    def _reset_locked(self):
        self._generation += 1
        self._disconnect_handoff()
        # Wake a set() still waiting: its fade has been cancelled.
        self._sync_event.set()
        self._control_points = {}
        self._anchor = None
        self._seen_position = None
        self._control_source.unset_all()

    def _disconnect_handoff(self):
        if self._handoff_handle is not None:
            self._sync_element.disconnect(self._handoff_handle)
            self._handoff_handle = None

    def _set_control_points(
        self, element: Gst.Element, buffer: Gst.Buffer, generation: int
    ):
        with self._sync_lock:
            if generation != self._generation or self._sync_event.is_set():
                return
            try:
                start = buffer.pts

                # Calculate the difference between the buffer timestamp and the
                # current time, this allows precise timing (e.g. for fadeout)
                self._calc_sync_delay(start)
                self._apply_control_points(start)
            finally:
                # We only need one buffer. Then inform the thread that
                # called `set()` that we have set the control points.
                self._disconnect_handoff()
                self._sync_event.set()

    def _apply_control_points(self, start):
        self._anchor = start
        self._seen_position = None
        self._control_source.unset_all()

        for time, value in self._control_points.items():
            self._control_source.set(start + time * Gst.MSECOND, value)

    def _calc_sync_delay(self, start):
        ok, position = self._pipeline.query_position(Gst.Format.TIME)
        self._delay = (start - position) // Gst.MSECOND
