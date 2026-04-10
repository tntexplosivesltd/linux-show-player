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

import logging
import time
import threading
from collections import deque
from uuid import uuid4

from lisp.core.signal import Connection
from lisp.plugins.test_harness.serializers import serialize_signal_args

logger = logging.getLogger(__name__)

# Signals available on the Application singleton
_APP_SIGNALS = {
    "session.session_created",
    "session.session_loaded",
    "session.session_before_finalize",
    "app.notify",
}

# Signals available on app.cue_model
_MODEL_SIGNALS = {
    "cue_model.item_added",
    "cue_model.item_removed",
    "cue_model.model_reset",
}

# Signals available on app.layout
_LAYOUT_SIGNALS = {
    "layout.cue_executed",
    "layout.all_executed",
}

# Signals available on app.commands_stack
_COMMANDS_SIGNALS = {
    "commands.done",
    "commands.undone",
    "commands.redone",
}

# Signals available on individual cues
_CUE_SIGNALS = {
    "started", "stopped", "paused", "interrupted",
    "error", "end", "next",
    "prewait_start", "prewait_ended", "prewait_paused", "prewait_stopped",
    "postwait_start", "postwait_ended", "postwait_paused", "postwait_stopped",
    "fadein_start", "fadein_end", "fadeout_start", "fadeout_end",
    "property_changed",
}


class Subscription:
    """A signal subscription with an event buffer."""

    __slots__ = (
        "id", "signal_path", "signal_obj", "callback",
        "events", "notify",
    )

    def __init__(self, signal_path, signal_obj, callback, max_buffer):
        self.id = str(uuid4())
        self.signal_path = signal_path
        self.signal_obj = signal_obj
        self.callback = callback
        self.events = deque(maxlen=max_buffer)
        self.notify = threading.Event()


