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

from lisp.core.has_properties import HasPropertiesMeta
from lisp.core.properties import Property


class TargetingCue(metaclass=HasPropertiesMeta):
    """Adds reactive target-validity tracking to a cue.

    Cues with a `target_id` property mix this in and gain an
    `invalid_target` boolean Property that flips to True whenever the
    target is empty or unresolvable in the current cue model. Widgets
    subscribe to `cue.changed("invalid_target")` to react.

    `invalid_target` is derived state. On session load it is
    recomputed in `__init__`, so any value that was serialized to disk
    is overwritten with the fresh truth.
    """

    invalid_target = Property(default=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if "target_id" in self.properties_names():
            self.changed("target_id").connect(self._recheck_target)
        self.app.cue_model.item_added.connect(self._on_model_change)
        self.app.cue_model.item_removed.connect(self._on_model_change)
        self._recheck_target()

    def _resolve_targets(self) -> bool:
        """True iff every target this cue references resolves in the model.

        Single-target cues use the default. List-style cues (e.g.
        CollectionCue) override this.
        """
        target_id = getattr(self, "target_id", "")
        if not target_id:
            return False
        return self.app.cue_model.get(target_id) is not None

    def _recheck_target(self, *_):
        invalid = not self._resolve_targets()
        if invalid != self.invalid_target:
            self.invalid_target = invalid

    def _on_model_change(self, cue):
        # Only recheck if this cue could be affected.
        if cue.id == getattr(self, "target_id", "") or self.invalid_target:
            self._recheck_target()
