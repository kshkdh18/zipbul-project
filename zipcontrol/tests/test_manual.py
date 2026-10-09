import os
import time
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest
from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QCheckBox, QDialogButtonBox

from zipcontrol.bridge import Frame
from zipcontrol.control import Stick
from zipcontrol.flight_gui import axis_hint
from zipcontrol.flight_profile import FlightProfileStore
from zipcontrol.guard import GuardBridge, GuardClient
from zipcontrol.gui import Window
from zipcontrol.manual import ManualHold, manual_targets


class Guard:
    def __init__(self):
        self.calls = []
        self.active = 0

    def command(self, left, right, ttl):
        self.calls.append(("command", left, right, ttl))
        self.active = sum(x is not None for x in (left, right))
        return self.snapshot()

    def manual_command(self, left, right, ttl):
        return self.command(left, right, ttl)

    def update(self):
        self.calls.append(("update",))
        return self.snapshot()

    def heartbeat(self):
        self.calls.append(("heartbeat",))

    def release(self, disarm=False):
        self.calls.append(("release", disarm))
        self.active = 0

    def snapshot(self):
        return {"active": self.active, "reason": "test"}


class Bridge(GuardBridge):
    def __init__(self):
        self.error = None
        self.guard = Guard()
        self.transport = SimpleNamespace(device_name="TEST")
        self.controller = SimpleNamespace(sticks=(Stick(200, 800, 50), Stick(600, 800, 50)), active={})
        self.now = time.monotonic
        self.frame_epoch = 1
        self.image = np.zeros((1200, 800, 3), dtype=np.uint8)

    def latest_frame(self):
        return Frame(self.image, int(self.now() * 1000), self.now(), self.now(), 0, self.frame_epoch)

    @property
    def fps(self):
        return 30

    def arm(self, package):
        self.guard.calls.append(("arm", package))

    def close(self):
        pass


def rig(max_seconds=3):
    bridge = Bridge()
    clock = [100.0]
    bridge.now = lambda: clock[0]
    hold = ManualHold(bridge, 1, -1, max_seconds, clock=bridge.now)
    return bridge, hold, clock


def test_sustained_manual_hold_reaches_target_and_renews_only_short_leases():
    b, h, t = rig()
    assert h.begin()
    for _ in range(42):
        h.pressed()
        assert h.tick()
        t[0] += 0.05
    writes = [x for x in b.guard.calls if x[0] == "command"]
    assert len(writes) >= 8 and all(x[3] == 500 for x in writes)
    assert all(x[1] == (0.0, -1.0) and x[2] is None for x in writes)
    assert h.target_points == [(200, 750), None] and h.distance_px == 50
    # The old implementation sent only one command and never advanced interpolation.
    assert len([x for x in b.guard.calls if x[0] == "update"]) >= 20
    assert not any(x[0] == "release" for x in b.guard.calls)
    h.stop()
    assert not h.tick() and b.guard.active == 0
    assert len([x for x in b.guard.calls if x[0] == "command"]) == len(writes)


@pytest.mark.parametrize("fault", ["released", "ui_stale", "video_stale", "geometry", "max_duration"])
def test_manual_hold_stops_and_never_renews_after_fault(fault):
    b, h, t = rig(max_seconds=1.5)
    assert h.begin() and h.tick()
    if fault == "released":
        h.stop()
    elif fault == "ui_stale":
        t[0] += 0.3
    elif fault == "video_stale":
        old = b.latest_frame()
        b.latest_frame = lambda: old
        t[0] += 0.6
        h.pressed()
    elif fault == "geometry":
        b.frame_epoch += 1
    else:
        t[0] += 1.5
        h.pressed()
    assert not h.tick() and b.guard.active == 0
    commands = len([x for x in b.guard.calls if x[0] == "command"])
    h.pressed()
    assert not h.tick()
    assert len([x for x in b.guard.calls if x[0] == "command"]) == commands


def test_release_while_arm_is_pending_never_sends_a_command():
    b, h, _ = rig()
    b.arm = lambda package: h.cancelled.set()
    assert not h.begin()
    assert not any(x[0] == "command" for x in b.guard.calls)
    assert ("release", True) in b.guard.calls


def test_axis_hints_describe_verified_mapping_including_y_inversion():
    profile = SimpleNamespace(axes=[["yaw", 1], ["vertical", -1], ["lateral", 1], ["forward", -1]])
    assert "상승" in axis_hint(1, -1, profile)
    assert "하강" in axis_hint(1, 1, profile)
    assert "후진" in axis_hint(3, 1, profile)
    assert axis_hint(0, 1, None) == "기본 축 설정: 우회전"


