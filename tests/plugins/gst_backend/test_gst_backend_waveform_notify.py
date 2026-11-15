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

"""A failed waveform must notify the operator.

`Signal` holds slots weakly; the handler that posts the notification
has to be kept alive for as long as the waveform is (same bug class as
merge-review finding H25).
"""

import gc
from types import SimpleNamespace
from unittest.mock import MagicMock

from lisp.plugins.gst_backend.gst_backend import GstBackend
from lisp.ui.widgets.notification import NotificationLevel


def test_waveform_failure_notifies_operator(mock_app):
    backend = SimpleNamespace(app=mock_app)
    uri = MagicMock()
    uri.unquoted_uri = "/media/missing.wav"

    # Unbound call with a stand-in `self`: the real GstBackend is a
    # plugin that needs the whole application.
    waveform = GstBackend.uri_waveform(backend, uri, duration=1000)
    gc.collect()

    waveform.failed.emit()

    mock_app.notify.emit.assert_called_once_with(
        'Cannot generate waveform for "/media/missing.wav"',
        NotificationLevel.Warning,
    )
