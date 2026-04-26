# This file is part of Linux Show Player
#
# Copyright 2016 Francesco Ceruti <ceppofrancy@gmail.com>
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

from PyQt5.QtGui import QColor

from lisp.ui.themes.base import BaseTheme, ThemeColors


class Light(BaseTheme):
    Colors = ThemeColors(
        background=QColor(245, 245, 245),
        foreground=QColor(230, 230, 230),
        text=QColor(30, 30, 30),
        highlight=QColor(65, 155, 230),
        alternate_base=QColor(220, 220, 220),
        highlighted_text=QColor(255, 255, 255),
        bright_text=QColor(200, 0, 0),
    )
