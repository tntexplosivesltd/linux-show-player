# This file is part of Linux Show Player
#
# Copyright 2023 Francesco Ceruti <ceppofrancy@gmail.com>
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

import logging
import weakref
from threading import Lock, RLock

from lisp.backend.media import Media, MediaState
from lisp.core.properties import Property
from lisp.core.util import weak_call_proxy
from lisp.plugins.gst_backend import elements as gst_elements
from lisp.plugins.gst_backend.gi_repository import Gst
from lisp.plugins.gst_backend.gst_element import GstMediaElements
from lisp.plugins.gst_backend.gst_properties import GstURIProperty
from lisp.plugins.gst_backend.gst_utils import GstError
from lisp.ui.ui_utils import translate

logger = logging.getLogger(__name__)


GST_TO_MEDIA_STATE = {
    Gst.State.NULL: MediaState.Null,
    Gst.State.READY: MediaState.Ready,
    Gst.State.PAUSED: MediaState.Paused,
    Gst.State.PLAYING: MediaState.Playing,
}


def media_finalizer(pipeline, message_handler, media_elements):
    # Allow pipeline resources to be released
    pipeline.set_state(Gst.State.NULL)

    # Disconnect message handler
    bus = pipeline.get_bus()
    bus.remove_signal_watch()
    bus.disconnect(message_handler)

    # Dispose all the elements
    media_elements.clear()