def test_optional_axis_dialog_saves_without_roi_or_verification_checkboxes(tmp_path):
    app = QApplication.instance() or QApplication([])
    window = Window()
    window.bridge = Bridge()
    window.bridge.adb = SimpleNamespace(serial="mock-phone")
    window.flight.store = FlightProfileStore(tmp_path)
    window.show()
    app.processEvents()
    window.tick()
    seen = []

    def save():
        dialog = app.activeModalWidget()
        seen.append(len(dialog.findChildren(QCheckBox)))
        dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.StandardButton.Save).click()
        # Avoid a hanging test if a future validation error keeps the dialog open.
        if dialog.isVisible():
            dialog.reject()

    try:
        assert window.flight.roi is None and window.flight.profile_button.isEnabled()
        QTimer.singleShot(0, save)
        window.flight.edit_profile()
        assert seen == [0]
        profile = window.flight.store.load("mock-phone", 800, 1200)
        assert profile is not None and profile.verified is False and profile.camera is None
    finally:
        window.close()
        app.processEvents()


@pytest.mark.parametrize("stop_with", ["release", "deactivate", "escape"])
def test_gui_keeps_pressed_button_enabled_and_stops_on_release_or_deactivate(stop_with):
    app = QApplication.instance() or QApplication([])
    window = Window()
    window.bridge = Bridge()
    window.tabs.setCurrentIndex(1)
    window.show()
    app.processEvents()
    window.tick()
    button = window.flight.test_buttons[0]
    try:
        QTest.mousePress(button, Qt.MouseButton.LeftButton)
        end = time.monotonic() + 1.2
        while time.monotonic() < end:
            app.processEvents()
            time.sleep(0.01)
        assert button.isEnabled() and button.isDown()
        assert window.flight.axis_testing
        assert window.bridge.guard.active == 1
        if stop_with == "deactivate":
            app.sendEvent(window, QEvent(QEvent.Type.ApplicationDeactivate))
        elif stop_with == "escape":
            QTest.keyClick(window, Qt.Key.Key_Escape)
        else:
            QTest.mouseRelease(button, Qt.MouseButton.LeftButton)
        commands = len([x for x in window.bridge.guard.calls if x[0] == "command"])
        end = time.monotonic() + 1
        while window.busy and time.monotonic() < end:
            app.processEvents()
            time.sleep(0.01)
        assert not window.busy and not window.flight.axis_testing
        assert window.bridge.guard.active == 0
        assert len([x for x in window.bridge.guard.calls if x[0] == "command"]) == commands
    finally:
        QTest.mouseRelease(button, Qt.MouseButton.LeftButton)
        window.close()
        app.processEvents()


@pytest.mark.parametrize(
    "axis,sign,expected",
    [
        (0, -1, ((-1.0, 0.0), None)),
        (0, 1, ((1.0, 0.0), None)),
        (1, -1, ((0.0, -1.0), None)),
        (1, 1, ((0.0, 1.0), None)),
        (2, -1, (None, (-1.0, 0.0))),
        (2, 1, (None, (1.0, 0.0))),
        (3, -1, (None, (0.0, -1.0))),
        (3, 1, (None, (0.0, 1.0))),
    ],
)
def test_full_radius_manual_buttons_use_only_the_selected_stick(axis, sign, expected):
    assert manual_targets(axis, sign, 1.0) == expected


@pytest.mark.parametrize("strength", [0, 0.04, 1.01, float("nan"), float("inf"), True])
def test_manual_strength_invalid_values_rejected(strength):
    with pytest.raises(ValueError):
        manual_targets(0, 1, strength)


def test_full_radius_ai_and_manual_use_distinct_protocol_lifetimes():
    g = GuardClient.__new__(GuardClient)
    g.status = {"epoch": 1}
    g.command_id = 0
    sent = []
    g.request = lambda op, **values: sent.append((op, values))
    g.manual_command((-1, 0), None, 500)
    assert sent[0][0] == "manual_command"
    assert sent[0][1]["targets"] == [[-1, 0], None]
    g.command((-1, 0), None, 2000)
    assert sent[1][0] == "command"
    assert sent[1][1]["targets"] == [[-1, 0], None]
    assert sent[1][1]["valid_for_ms"] == 2000
    with pytest.raises(ValueError, match="100%"):
        g.command((1, 1), None, 500)
    with pytest.raises(ValueError, match="2000ms"):
        g.command((1, 0), None, 2001)
    with pytest.raises(ValueError, match="100%"):
        g.manual_command((1, 1), None, 500)
    with pytest.raises(ValueError, match="500ms"):
        g.manual_command((1, 0), None, 501)
    assert len(sent) == 2


def test_manual_diagnostics_keep_acknowledgements_and_requested_positions():
    b, h, t = rig()
    assert h.begin() and h.tick()
    t[0] += 0.05
    h.pressed()
    assert h.tick()
    assert h.command_count == 1 and h.update_count == 1
    assert h.last_ack["active"] == 1
    assert h.events[0]["kind"] == "start"
    assert h.events[0]["target_points"] == [(200, 750), None]
    h.stop()
