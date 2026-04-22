# This file is part of Linux Show Player
#
# Copyright 2026 Francesco Ceruti <ceppofrancy@gmail.com>
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
"""Shared fader-orchestration helpers for the Fade & Stop / Fade & Resume
action cues. Underscore prefix keeps this module out of ActionCues'
load_classes cue-registration loop.
"""

import logging

logger = logging.getLogger(__name__)


def build_affected_set(target):
    """Flatten target (and any nested GroupCues) to a list of leaf cues.

    GroupCue membership is resolved via `_resolve_children()`; nested
    groups are flattened recursively. The target itself is returned
    as a single-element list when it is not a GroupCue.
    """
    # Local import to avoid a circular import at module load time
    # (group_cue imports from cues.cue, and this module is imported
    # from stop_cue / resume_cue which live in the same package).
    from lisp.plugins.action_cues.group_cue import GroupCue

    if not isinstance(target, GroupCue):
        return [target]

    leaves = []
    for child in target._resolve_children():
        leaves.extend(build_affected_set(child))
    return leaves
