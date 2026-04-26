# This file is part of Linux Show Player
#
# Copyright 2026
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


class System:
    """Pass-through theme: applies no palette and no stylesheet — Qt's
    default style takes over. Selected by users who want their system
    Qt theme (Adwaita, Breeze, Fusion) to drive LiSP's appearance.
    """

    def apply(self, qt_app):
        from lisp.ui import themes
        themes._active = self
