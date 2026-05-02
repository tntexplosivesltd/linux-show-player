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

"""Unit tests for pre_arm.status and pre_arm.wait_for_armed RPC handlers,
and for the pre_arm_manager.armed_set_changed signal manager registration.
"""

import time
from threading import Thread
from types import SimpleNamespace

import pytest

from lisp.core.signal import Signal
from lisp.cues.pre_arm_manager import ArmReason
from lisp.plugins.test_harness.dispatcher import Dispatcher
from lisp.plugins.test_harness.handlers import register_all
from lisp.plugins.test_harness.signal_manager import SignalManager


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_mgr(**kwargs):
    """Build a minimal fake PreArmManager-shaped object."""
    armed = kwargs.get("_armed", {})
    failed = kwargs.get("_failed", {})
    return SimpleNamespace(
        _armed=armed,
        _failed=failed,
        armed_set_changed=Signal(),
    )


def _make_app(mgr=None):
    ns = SimpleNamespace()
    if mgr is not None:
        ns.pre_arm_manager = mgr
    return ns


def _make_dispatcher(app):
    d = Dispatcher()
    register_all(d, app, signal_manager=None)
    return d


def _call(dispatcher, method, params=None):
    return dispatcher.dispatch({
        "jsonrpc": "2.0",
        "id": 1,
        "method": method,
        "params": params or {},
    })


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_methods_registered():
    """Guard against typos in handlers.py's `methods` dict."""
    d = Dispatcher()
    register_all(d, _make_app(), signal_manager=None)
    methods = d.list_methods()
    assert "pre_arm.status" in methods
    assert "pre_arm.wait_for_armed" in methods


# ---------------------------------------------------------------------------
# pre_arm.status tests
# ---------------------------------------------------------------------------

class TestPreArmStatus:

    def test_no_manager_returns_empty_dicts(self):
        """When app has no pre_arm_manager, return empty armed/failed."""
        app = _make_app(mgr=None)
        d = _make_dispatcher(app)
        resp = _call(d, "pre_arm.status")
        assert "result" in resp
        assert resp["result"] == {"armed": {}, "failed": {}}

    def test_empty_armed_set(self):
        """Manager present but no armed cues."""
        mgr = _make_mgr(_armed={}, _failed={})
        app = _make_app(mgr)
        d = _make_dispatcher(app)
        resp = _call(d, "pre_arm.status")
        assert resp["result"] == {"armed": {}, "failed": {}}

    def test_single_flag_preload(self):
        """Single ArmReason.Preload serialises to 'Preload'."""
        mgr = _make_mgr(_armed={"c1": ArmReason.Preload})
        app = _make_app(mgr)
        d = _make_dispatcher(app)
        resp = _call(d, "pre_arm.status")
        assert resp["result"]["armed"] == {"c1": "Preload"}
        assert resp["result"]["failed"] == {}

    def test_single_flag_auto(self):
        """Single ArmReason.Auto serialises to 'Auto'."""
        mgr = _make_mgr(_armed={"c2": ArmReason.Auto})
        app = _make_app(mgr)
        d = _make_dispatcher(app)
        resp = _call(d, "pre_arm.status")
        assert resp["result"]["armed"] == {"c2": "Auto"}

    def test_composite_flag_serializes_sensibly(self):
        """ArmReason.Auto | ArmReason.Preload produces a non-empty string
        that contains both flag names."""
        composite = ArmReason.Auto | ArmReason.Preload
        mgr = _make_mgr(_armed={"c1": composite})
        app = _make_app(mgr)
        d = _make_dispatcher(app)
        resp = _call(d, "pre_arm.status")
        reason_str = resp["result"]["armed"]["c1"]
        assert isinstance(reason_str, str)
        assert len(reason_str) > 0
        # Both flag names should be present in the string
        assert "Auto" in reason_str
        assert "Preload" in reason_str

    def test_failures_reported(self):
        """Failed cues appear in the 'failed' dict."""
        mgr = _make_mgr(
            _armed={},
            _failed={"c2": "audio decoder error"},
        )
        app = _make_app(mgr)
        d = _make_dispatcher(app)
        resp = _call(d, "pre_arm.status")
        assert resp["result"]["failed"] == {"c2": "audio decoder error"}
        assert resp["result"]["armed"] == {}

    def test_armed_and_failed_together(self):
        """Both armed and failed cues appear simultaneously."""
        mgr = _make_mgr(
            _armed={"c1": ArmReason.Preload},
            _failed={"c2": "cap reached"},
        )
        app = _make_app(mgr)
        d = _make_dispatcher(app)
        resp = _call(d, "pre_arm.status")
        assert resp["result"]["armed"] == {"c1": "Preload"}
        assert resp["result"]["failed"] == {"c2": "cap reached"}


# ---------------------------------------------------------------------------
# pre_arm.wait_for_armed tests
# ---------------------------------------------------------------------------

