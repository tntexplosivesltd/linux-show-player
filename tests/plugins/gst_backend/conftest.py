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
    tests/conftest.py:_guard_application_threads). Module-scoped, so
    a probe still running after its test ends is covered too."""
    with patch.object(
        SessionURI, "path_to_absolute", staticmethod(lambda p: p)
    ), patch.object(
        SessionURI, "path_to_relative", staticmethod(lambda p: p)
    ):
        yield