class SignalManager:
    """Manages signal subscriptions for the test harness.

    Allows subscribing to LiSP signals by dot-path name, buffering
    emitted events, and blocking wait_for queries.
    """

    def __init__(self, app, max_buffer=1000):
        self._app = app
        self._max_buffer = max_buffer
        self._subscriptions = {}
        self._lock = threading.Lock()

    def subscribe(self, signal_path, cue_id=None):
        """Subscribe to a signal by dot-path name.

        :param signal_path: e.g. 'cue_model.item_added' or 'cue.started'
        :param cue_id: Required for per-cue signals (cue.* paths)
        :returns: subscription_id string
        :raises ValueError: If signal path is invalid
        """
        signal_obj = self._resolve_signal(signal_path, cue_id)

        # Build the actual signal path for per-cue signals
        full_path = signal_path
        if cue_id and signal_path.startswith("cue."):
            full_path = f"cue.{cue_id}.{signal_path[4:]}"

        # Create a callback that captures the subscription
        # We must store a strong reference to this so Signal's
        # weak reference doesn't expire immediately
        def make_callback(sub):
            def on_signal(*args, **kwargs):
                event = {
                    "signal": sub.signal_path,
                    "timestamp": time.time(),
                    "args": serialize_signal_args(*args),
                }
                sub.events.append(event)
                sub.notify.set()
            return on_signal

        # Create subscription first so callback can reference it
        sub = Subscription.__new__(Subscription)
        sub.id = str(uuid4())
        sub.signal_path = full_path
        sub.signal_obj = signal_obj
        sub.events = deque(maxlen=self._max_buffer)
        sub.notify = threading.Event()

        callback = make_callback(sub)
        sub.callback = callback

        signal_obj.connect(callback, mode=Connection.Direct)

        with self._lock:
            self._subscriptions[sub.id] = sub

        logger.debug("Subscribed to %s (id=%s)", full_path, sub.id)
        return sub.id

    def unsubscribe(self, subscription_id):
        """Remove a subscription and disconnect the signal."""
        with self._lock:
            sub = self._subscriptions.pop(subscription_id, None)

        if sub is None:
            raise ValueError(f"Subscription not found: {subscription_id}")

        sub.signal_obj.disconnect(sub.callback)
        logger.debug("Unsubscribed %s (id=%s)", sub.signal_path, sub.id)

    def unsubscribe_all(self):
        """Remove all subscriptions."""
        with self._lock:
            subs = list(self._subscriptions.values())
            self._subscriptions.clear()

        for sub in subs:
            try:
                sub.signal_obj.disconnect(sub.callback)
            except Exception:
                pass

    def poll(self, subscription_id, clear=True):
        """Return buffered events for a subscription.

        :param subscription_id: The subscription to poll
        :param clear: If True, clear the buffer after reading
        :returns: List of event dicts
        """
        with self._lock:
            sub = self._subscriptions.get(subscription_id)

        if sub is None:
            raise ValueError(f"Subscription not found: {subscription_id}")

        events = list(sub.events)
        if clear:
            sub.events.clear()
            sub.notify.clear()

        return events

    def wait_for(self, subscription_id, timeout=10.0, match=None):
        """Block until a matching event arrives or timeout.

        :param subscription_id: The subscription to wait on
        :param timeout: Maximum seconds to wait
        :param match: Optional dict of key-value pairs to match in the event
        :returns: The matching event dict
        :raises TimeoutError: If no matching event within timeout
        :raises ValueError: If subscription not found
        """
        with self._lock:
            sub = self._subscriptions.get(subscription_id)

        if sub is None:
            raise ValueError(f"Subscription not found: {subscription_id}")

        deadline = time.monotonic() + timeout

        while True:
            # Snapshot the deque to avoid concurrent mutation issues
            snapshot = list(sub.events)
            for i, event in enumerate(snapshot):
                if self._matches(event, match):
                    # Remove this event and all before it
                    for _ in range(min(i + 1, len(sub.events))):
                        try:
                            sub.events.popleft()
                        except IndexError:
                            break
                    return event

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(
                    f"Timed out waiting for signal "
                    f"({sub.signal_path}, timeout={timeout}s)"
                )

            # Wait for notification with short timeout to recheck
            sub.notify.wait(timeout=min(0.1, remaining))
            sub.notify.clear()

    def list_signals(self):
        """Return list of available signal names."""
        signals = sorted(
            _APP_SIGNALS | _MODEL_SIGNALS | _LAYOUT_SIGNALS | _COMMANDS_SIGNALS
        )
        signals.append("cue.<cue_id>.<signal_name>")
        return signals

    def _resolve_signal(self, signal_path, cue_id=None):
        """Resolve a dot-path signal name to an actual Signal object."""
        if signal_path in _APP_SIGNALS:
            attr = signal_path.split(".", 1)[1]
            return getattr(self._app, attr)

        if signal_path in _MODEL_SIGNALS:
            attr = signal_path.split(".", 1)[1]
            return getattr(self._app.cue_model, attr)

        if signal_path in _LAYOUT_SIGNALS:
            if self._app.session is None:
                raise ValueError("No active session (no layout)")
            attr = signal_path.split(".", 1)[1]
            return getattr(self._app.layout, attr)

        if signal_path in _COMMANDS_SIGNALS:
            attr = signal_path.split(".", 1)[1]
            return getattr(self._app.commands_stack, attr)

        # Per-cue signals: "cue.<signal_name>" with cue_id param
        if signal_path.startswith("cue."):
            signal_name = signal_path[4:]
            if signal_name not in _CUE_SIGNALS:
                raise ValueError(
                    f"Unknown cue signal: {signal_name}. "
                    f"Available: {sorted(_CUE_SIGNALS)}"
                )
            if cue_id is None:
                raise ValueError(
                    "cue_id is required for per-cue signal subscriptions"
                )
            cue = self._app.cue_model.get(cue_id)
            if cue is None:
                raise ValueError(f"Cue not found: {cue_id}")
            return getattr(cue, signal_name)

        available = sorted(
            _APP_SIGNALS | _MODEL_SIGNALS | _LAYOUT_SIGNALS
            | _COMMANDS_SIGNALS
        )
        raise ValueError(
            f"Unknown signal: {signal_path}. "
            f"Available: {available} and cue.<signal_name>"
        )

    @staticmethod
    def _matches(event, match):
        """Check if an event dict matches the given criteria."""
        if match is None:
            return True

        for key, value in match.items():
            # Support matching nested in args
            if key == "args":
                if event.get("args") != value:
                    return False
            elif event.get(key) != value:
                # Also check inside args list (for convenience)
                found = False
                for arg in event.get("args", []):
                    if isinstance(arg, dict) and arg.get(key) == value:
                        found = True
                        break
                if not found:
                    return False

        return True
