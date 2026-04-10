import pytest

from lisp.plugins.gst_backend.gi_repository import Gst


@pytest.fixture(scope="session", autouse=True)
def gst_init():
    """Initialize GStreamer once for the test session."""
    Gst.init([])
