import json
import threading
import time
from types import SimpleNamespace
from urllib.request import Request, urlopen

import pytest

from zipcontrol.guard_validation import _error_details, _wait_guard_event, _wait_pair_released
from zipcontrol.lab import LabNotVisible, TouchLab


def test_guard_waits_for_matching_async_command_event_instead_of_stop_iteration():
    guard = SimpleNamespace(
        condition=threading.Condition(),
        error=None,
        events=[
            {"reason": "heartbeat_expired", "command_id": 12, "request_id": 0},
            {"reason": "heartbeat_expired", "command_id": 13, "request_id": 186},
        ],
    )

    def later():
        with guard.condition:
            guard.events.append({"reason": "heartbeat_expired", "command_id": 13, "request_id": 0})
            guard.condition.notify_all()

    timer = threading.Timer(0.04, later)
    timer.start()
    try:
        event = _wait_guard_event(guard, "heartbeat_expired", 13, timeout=0.5)
        assert event["command_id"] == 13 and event["request_id"] == 0
    finally:
        timer.join()


def test_missing_guard_event_has_actionable_error():
    guard = SimpleNamespace(condition=threading.Condition(), error=None, events=[])
    with pytest.raises(AssertionError, match="heartbeat_expired.*13"):
        _wait_guard_event(guard, "heartbeat_expired", 13, timeout=0.01)


def test_delayed_previous_up_and_reused_id_on_old_page_do_not_end_current_gesture():
    # Matches the reported trace: UP #13 seq91 arrives alongside DOWN #14/#15 seq92/93.
    events = [
        {
            "kind": "up",
            "active": 0,
            "id": 13,
            "seq": 91,
            "page_id": "new",
            "host_received_at": time.monotonic(),
        },
        {
            "kind": "up",
            "active": 0,
            "id": 15,
            "seq": 99,
            "page_id": "old",
            "host_received_at": time.monotonic(),
        },
    ]
    pair = {"ids": (14, 15), "seq": 93, "page_id": "new"}

    def later():
        events.extend(
            [
                {
                    "kind": "up",
                    "active": 1,
                    "id": 14,
                    "seq": 95,
                    "page_id": "new",
                    "host_received_at": time.monotonic(),
                },
                {
                    "kind": "up",
                    "active": 0,
                    "id": 15,
                    "seq": 96,
                    "page_id": "new",
                    "host_received_at": time.monotonic(),
                },
            ]
        )

    timer = threading.Timer(0.04, later)
    timer.start()
    try:
        final = _wait_pair_released(SimpleNamespace(snapshot=lambda: list(events)), pair, timeout=0.5)
        assert final["seq"] == 96 and final["id"] == 15 and final["page_id"] == "new"
    finally:
        timer.join()


@pytest.mark.parametrize("exception", [StopIteration(), AssertionError()])
def test_blank_exception_is_reported_with_type_stage_and_traceback(tmp_path, exception):
    try:
        raise exception
    except Exception as exc:
        result = _error_details(exc, {"stage": "heartbeat_loss"}, tmp_path)
    assert result["error"] and type(exception).__name__ in result["error"]
    assert result["failed_stage"] == "heartbeat_loss"
    assert type(exception).__name__ in (tmp_path / "failure-traceback.txt").read_text()


class FakeAdb:
    def run(self, *args, **kwargs):
        if args[:2] == ("reverse", "--no-rebind"):
            self.target = args[-1]
            return "34567"
        if args == ("reverse", "--list"):
            return f"UsbFfs tcp:34567 {self.target}"
        return ""


def test_http_ignores_old_tab_ready_and_status_and_reports_current_load():
    lab = TouchLab(FakeAdb()).start()
    lab.expected_load = "current-load"
    base = f"http://127.0.0.1:{lab.server.server_port}"

    def post(event):
        req = Request(
            base + f"/events?token={lab.token}",
            data=json.dumps([event]).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(req) as response:
            assert response.status == 204

    try:
        for kind in ("ready", "status"):
            post({"kind": kind, "load_id": "old-load", "page_id": "old-page", "seq": 99})
        assert lab.layout is None and lab.snapshot() == []
        with urlopen(base + f"/touch-test?token={lab.token}&load=current-load") as response:
            assert response.status == 200
        post(
            {
                "kind": "ready",
                "load_id": "current-load",
                "page_id": "new-page",
                "seq": 1,
                "width": 400,
                "height": 700,
            }
        )
        assert lab.wait_ready(0.1)["page_id"] == "new-page"
        assert lab.diagnostics() == {
            "run": "current-load",
            "launch_attempts": 0,
            "page_requests": 1,
            "ready_received": True,
            "events_received": 1,
            "reverse_repairs": 0,
            "reverse_mapping_present": True,
        }
    finally:
        lab.close()


def test_missing_own_reverse_mapping_is_repaired_without_removing_other_ports():
    class Adb(FakeAdb):
        def __init__(self):
            self.missing = False
            self.binds = []

        def run(self, *args, **kwargs):
            if args[:2] == ("reverse", "--no-rebind"):
                self.binds.append(args)
                self.missing = False
            if args == ("reverse", "--list") and self.missing:
                return "UsbFfs tcp:33333 tcp:44444"
            return super().run(*args, **kwargs)

    adb = Adb()
    lab = TouchLab(adb).start()
    try:
        adb.missing = True
        lab.ensure_reverse()
        assert lab.reverse_repairs == 1
        assert adb.binds[-1] == ("reverse", "--no-rebind", "tcp:34567", f"tcp:{lab.server.server_port}")
    finally:
        lab.close()


def test_reverse_port_collision_does_not_overwrite_another_mapping():
    adb = FakeAdb()
    lab = TouchLab(adb).start()
    original_run = adb.run

    def collision(*args, **kwargs):
        assert args == ("reverse", "--list"), "Must not mutate the other session's mapping"
        return "UsbFfs tcp:34567 tcp:99999"

    try:
        adb.run = collision
        with pytest.raises(RuntimeError, match="another destination"):
            lab.ensure_reverse()
    finally:
        adb.run = original_run
        lab.close()


def test_page_setup_retries_after_temporary_adb_authorization_gap(monkeypatch):
    class Adb:
        def __init__(self):
            self.lists = 0
            self.launches = 0

        def run(self, *args, **kwargs):
            if args == ("reverse", "--list"):
                self.lists += 1
                if self.lists == 1:
                    raise RuntimeError("device unauthorized: allow USB debugging on the phone")
                return "UsbFfs tcp:34567 tcp:45678"
            assert args[:3] == ("shell", "am", "start")
            self.launches += 1
            return ""

    adb = Adb()
    lab = TouchLab(adb)
    lab.phone_port = 34567
    lab.server = SimpleNamespace(server_port=45678)

    def ready(timeout):
        if not adb.launches:
            raise LabNotVisible("waiting")
        return {"load_id": lab.expected_load}

    monkeypatch.setattr(lab, "wait_ready", ready)
    monkeypatch.setattr("zipcontrol.lab.time.sleep", lambda _: None)
    lab.open_phone()
    assert lab.launch_attempts == 2 and adb.launches == 1 and lab.setup_error is None
