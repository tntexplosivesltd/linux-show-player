# This file is part of Linux Show Player
#
# Copyright 2024 Linux Show Player Contributors
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

import json
from enum import Enum

from lisp.core.has_properties import HasProperties
from lisp.cues.cue import CueState


# Map individual state bits to names
_STATE_NAMES = {
    CueState.Invalid: "Invalid",
    CueState.Error: "Error",
    CueState.Stop: "Stop",
    CueState.Running: "Running",
    CueState.Pause: "Pause",
    CueState.PreWait: "PreWait",
    CueState.PostWait: "PostWait",
    CueState.PreWait_Pause: "PreWait_Pause",
    CueState.PostWait_Pause: "PostWait_Pause",
}


def state_name(state):
    """Convert a CueState integer to a human-readable string.

    Composite states are joined with '|' (e.g. 'Running|PostWait').
    """
    if state == CueState.Invalid:
        return "Invalid"

    names = []
    for bit, name in _STATE_NAMES.items():
        if bit and state & bit:
            names.append(name)

    return "|".join(names) if names else "Unknown"


def serialize_cue_brief(cue):
    """Serialize a cue to a brief dict for list views."""
    return {
        "id": cue.id,
        "name": cue.name,
        "_type_": cue._type_,
        "index": cue.index,
        "state": cue.state,
        "state_name": state_name(cue.state),
    }


def serialize_cue(cue):
    """Serialize a cue to a full properties dict with runtime state."""
    props = cue.properties()
    props["state"] = cue.state
    props["state_name"] = state_name(cue.state)
    props["current_time"] = cue.current_time()
    props["prewait_time"] = cue.prewait_time()
    props["postwait_time"] = cue.postwait_time()
    props["is_fading"] = cue.is_fading()
    return props


def serialize_signal_args(*args):
    """Serialize signal emission arguments to JSON-safe values."""
    from lisp.cues.cue import Cue

    result = []
    for arg in args:
        if isinstance(arg, Cue):
            result.append(serialize_cue_brief(arg))
        elif isinstance(arg, Enum):
            result.append(arg.value)
        elif isinstance(arg, (str, int, float, bool, type(None))):
            result.append(arg)
        elif isinstance(arg, (list, tuple)):
            result.append([serialize_signal_args(a)[0] if isinstance(a, (Cue, Enum)) else a for a in arg])
        elif isinstance(arg, dict):
            result.append(arg)
        else:
            result.append(str(arg))
    return result


class LispJsonEncoder(json.JSONEncoder):
    """JSON encoder that handles LiSP-specific types."""

    def default(self, obj):
        if isinstance(obj, Enum):
            return obj.value
        if isinstance(obj, HasProperties):
            return obj.properties()
        return super().default(obj)
