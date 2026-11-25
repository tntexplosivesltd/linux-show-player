"""Regression test for the __init_pipeline race condition.

Repro scenario in production: PreArmManager.prearm and cue.start.media.play
can both reach GstMedia.__init_pipeline on the same media object from
different threads — typically when a standby cue is being auto-armed at
the same instant a parallel GroupCue starts firing its children. Before
the fix, both threads cleared the shared `self.elements` container and
then appended fresh elements into *different* Gst.Pipeline instances,
leaving a half-rebuilt state where:

* the elements list was shorter or longer than `self.pipe` warranted,
* element instances belonged to one pipeline while linked into another,
* the captured `elements_properties` dict held defaults, so the URI /
  duration of the first child got reset to "" / 0 on restore.

The fix wraps the body of `__init_pipeline` in `self.__init_lock`, so a
second thread waits for the first to finish its full teardown+rebuild
before running its own (possibly redundant) rebuild — but always against
a coherent live state.
"""

import threading
import time
import wave

import pytest

from lisp.backend.media import MediaState
from lisp.plugins.gst_backend import elements as gst_elements
from lisp.plugins.gst_backend.gi_repository import Gst
from lisp.plugins.gst_backend.gst_media import GstMedia


@pytest.fixture(scope="module", autouse=True)
def load_elements():
    gst_elements.load()


class TestInitPipelineRace:
    def test_concurrent_pipe_set_keeps_elements_consistent(self):
        """Two threads driving __init_pipeline simultaneously must
        not corrupt the shared elements container.

        We provoke the race by re-assigning `media.pipe` from two
        threads with fresh tuple instances each time so
        `__on_pipe_changed`'s equality short-circuit doesn't kick
        in and __init_pipeline actually re-runs every time.

        Without the lock, the elements list ends up mixed across
        pipelines: len(elements) drifts away from len(pipe) and
        elements with the same `typename` collide on the shared
        InstanceProperty slot, leaving the container in a
        half-rebuilt state.

        We assert AFTER the threads join that the live state is
        coherent: |elements| == |pipe| and all elements are
        live GstMediaElements.
        """
        media = GstMedia()
        target = ("UriInput", "Volume", "AutoSink")
        media.pipe = target

        barrier = threading.Barrier(2)

        def worker():
            barrier.wait()
            # Force a rebuild several times to widen the race
            # window and exercise both teardown and append paths.
            for _ in range(20):
                media.pipe = tuple(target)

        t1 = threading.Thread(target=worker)
        t2 = threading.Thread(target=worker)
        t1.start()
        t2.start()
        t1.join(timeout=10)
        t2.join(timeout=10)

        assert not t1.is_alive(), "init thread 1 stuck"
        assert not t2.is_alive(), "init thread 2 stuck"

        # Live state must match the pipe length and contain one
        # instance per declared element type. Pre-fix this would
        # routinely come back with len < 3 or with the elements
        # split across two distinct Gst.Pipeline instances.
        elements = list(media.elements)
        assert len(elements) == len(target), (
            f"elements out of sync with pipe after race: "
            f"got {[type(e).__name__ for e in elements]}"
        )
        type_names = [type(e).__name__ for e in elements]
        for name in target:
            assert name in type_names, (
                f"missing {name} after concurrent __init_pipeline: "
                f"have {type_names}"
            )

    def test_init_pipeline_lock_exists(self):
        """Smoke test: the GstMedia instance has the init lock the
        race fix relies on. Catches accidental removal of the lock
        (e.g. during a refactor) before the race re-emerges."""
        media = GstMedia()
        # Name-mangled attribute name for `__init_lock` in GstMedia.
        assert hasattr(media, "_GstMedia__init_lock"), (
            "GstMedia is missing __init_lock — the __init_pipeline "
            "race-condition fix has been removed."
        )

    def test_init_pipeline_serialises_concurrent_calls(self, monkeypatch):
        """Two threads entering `__init_pipeline` must observe
        strict serialisation: while one thread is in the locked
        body, the other must block until it exits.

        We instrument `__init_pipeline_locked` to record max
        concurrent entries and add a deliberate yield-point. Pre-fix
        (no lock around the body) this would record 2 — both threads
        in the body simultaneously. With the lock it records 1.
        """
        media = GstMedia()
        # Initial pipeline build, so the second pipe= is a rebuild
        # (which is the path that caused the production bug).
        media.pipe = ("UriInput", "Volume", "AutoSink")

        in_flight = [0]
        max_observed = [0]
        observe_lock = threading.Lock()

        original = GstMedia._GstMedia__init_pipeline_locked

        def instrumented(self):
            with observe_lock:
                in_flight[0] += 1
                max_observed[0] = max(max_observed[0], in_flight[0])
            try:
                # Yield-point that widens the race window. With the
                # outer lock held, no other thread reaches this
                # body. Without it, both threads sleep here at once
                # and `max_observed` ticks to 2.
                time.sleep(0.005)
                original(self)
            finally:
                with observe_lock:
                    in_flight[0] -= 1

        monkeypatch.setattr(
            GstMedia,
            "_GstMedia__init_pipeline_locked",
            instrumented,
        )

        # Call the (mangled) __init_pipeline directly so the
        # equality short-circuit in __on_pipe_changed doesn't
        # suppress the rebuild.
        init = media._GstMedia__init_pipeline  # noqa: SLF001
        barrier = threading.Barrier(2)

        def worker():
            barrier.wait()
            for _ in range(5):
                init()

        t1 = threading.Thread(target=worker)
        t2 = threading.Thread(target=worker)
        t1.start()
        t2.start()
        t1.join(timeout=10)
        t2.join(timeout=10)

        assert max_observed[0] == 1, (
            f"two threads entered __init_pipeline body concurrently "
            f"(max in-flight={max_observed[0]}) — the lock is missing "
            f"or ineffective"
        )


