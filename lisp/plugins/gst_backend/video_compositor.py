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

import logging

from lisp.plugins.gst_backend.gi_repository import Gst

logger = logging.getLogger(__name__)

# Projection format. Kept modest; the later mixing spec may make this
# configurable. Background layer + both sinks negotiate against this.
COMP_WIDTH = 1920
COMP_HEIGHT = 1080
COMP_FPS = 30


def _have_factory(name):
    """True if a GStreamer element factory of this name exists."""
    return Gst.ElementFactory.find(name) is not None


def plan_pipeline():
    """Decide the projection pipeline's element factories.

    Primary path is GL (glupload → glvideomixer → glimagesink), which
    keeps compositing on the GPU and pairs natively with glimagesink.
    When GL is unavailable, fall back to a system-memory pipeline
    (compositor → xvimagesink/autovideosink) with no glupload on the
    inputs. Mirrors the factory-probe pattern in video_sink.py.
    """
    if (
        _have_factory("glupload")
        and _have_factory("glvideomixer")
        and _have_factory("glimagesink")
    ):
        return {
            "gl": True,
            "upload": "glupload",
            "mixer": "glvideomixer",
            "sink": "glimagesink",
        }

    if _have_factory("xvimagesink"):
        sink = "xvimagesink"
    else:
        sink = "autovideosink"
    return {"gl": False, "upload": None, "mixer": "compositor", "sink": sink}
