# This file is part of Linux Show Player
#
# Copyright 2018 Francesco Ceruti <ceppofrancy@gmail.com>
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

import random
from os import path

from lisp.core.loading import load_classes
from lisp.core.plugin import Plugin


class ActionCues(Plugin):
    Name = "Action Cues"
    Authors = ("Francesco Ceruti",)
    Description = "A collection of cues to extend base functions"

    def __init__(self, app):
        super().__init__(app)

        # Register all the cue in the plugin
        for _, cue_class in load_classes(__package__, path.dirname(__file__)):
            app.cue_factory.register_factory(cue_class.__name__, cue_class)
            app.window.registerSimpleCueMenu(cue_class, cue_class.Category)

        app.session_loaded.connect(
            lambda _session: ActionCues._shuffle_on_load(app)
        )

    @staticmethod
    def _shuffle_on_load(app):
        """Shuffle children of playlist GroupCues with shuffle enabled."""
        from lisp.plugins.action_cues.group_cue import GroupCue

        for cue in app.cue_model:
            if (
                isinstance(cue, GroupCue)
                and cue.group_mode == "playlist"
                and cue.shuffle
                and len(cue.children) > 1
            ):
                random.shuffle(cue.children)
