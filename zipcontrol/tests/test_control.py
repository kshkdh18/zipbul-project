import math
import struct
import time

import pytest

from zipcontrol.control import Controller, Stick


class AndroidReceiver:
    """Independent protocol observer: reject MOVE/UP without DOWN or duplicate DOWN."""

    def __init__(self):
        self.active = {}
        self.max_active = 0
        self.events = []

    def send(self, data):
        assert len(data) % 32 == 0
        for offset in range(0, len(data), 32):
            kind, action, pid, x, y, width, height, pressure, ab, buttons = struct.unpack(
                ">BBQiiHHHII", data[offset : offset + 32]
            )
            assert kind == 2 and ab == buttons == 0
            assert 0 <= x < width and 0 <= y < height
            if action == 0:
                assert pid not in self.active and pressure == 65535
                self.active[pid] = (x, y)
            elif action == 2:
                assert pid in self.active
                self.active[pid] = (x, y)
            elif action == 1:
                assert pid in self.active and pressure == 0
                del self.active[pid]
            self.max_active = max(self.max_active, len(self.active))
            self.events.append((action, pid, x, y))


@pytest.fixture
def rig():
    observer = AndroidReceiver()
    controller = Controller(observer.send)
    controller.geometry(800, 1200)
    controller.calibrate(Stick(200, 800, 100), Stick(600, 800, 100), controller.epoch)
    yield controller, observer
    controller.close()


def test_independent_hold_move_and_release_without_lifting_other_pointer(rig):
    c, phone = rig
    c.set_sticks((0.5, 0), (-0.5, 0))
    assert phone.active == {1: (250, 800), 2: (550, 800)}
    c.set_sticks((0.5, 0.4), (-0.5, 0))
    assert phone.active == {1: (250, 840), 2: (550, 800)}
    assert sum(e[0] == 0 for e in phone.events) == 2
    c.set_sticks(None, (0, -0.4))
    assert phone.active == {2: (600, 760)}
    c.release_all()
    assert not phone.active and phone.max_active == 2


def test_radial_clamp_and_validation_before_any_input(rig):
    c, phone = rig
    c.set_sticks((100, 100), (-100, -100))
    assert math.dist(phone.active[1], (200, 800)) < 101
    before = list(phone.events)
    with pytest.raises(ValueError):
        c.set_sticks((0, 0), (float("nan"), 0))
    assert phone.events == before


def test_expiry_renewal_and_final_release(rig):
    c, phone = rig
    c.set_sticks((0.2, 0), (0.2, 0), ttl_ms=100)
    time.sleep(0.06)
    c.set_sticks((0.3, 0), (0.3, 0), ttl_ms=200)
    time.sleep(0.07)
    assert len(phone.active) == 2
    deadline = time.monotonic() + 0.8
    while phone.active and time.monotonic() < deadline:
        time.sleep(0.01)
    assert not phone.active and c.last_reason == "Command expired"


def test_new_capture_session_invalidates_even_same_size_and_old_calibration(rig):
    c, phone = rig
    old_epoch = c.epoch
    c.set_sticks((0.2, 0), (0.2, 0))
    c.geometry(800, 1200)
    assert not phone.active and c.sticks is None
    with pytest.raises(RuntimeError):
        c.set_sticks((0, 0), (0, 0))
    with pytest.raises(ValueError):
        c.calibrate(Stick(200, 800, 100), Stick(600, 800, 100), old_epoch)


def test_send_failure_disarms_and_does_not_replay():
    errors = []

    def fail(_):
        raise OSError("USB disconnected")

    c = Controller(fail, errors.append)
    try:
        c.geometry(800, 1200)
        c.calibrate(Stick(200, 800, 100), Stick(600, 800, 100), c.epoch)
        with pytest.raises(OSError):
            c.set_sticks((0.2, 0), (0.2, 0))
        assert c.sticks is None and not c.active and c.deadline == 0
        assert errors == ["USB disconnected"]
        with pytest.raises(RuntimeError):
            c.set_sticks((0, 0), (0, 0))
    finally:
        c.close()


def test_close_releases_and_refuses_further_input(rig):
    c, phone = rig
    c.set_sticks((0, 0), (0, 0))
    c.close()
    assert not phone.active
    with pytest.raises(RuntimeError):
        c.set_sticks((0, 0), (0, 0))