class TestPreArmWaitForArmed:

    def test_returns_immediately_if_already_armed(self):
        """If the cue is already armed, return without blocking."""
        mgr = _make_mgr(_armed={"c1": ArmReason.Preload})
        app = _make_app(mgr)
        d = _make_dispatcher(app)

        start = time.monotonic()
        resp = _call(d, "pre_arm.wait_for_armed",
                     {"cue_id": "c1", "timeout": 5.0})
        elapsed = time.monotonic() - start

        assert resp["result"]["armed"] is True
        assert resp["result"]["reason"] == "Preload"
        assert elapsed < 0.1  # must not have blocked

    def test_blocks_then_succeeds_when_signal_fires(self):
        """Blocks until armed_set_changed fires with the cue in _armed."""
        mgr = _make_mgr(_armed={}, _failed={})
        app = _make_app(mgr)
        d = _make_dispatcher(app)

        def arm_after_delay():
            time.sleep(0.1)
            mgr._armed["c1"] = ArmReason.Preload
            mgr.armed_set_changed.emit()

        t = Thread(target=arm_after_delay, daemon=True)
        t.start()

        start = time.monotonic()
        try:
            resp = _call(d, "pre_arm.wait_for_armed",
                         {"cue_id": "c1", "timeout": 2.0})
            elapsed = time.monotonic() - start
        finally:
            t.join(timeout=1.0)

        assert resp["result"]["armed"] is True
        assert resp["result"]["reason"] == "Preload"
        # Should have blocked ~100ms, not instant and not a full timeout
        assert 0.05 < elapsed < 0.5

    def test_times_out_cleanly(self):
        """Returns armed=False after timeout if the cue never arms."""
        mgr = _make_mgr(_armed={}, _failed={})
        app = _make_app(mgr)
        d = _make_dispatcher(app)

        start = time.monotonic()
        resp = _call(d, "pre_arm.wait_for_armed",
                     {"cue_id": "c1", "timeout": 0.1})
        elapsed = time.monotonic() - start

        assert resp["result"]["armed"] is False
        assert resp["result"]["reason"] is None
        # Should have waited roughly the timeout
        assert elapsed >= 0.05

    def test_requires_cue_id(self):
        """Calling without cue_id returns an AppError (-32000)."""
        mgr = _make_mgr()
        app = _make_app(mgr)
        d = _make_dispatcher(app)

        resp = _call(d, "pre_arm.wait_for_armed", {})
        assert "error" in resp
        assert resp["error"]["code"] == -32000
        assert "cue_id" in resp["error"]["message"]

    def test_no_manager_returns_not_armed(self):
        """When pre_arm_manager is absent, return armed=False immediately."""
        app = _make_app(mgr=None)
        d = _make_dispatcher(app)

        start = time.monotonic()
        resp = _call(d, "pre_arm.wait_for_armed",
                     {"cue_id": "c1", "timeout": 5.0})
        elapsed = time.monotonic() - start

        assert resp["result"]["armed"] is False
        assert resp["result"]["reason"] is None
        assert elapsed < 0.1

    def test_composite_reason_returned(self):
        """When cue is already armed with composite reason, it's serialized."""
        composite = ArmReason.Auto | ArmReason.Preload
        mgr = _make_mgr(_armed={"c1": composite})
        app = _make_app(mgr)
        d = _make_dispatcher(app)

        resp = _call(d, "pre_arm.wait_for_armed",
                     {"cue_id": "c1", "timeout": 1.0})
        assert resp["result"]["armed"] is True
        reason_str = resp["result"]["reason"]
        assert "Auto" in reason_str
        assert "Preload" in reason_str


# ---------------------------------------------------------------------------
# SignalManager: pre_arm_manager.armed_set_changed registration
# ---------------------------------------------------------------------------

class TestSignalManagerPreArmSignal:

    def _make_signal_manager(self, mgr):
        app = _make_app(mgr)
        return SignalManager(app)

    def test_resolves_armed_set_changed(self):
        """_resolve_signal returns the actual Signal object."""
        sig = Signal()
        mgr = SimpleNamespace(armed_set_changed=sig)
        sm = self._make_signal_manager(mgr)

        resolved = sm._resolve_signal("pre_arm_manager.armed_set_changed")
        assert resolved is sig

    def test_raises_if_manager_absent(self):
        """ValueError if pre_arm_manager is not on app."""
        app = _make_app(mgr=None)
        sm = SignalManager(app)

        with pytest.raises(ValueError, match="pre_arm_manager not available"):
            sm._resolve_signal("pre_arm_manager.armed_set_changed")

    def test_listed_in_list_signals(self):
        """armed_set_changed appears in list_signals output."""
        mgr = SimpleNamespace(armed_set_changed=Signal())
        sm = self._make_signal_manager(mgr)

        listed = sm.list_signals()
        assert "pre_arm_manager.armed_set_changed" in listed

    def test_subscribe_and_receive_event(self):
        """Full subscribe → emit → poll round-trip works."""
        real_sig = Signal()
        mgr = SimpleNamespace(armed_set_changed=real_sig)
        sm = self._make_signal_manager(mgr)

        sub_id = sm.subscribe("pre_arm_manager.armed_set_changed")
        real_sig.emit()

        events = sm.poll(sub_id)
        assert len(events) == 1
        assert events[0]["signal"] == "pre_arm_manager.armed_set_changed"

        sm.unsubscribe(sub_id)
