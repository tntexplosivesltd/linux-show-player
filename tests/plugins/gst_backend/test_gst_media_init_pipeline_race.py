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

import pytest

from lisp.plugins.gst_backend import elements as gst_elements
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
