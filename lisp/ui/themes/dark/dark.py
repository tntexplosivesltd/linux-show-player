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

import os

from PyQt5.QtGui import QColor

# Import resources
# noinspection PyUnresolvedReferences
from . import assets
from lisp.ui.themes.base import BaseTheme, ThemeColors


class Dark(BaseTheme):
    Colors = ThemeColors(
        background=QColor(30, 30, 30),
        foreground=QColor(52, 52, 52),
        text=QColor(230, 230, 230),
        highlight=QColor(65, 155, 230),
    )
    QssPath = os.path.join(os.path.dirname(__file__), "theme.qss")
