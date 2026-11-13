import pytest

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
