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

import gc

import pytest
from PyQt5 import sip

from lisp.plugins.list_layout.list_view import CueListView


@pytest.fixture(autouse=True)
def _delete_list_views(monkeypatch):
    """Keep every CueListView a test builds alive until teardown, then
    delete it deterministically.

    A test's view sits in reference cycles (fake app, mock call
    records), so once the test returns only the cyclic GC frees it,
    at whatever moment it next runs. pytest-qt processes pending
    events right after the test body; when the GC frees a shown view
    in the middle of that (an expose repaint walking the window's
    children), Qt touches freed widgets and segfaults. qtbot.addWidget
    holds only a weak reference, so it does not prevent this. Same
    fix as the main_window fixture in tests/ui/test_window_geometry.py.
    """
    views = []
    original_init = CueListView.__init__

    def tracking_init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        views.append(self)

    monkeypatch.setattr(CueListView, "__init__", tracking_init)
    yield
    for view in views:
        if not sip.isdeleted(view):
            view.hide()
            sip.delete(view)
    views.clear()
    gc.collect()