@pytest.mark.usefixtures("bypass_session_paths")
class TestInitPipelineSkipsCoherentRebuild:
    """A second __init_pipeline on a usable pipeline must keep it.

    A session file stores `pipe` as a JSON list, so a loaded cue gets a
    list, while the fast path compared it against `tuple(self.pipe)`: a
    list never equals a tuple, so every call rebuilt. When the standby
    pre-arm and GO both found the music cue's pipeline in NULL (after a
    disarm), the second rebuild finalised the pipeline the first had
    just set PLAYING: the cue showed Running, stuck at 0 (2026-11-25
    rehearsal, "music stalls on the second time through").
    """

    @pytest.mark.parametrize("pipe", [
        ("UriInput", "Volume", "AutoSink"),
        ["UriInput", "Volume", "AutoSink"],
    ], ids=["tuple", "list-from-session"])
    def test_second_init_keeps_the_ready_pipeline(self, pipe):
        media = GstMedia()
        media.update_properties({"pipe": pipe})
        built = media._GstMedia__pipeline  # noqa: SLF001
        assert built is not None

        assert built.get_state(0)[1] == Gst.State.READY

        media._GstMedia__init_pipeline()  # noqa: SLF001

        assert media._GstMedia__pipeline is built, (
            "a coherent READY pipeline was torn down and rebuilt"
        )

    def test_armed_pipeline_survives_the_second_caller(self, tmp_path):
        """The rehearsal interleaving, minus the threads: the first
        caller has the pipeline prerolled (here armed: PAUSED, silent)
        when the second, which also saw Null, reaches __init_pipeline.
        It must keep that pipeline, not finalise it to NULL."""
        path = tmp_path / "tone.wav"
        with wave.open(str(path), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(48000)
            w.writeframes(b"\x00\x00" * 48000)
        media = GstMedia()
        media.update_properties({"pipe": ["UriInput", "Volume", "AutoSink"]})
        media.elements[0].uri = f"file://{path}"
        try:
            assert media.prearm()
            built = media._GstMedia__pipeline  # noqa: SLF001

            media._GstMedia__init_pipeline()  # noqa: SLF001

            assert media._GstMedia__pipeline is built
            assert media.state == MediaState.Armed
        finally:
            media.disarm()

    def test_unknown_element_does_not_force_a_rebuild(self):
        """A pipe naming an element this machine lacks builds without
        it; the next __init_pipeline must still keep that pipeline."""
        media = GstMedia()
        media.update_properties(
            {"pipe": ["UriInput", "NoSuchElement", "AutoSink"]}
        )
        built = media._GstMedia__pipeline  # noqa: SLF001
        assert len(media.elements) == 2

        media._GstMedia__init_pipeline()  # noqa: SLF001

        assert media._GstMedia__pipeline is built

    @pytest.mark.parametrize("seq", [list, tuple], ids=["list", "tuple"])
    def test_same_length_element_swap_rebuilds(self, seq):
        """A real pipe change (a preset, the pipe editor) of the same
        length must rebuild with the new elements."""
        media = GstMedia()
        media.update_properties(
            {"pipe": seq(("UriInput", "Volume", "AutoSink"))}
        )
        built = media._GstMedia__pipeline  # noqa: SLF001

        media.update_properties(
            {"pipe": seq(("UriInput", "AudioPan", "AutoSink"))}
        )

        assert media._GstMedia__pipeline is not built
        assert [type(e).__name__ for e in media.elements] == [
            "UriInput", "AudioPan", "AutoSink",
        ]
