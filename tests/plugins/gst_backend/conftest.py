from concurrent.futures import ThreadPoolExecutor

import pytest
from unittest.mock import patch

from lisp.core.session_uri import SessionURI

from lisp.plugins.gst_backend.gi_repository import Gst


@pytest.fixture(scope="session", autouse=True)
def gst_init():
    """Initialize GStreamer once for the test session."""
    Gst.init([])


@pytest.fixture(autouse=True)
def clear_active_video_sinks():
    """Video exclusivity is a process-wide registry; a test that plays
    a VideoSink without stopping it must not block the next test."""
    from lisp.plugins.gst_backend.video_exclusive import active_video_sinks

    active_video_sinks.clear()
    yield
    active_video_sinks.clear()


@pytest.fixture(scope="module")
def bypass_session_paths():
    """Keep SessionURI from resolving paths through the Application
    singleton. Setting a UriInput's uri starts a duration probe on a
    worker thread, which reads the uri back through SessionURI; without
    this, Application() would be called there (see
    tests/conftest.py:_guard_application_threads). Module-scoped, and
    the probe pools are drained before unpatching, so a probe queued by
    any test of the module runs under the bypass."""
    with patch.object(
        SessionURI, "path_to_absolute", staticmethod(lambda p: p)
    ), patch.object(
        SessionURI, "path_to_relative", staticmethod(lambda p: p)
    ):
        yield
        drain_probe_pools()


def _probe_pools():
    """The duration-probe pools of UriInput and UriAvInput. Each is a
    one-worker ThreadPoolExecutor held only by the closure of the
    async_in_pool wrapper around the class's __duration."""
    from lisp.plugins.gst_backend.elements.uri_av_input import UriAvInput
    from lisp.plugins.gst_backend.elements.uri_input import UriInput

    pools = []
    for cls in (UriInput, UriAvInput):
        wrapper = getattr(cls, f"_{cls.__name__}__duration")
        for cell in wrapper.__closure__ or ():
            if isinstance(cell.cell_contents, ThreadPoolExecutor):
                pools.append(cell.cell_contents)
    assert len(pools) == 2, "probe pools not found: test helper is stale"
    return pools


def drain_probe_pools(timeout=30):
    """Wait for every queued duration probe: each pool has one worker
    and runs jobs in order, so a no-op submitted now finishes last."""
    for pool in _probe_pools():
        pool.submit(lambda: None).result(timeout=timeout)
