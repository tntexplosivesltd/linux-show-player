"""Utility module for importing and checking gi.repository packages once"""

import gi

gi.require_version("Gst", "1.0")
gi.require_version("GstController", "1.0")
gi.require_version("GstPbutils", "1.0")
gi.require_version("GstApp", "1.0")
# GstVideo typelib must be loaded so that GStreamer elements
# implementing the VideoOverlay interface expose
# set_window_handle() via GObject introspection.
gi.require_version("GstVideo", "1.0")

# noinspection PyUnresolvedReferences
from gi.repository import (
    GObject, GLib, Gst, GstController, GstPbutils, GstApp,
    GstVideo,  # noqa: F401 — imported for typelib side-effect
)
