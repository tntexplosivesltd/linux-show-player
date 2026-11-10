# This file is part of Linux Show Player
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

"""The cue context menu for selections that mix TargetingCue types.

StopCue and ResumeCue are both `(TargetingCue, Cue)`. TargetingCue is a
mixin, not a Cue, so a mixed selection must still get the actions
registered against Cue (Edit, Remove, Group selected, ...).
"""

from lisp.cues.cue import Cue
from lisp.layout.cue_menu import CueContextMenu, SimpleMenuAction
from lisp.plugins.action_cues.resume_cue import ResumeCue
from lisp.plugins.action_cues.stop_cue import StopCue


def _menu_with_cue_action():
    menu = CueContextMenu()
    menu.add(
        SimpleMenuAction(
            "Single", lambda cue: None, "Group selected", lambda cues: None
        ),
        Cue,
    )
    return menu


def _texts(qmenu):
    return [a.text() for a in qmenu.actions() if not a.isSeparator()]


def test_mixed_stop_and_resume_selection_gets_cue_actions(mock_app, qtbot):
    cues = [StopCue(app=mock_app), ResumeCue(app=mock_app)]
    qmenu = _menu_with_cue_action().create_qmenu(cues, None)
    assert _texts(qmenu) == ["Group selected"]


def test_same_type_selection_still_gets_cue_actions(mock_app, qtbot):
    cues = [StopCue(app=mock_app), StopCue(app=mock_app)]
    qmenu = _menu_with_cue_action().create_qmenu(cues, None)
    assert _texts(qmenu) == ["Group selected"]


def _menu_with_stop_cue_action():
    menu = _menu_with_cue_action()
    menu.add(
        SimpleMenuAction(
            "Stop only", lambda cue: None, "Stop only", lambda cues: None
        ),
        StopCue,
    )
    return menu


def test_type_specific_action_kept_for_same_type_selection(mock_app, qtbot):
    # A helper that always returned Cue would drop the StopCue action.
    cues = [StopCue(app=mock_app), StopCue(app=mock_app)]
    qmenu = _menu_with_stop_cue_action().create_qmenu(cues, None)
    assert "Stop only" in _texts(qmenu)
    assert "Group selected" in _texts(qmenu)


def test_type_specific_action_dropped_for_mixed_selection(mock_app, qtbot):
    cues = [StopCue(app=mock_app), ResumeCue(app=mock_app)]
    qmenu = _menu_with_stop_cue_action().create_qmenu(cues, None)
    assert _texts(qmenu) == ["Group selected"]