class GstMedia(Media):
    """Media implementation based on the GStreamer framework."""

    pipe = Property(default=())
    elements = Property(default=GstMediaElements.class_defaults())

    def __init__(self):
        super().__init__()
        self.elements = GstMediaElements()

        self.__pipeline = None
        self.__finalizer = None
        self.__loop = 0  # current number of loops left to do
        self.__current_pipe = None  # A copy of the pipe property
        self.__armed = False  # True when pre-armed (pipeline in PAUSED)
        # What the armed pipeline was prerolled and seeked for (see
        # __armed_settings); play() skips the seek only while it holds.
        self.__armed_for = None
        # Serialises the arm state (__armed, __armed_for) and what is
        # done to an armed pipeline: edits re-seek it on the editing
        # (main) thread while play() and prearm() run on cue workers.
        # Always taken after __init_lock, never while holding it the
        # other way round: play() and prearm() build the pipeline
        # before taking it. Reentrant: play() emits signals under it.
        self.__arm_lock = RLock()
        # Serialises pipeline (re)builds. Without it, two threads
        # racing into __init_pipeline (e.g. PreArmManager.prearm on
        # the standby cue and the parallel-group's start firing
        # cue.media.play on the same cue) corrupt self.elements:
        # both clear() the shared container and then append into
        # different Gst.Pipeline instances, leaving a hybrid state
        # that GStreamer then spins on while trying to link
        # elements across pipelines.
        #
        # Deliberately a non-reentrant Lock — __init_pipeline must
        # NEVER be re-entered from within itself (a slot fired
        # during the rebuild that mutates `pipe`, `start_time`, or
        # otherwise loops back here is always a logic bug). RLock
        # would silently allow that recursion and corrupt state
        # the same way the original race did. A deadlock is the
        # right failure mode: it surfaces the bug immediately.
        self.__init_lock = Lock()

        self.changed("loop").connect(self.__on_loops_changed)
        self.changed("pipe").connect(self.__on_pipe_changed)
        self.changed("start_time").connect(self.__on_seek_setting_changed)
        self.changed("stop_time").connect(self.__on_seek_setting_changed)

    @Media.state.getter
    def state(self):
        if self.__pipeline is None:
            return MediaState.Null

        if self.__armed:
            return MediaState.Armed

        return GST_TO_MEDIA_STATE.get(
            self.__pipeline.get_state(Gst.MSECOND)[1], MediaState.Null
        )

    def current_time(self):
        if self.__pipeline is not None:
            ok, position = self.__pipeline.query_position(Gst.Format.TIME)
            return position // Gst.MSECOND if ok else 0

        return 0

    def play(self):
        if self.state == MediaState.Null:
            self.__init_pipeline()

        with self.__arm_lock:
            if self.state not in (
                MediaState.Ready, MediaState.Paused, MediaState.Armed,
            ):
                return

            self.on_play.emit(self)

            for element in self.elements:
                element.play()

            # Pre-armed: pipeline already in PAUSED and seeked. Skip the
            # preroll/seek work — that latency was paid at prearm time.
            # This is the latency saving. An edit not applied yet is
            # caught up here; if that fails, play as an unarmed cue.
            was_armed = self.__armed
            armed = was_armed and self.__refresh_armed()
            # Clear the arm flag — once we go to PLAYING, the state
            # property must derive from the live pipeline (Playing),
            # not keep reporting Armed via the override.
            self.__armed = False
            self.__armed_for = None

            if armed:
                pass
            elif was_armed and self.state == MediaState.Paused:
                # Still PAUSED where the arm left it, not a pause: play
                # from the start time, as an unarmed cue would.
                self.__seek(self.start_time)
            elif self.state == MediaState.Paused:
                self.__seek(self.current_time())
            else:  # Ready
                self.__pipeline.set_state(Gst.State.PAUSED)
                self.__pipeline.get_state(Gst.SECOND)
                self.__seek(self.start_time)

            self.__pipeline.set_state(Gst.State.PLAYING)
            self.__pipeline.get_state(Gst.SECOND)

        self.played.emit(self)

    def pause(self):
        if self.state == MediaState.Playing:
            self.on_pause.emit(self)

            for element in self.elements:
                element.pause()

            self.__pipeline.set_state(Gst.State.PAUSED)
            self.__pipeline.get_state(Gst.SECOND)

            # Flush the pipeline
            self.__seek(self.current_time())

            self.paused.emit(self)

    def stop(self):
        if self.state == MediaState.Armed:
            # An Armed pipeline holds audio device resources in PAUSED
            # state. stop() on Armed must release them — defer to
            # disarm() rather than emitting on_stop/stopped signals,
            # since the cue never started playing.
            self.disarm()
            return
        if self.state == MediaState.Playing or self.state == MediaState.Paused:
            self.on_stop.emit(self)

            for element in self.elements:
                element.stop()

            self.__pipeline.set_state(Gst.State.READY)
            self.__pipeline.get_state(Gst.SECOND)
            self.__reset_media()

            self.stopped.emit(self)
        elif self.state == MediaState.Ready:
            # Pipeline already in READY (e.g. EOS arrived during a
            # cue-level fade).  Still reset element state so live
            # properties (volume, alpha) aren't left at fade values.
            for element in self.elements:
                element.stop()

    def prearm(self) -> bool:
        """Drive the pipeline to PAUSED + seek to start_time.

        Returns False on any failure (file missing, decoder error, sink
        refused, preroll deadline exceeded). Logs WARNING on failure.
        Idempotent: returns True immediately if already Armed/Playing/Paused.
        """
        if self.state in (
            MediaState.Playing,
            MediaState.Paused,
            MediaState.Armed,
        ):
            return True

        if self.state == MediaState.Null:
            try:
                self.__init_pipeline()
            except Exception as exc:
                logger.warning(
                    "GstMedia.prearm: pipeline init failed: %s", exc
                )
                return False

        with self.__arm_lock:
            # Re-checked under the lock: a play() may have started it.
            if self.state != MediaState.Ready:
                return self.state in (
                    MediaState.Playing, MediaState.Paused, MediaState.Armed,
                )
            # Pipeline is in READY; drive it to PAUSED for preroll
            if not self.__preroll("prearm"):
                return False
            self.__armed = True
            self.__seek_armed(self.__armed_settings())

        self.armed.emit(self)
        return True

    def disarm(self) -> None:
        """Tear down an armed pipeline. Idempotent."""
        with self.__arm_lock:
            if self.state != MediaState.Armed:
                return
            self.__pipeline.set_state(Gst.State.NULL)
            self.__armed = False
            self.__armed_for = None
        self.disarmed.emit(self)

    def reseek(self, position: int) -> None:
        """Re-seek a pre-armed pipeline without tearing it down.

        Not needed for edits: an armed GstMedia applies start time,
        stop time, loop and file edits itself (__refresh_armed).
        """
        with self.__arm_lock:
            if self.state != MediaState.Armed:
                return
            if self.__seek(position):
                # The pipeline no longer matches start_time: play() will
                # seek it back unless start_time is set to `position`.
                self.__armed_for = (position,) + self.__armed_for[1:] \
                    if self.__armed_for is not None else None

    def seek(self, position):
        if self.__seek(position):
            self.sought.emit(self, position)

    def loop_release(self):
        self.__loop = 0

    def element(self, class_name):
        return getattr(self.elements, class_name, None)

    def drain_video(self, abort=None, deadline=None):
        sink = self.element("VideoSink")
        if sink is None:
            return True
        return sink.wait_drained(abort=abort, deadline=deadline)

    def input_uri(self):
        try:
            return self.elements[0].input_uri()
        except (IndexError, AttributeError):
            pass

    def update_properties(self, properties):
        # In order to update the other properties we need the pipeline first
        pipe = properties.pop("pipe", ())
        if pipe:
            self.pipe = pipe

        super().update_properties(properties)

    def __reset_media(self):
        # Image pipelines use a timer-based EOS that bypasses the
        # SEGMENT_DONE loop mechanism, so looping has no effect.
        # Detect by checking if the source element has no audio
        # output (src() returns None).
        try:
            if self.elements[0].src() is None:
                self.__loop = 0
                return
        except (IndexError, AttributeError):
            pass
        self.__loop = self.loop

    def __segment_stop_position(self):
        if 0 < self.stop_time < self.duration:
            return self.stop_time

        return self.duration

    def __seek(self, position, flush=True):
        if (
            self.state
            not in (MediaState.Playing, MediaState.Paused, MediaState.Armed)
            or position > self.__segment_stop_position()
        ):
            return False

        # Query segment info for the playback rate
        query = Gst.Query.new_segment(Gst.Format.TIME)
        self.__pipeline.query(query)
        rate = Gst.Query.parse_segment(query)[0]

        # Set the stop position, an early one or the end of the stream.
        # Always SET: SeekType.NONE would keep the segment's previous
        # stop, so a cleared stop time would still cut the cue short on
        # a pipeline seeked before (an armed one, re-seeked on edit).
        if self.stop_time > 0:
            stop = self.stop_time * Gst.MSECOND
        else:
            stop = -1  # GST_CLOCK_TIME_NONE: the end of the stream

        # Decide which SeekFlags we want to use
        flags = Gst.SeekFlags.TRICKMODE

        # We want to receive SEGMENT_DONE messages, allowing seamless loops,
        # except for the "last" loop, were we want to receive a normal EOS
        # to ensure that all pipeline buffers have been processed.
        if self.__loop != 0:
            flags |= Gst.SeekFlags.SEGMENT

        # While seeking, we typically want to flush any buffered data. However,
        # there are exceptions, such as during seamless looping, where flushing is undesirable.
        if flush:
            flags |= Gst.SeekFlags.FLUSH

        # Seek the pipeline
        return self.__pipeline.seek(
            rate if rate > 0 else 1,
            Gst.Format.TIME,
            flags,
            Gst.SeekType.SET,
            position * Gst.MSECOND,
            Gst.SeekType.SET,
            stop,
        )

    def __on_loops_changed(self, loops):
        self.__loop = loops
        self.__on_seek_setting_changed(loops)

    def __armed_settings(self):
        """What an armed pipeline is prerolled and seeked for: the
        start and stop times and the loop count (one seek: its range and
        SEGMENT flag), and the source file: the uri its GStreamer element
        holds, which is what READY->PAUSED opens. (The uri property reads
        back relative to the session folder, which moves when the session
        is saved elsewhere though the file does not.)"""
        uri = None
        try:
            source = self.elements[0]
            prop = getattr(type(source), "uri", None)
            if isinstance(prop, GstURIProperty):
                uri = getattr(source, prop.element_name).get_property(
                    prop.property_name
                )
        except (IndexError, AttributeError, TypeError):
            pass
        return self.start_time, self.stop_time, self.loop, uri

    def __seek_armed(self, settings):
        """Seek the armed pipeline for `settings` and record them. A
        failed seek records the file only, so the next refresh retries.
        Caller holds __arm_lock."""
        if self.__seek(settings[0]):
            self.__armed_for = settings
        else:
            self.__armed_for = (None, None, None, settings[3])
            return False
        return True

    def __preroll(self, caller):
        """READY -> PAUSED, waiting for the preroll. On failure the
        pipeline is set to NULL and the arm state cleared."""
        ret = self.__pipeline.set_state(Gst.State.PAUSED)
        if ret == Gst.StateChangeReturn.FAILURE:
            logger.warning("GstMedia.%s: set_state(PAUSED) FAILURE", caller)
        else:
            ret, *_ = self.__pipeline.get_state(Gst.SECOND)
            if ret == Gst.StateChangeReturn.SUCCESS:
                return True
            logger.warning(
                "GstMedia.%s: preroll did not complete (%s)", caller, ret
            )
        self.__pipeline.set_state(Gst.State.NULL)
        self.__armed = False
        self.__armed_for = None
        return False

    def __on_seek_setting_changed(self, _value):
        # The standby cue is armed, and it is also the cue being edited:
        # apply the edit now, so GO keeps the pre-arm latency saving.
        self.__on_armed_edit()

    def __on_source_changed(self, _uri):
        self.__on_armed_edit()

    def __on_armed_edit(self):
        # Unlocked fast path: a pipeline rebuild (which holds
        # __init_lock and resets __armed first) reloads the source uri;
        # taking __arm_lock there could deadlock with play().
        if not self.__armed:
            return
        with self.__arm_lock:
            if not self.__armed:
                return
            self.__refresh_armed()
            # A failed re-seek stays armed (play() retries it); a failed
            # preroll set the pipeline to NULL and cleared the arm. The
            # manager still lists the cue as armed until told.
            lost = not self.__armed
        if lost:
            self.arm_lost.emit(self)

    def __refresh_armed(self):
        """Bring an armed pipeline in line with edits made since it was
        armed; True when it is still armed. Caller holds __arm_lock.

        Start/stop time and loop edits re-seek it. A new file is
        prerolled again: uridecodebin opens its uri only on
        READY->PAUSED, so the armed one would play the old file.
        """
        current = self.__armed_settings()
        armed_for = self.__armed_for
        if current == armed_for:
            return True
        if armed_for is None or current[3] != armed_for[3]:
            self.__pipeline.set_state(Gst.State.READY)
            self.__pipeline.get_state(Gst.SECOND)
            if not self.__preroll("prearm"):
                return False
        return self.__seek_armed(current)

    def __on_pipe_changed(self, new_pipe):
        # Rebuild the pipeline only if something is changed
        # Kept as a tuple: a session file loads `pipe` as a list, and a
        # list never equals the tuple the rebuild fast path compares it
        # with, so every __init_pipeline would tear down a good pipeline.
        new_pipe = tuple(new_pipe)
        if new_pipe != self.__current_pipe:
            self.__current_pipe = new_pipe
            self.__init_pipeline()

    def __init_pipeline(self):
        # Serialise pipeline (re)builds. See __init__ for the race
        # this guards against. Held for the entire teardown+rebuild;
        # any other thread that wanted to (re)init will run AFTER us
        # against a fully-initialised pipeline rather than racing on
        # a half-cleared self.elements.
        with self.__init_lock:
            self.__init_pipeline_locked()

    def __init_pipeline_locked(self):
        # Skip-if-coherent fast path. When two threads race into
        # __init_pipeline (e.g. PreArmManager.prearm + cue.start →
        # media.play, the original symptom), the second thread
        # waits at __init_lock and arrives here AFTER the first
        # finished a full build. Re-running the build would tear
        # down a perfectly good pipeline (and, in the prearm-then-
        # play sequence, throw away the prearm latency benefit the
        # user paid for). Bail out if the live pipeline already
        # matches `pipe` and is in a usable state.
        if (
            self.__pipeline is not None
            and self.__current_pipe == tuple(self.pipe)
            and len(self.elements) == len(self.pipe)
        ):
            try:
                gst_state = self.__pipeline.get_state(0)[1]
            except Exception:
                gst_state = Gst.State.NULL
            if gst_state in (
                Gst.State.READY,
                Gst.State.PAUSED,
                Gst.State.PLAYING,
            ):
                return

        # Make a copy of the current elements properties
        elements_properties = self.elements.properties()

        # Pipeline is being torn down and rebuilt — any previous arm
        # state is invalid. Don't emit `disarmed` here; this is an
        # internal reset, not a user-visible disarm.
        self.__armed = False
        self.__armed_for = None

        # Call the current media-finalizer, if any
        if self.__finalizer is not None:
            # Set pipeline to NULL, finalize bus-handler and elements
            self.__finalizer()
            # weakref.finalize is single-shot: once called, alive=False
            # and subsequent calls are no-ops. If pipeline build below
            # raises, leaving this attribute set would cause the next
            # __init_pipeline to "call" a dead finalizer (silently
            # skipping cleanup) and then append on top of stale
            # elements. Drop the reference so the next entry treats
            # this as a fresh build.
            self.__finalizer = None

        self.__pipeline = Gst.Pipeline()
        # Add a callback to watch for pipeline bus-messages
        bus = self.__pipeline.get_bus()
        bus.add_signal_watch()
        # Use a weakref or GStreamer will hold a reference of the callback
        handler = bus.connect(
            "message", weak_call_proxy(weakref.WeakMethod(self.__on_message))
        )

        # Create all the new elements
        all_elements = gst_elements.all_elements()
        for element in self.pipe:
            try:
                self.elements.append(all_elements[element](self.__pipeline))
            except KeyError:
                logger.warning(
                    translate(
                        "GstMediaWarning", 'Invalid pipeline element: "{}"'
                    ).format(element)
                )
            except Exception:
                logger.warning(
                    translate(
                        "GstMediaError", 'Cannot create pipeline element: "{}"'
                    ).format(element),
                    exc_info=True,
                )

        # Post-link pass: allow compound elements to wire non-linear
        # branches (e.g. video paths from UriAVInput to VideoSink)
        for element in self.elements:
            element.post_link(self.elements)

        # Only a pipeline with a video branch adopts the projection's
        # shared clock: the pump offsets PTS by the two pipelines'
        # base-times, which is only meaningful under one clock. Audio-
        # only pipelines keep their automatic clock (usually the audio
        # sink's); slaved to the system clock instead, their sink would
        # resync on soundcard drift by dropping or inserting samples.
        # Guarded: the compositor may be absent or unavailable.
        if self.element("VideoSink") is not None:
            self.__adopt_shared_clock()

        # Reload the elements properties
        self.elements.update_properties(elements_properties)

        # A new file on an armed pipeline is prerolled when it is set
        try:
            self.elements[0].changed("uri").connect(self.__on_source_changed)
        except (IndexError, ValueError):
            pass

        # The source element should provide the duration
        self.elements[0].changed("duration").connect(self.__duration_changed)
        self.duration = self.elements[0].duration

        # Create a new finalizer object to free the pipeline when the media
        # is dereferenced
        self.__finalizer = weakref.finalize(
            self, media_finalizer, self.__pipeline, handler, self.elements
        )

        # Set the pipeline to READY
        self.__pipeline.set_state(Gst.State.READY)
        self.__pipeline.get_state(Gst.SECOND)

        self.elements_changed.emit(self)

    def __adopt_shared_clock(self):
        try:
            from lisp.plugins.gst_backend.gst_backend import GstBackend

            compositor = GstBackend.video_compositor()
            if compositor is not None and compositor.clock() is not None:
                self.__pipeline.use_clock(compositor.clock())
        except Exception:
            logger.debug(
                "GstMedia: shared clock unavailable, using auto clock",
                exc_info=True,
            )

    def __on_message(self, bus, message):
        if message.src == self.__pipeline:
            if message.type == Gst.MessageType.SEGMENT_DONE:
                if self.__loop != 0:
                    # If we still have loops to do then seek to start
                    self.__loop -= 1
                    self.__seek(self.start_time, flush=False)
                else:
                    # We reached loop 0 earlier (e.g. due to a loop-release).
                    # We cannot stop the pipeline yet, likely there's still data in the buffers,
                    # to "force" an EOS event we seek to the end of the stream, without flushing.
                    self.__seek(self.__segment_stop_position(), flush=False)

            elif message.type == Gst.MessageType.EOS:
                self.__pipeline.set_state(Gst.State.READY)
                self.__pipeline.get_state(Gst.SECOND)

                for element in self.elements:
                    element.eos()

                self.__reset_media()
                self.eos.emit(self)

            elif message.type == Gst.MessageType.CLOCK_LOST:
                self.__pipeline.set_state(Gst.State.PAUSED)
                self.__pipeline.set_state(Gst.State.PLAYING)

        if message.type == Gst.MessageType.ERROR:
            error, debug = message.parse_error()
            logger.error(
                f"GStreamer: {error.message}", exc_info=GstError(debug)
            )

            # Release per-element resources as stop() would. VideoSink
            # registered with the projection compositor in play(); left
            # registered, an errored cue counts as active forever and
            # VideoExclusiveManager refuses every later video cue. Each
            # element is guarded so one failure cannot skip the rest or
            # the error signal below.
            for element in self.elements:
                try:
                    element.stop()
                except Exception:
                    logger.exception(
                        "GstMedia: %s.stop() failed during error teardown",
                        type(element).__name__,
                    )

            # Set the pipeline to NULL
            self.__pipeline.set_state(Gst.State.NULL)
            self.__pipeline.get_state(Gst.SECOND)
            # Clear arm state — an Armed pipeline that errors out is no
            # longer armed; without this the state property would keep
            # reporting Armed despite the pipeline being NULL.
            # Note: we deliberately do NOT emit `disarmed` here. The
            # `disarmed` signal contract is "emitted by disarm()". The
            # `error` signal (emitted below) is the canonical channel
            # for "pipeline gone, including any armed state" — adding
            # `disarmed` would be redundant for `error` subscribers.
            self.__armed = False
            self.__armed_for = None
            self.__reset_media()

            self.error.emit(self)

    def __duration_changed(self, duration):
        self.duration = duration
