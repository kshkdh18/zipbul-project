import json
import socket
import struct
import threading

import pytest
from test_mission import executor

from zipcontrol.guard import PROTOCOL, GuardClient, GuardRejected
from zipcontrol.protocol import read_exact


def test_first_disarm_survives_rejection_stop_and_clears_on_new_arm():
    client_socket, device_socket = socket.socketpair()
    fail_reason = ["heartbeat_expired"]

    def emit(request_id, reason, armed, ok=True):
        payload = json.dumps(
            {
                "protocol": PROTOCOL,
                "request_id": request_id,
                "reason": reason,
                "armed": armed,
                "ok": ok,
                "injection_ok": True,
                "epoch": 1,
                "command_id": 0,
            }
        ).encode()
        device_socket.sendall(b"\xc8" + struct.pack(">I", len(payload)) + payload)

    def server():
        try:
            while True:
                assert read_exact(device_socket, 1) == b"\xc8"
                size = struct.unpack(">I", read_exact(device_socket, 4))[0]
                request = json.loads(read_exact(device_socket, size))
                op, rid = request["op"], request["request_id"]
                if op == "arm":
                    emit(rid, "armed", True)
                elif op == "heartbeat":
                    emit(0, fail_reason[0], False)
                    emit(0, "rejected", False)
                    emit(rid, "not armed", False, False)
                else:
                    emit(rid, op, False)
        except (OSError, EOFError):
            pass

    worker = threading.Thread(target=server, daemon=True)
    worker.start()
    client = GuardClient(client_socket)
    try:
        client.request("arm")
        with pytest.raises(GuardRejected, match="heartbeat_expired.*not armed") as error:
            client.heartbeat()
        assert error.value.status["reason"] == "not armed"
        assert error.value.diagnostics["first_disarm"]["reason"] == "heartbeat_expired"
        client.release(True)
        assert client.diagnostics()["status"]["reason"] == "stop"
        assert client.diagnostics()["first_disarm"]["reason"] == "heartbeat_expired"
        client.request("arm")
        assert client.diagnostics()["first_disarm"] is None
        fail_reason[0] = "foreground_changed"
        with pytest.raises(GuardRejected, match="foreground_changed"):
            client.heartbeat()
    finally:
        client.close()
        client_socket.shutdown(socket.SHUT_RDWR)
        client_socket.close()
        device_socket.close()
        worker.join(1)


def test_executor_records_original_cause_before_cleanup_ack(tmp_path):
    bridge, runner = executor(tmp_path)
    bridge.armed = False
    bridge.diagnostics = lambda: {
        "first_disarm": {"reason": "heartbeat_expired"},
        "status": {"armed": False, "reason": "not armed"},
        "recent_events": [],
    }
    runner.tick()
    assert not runner.running and runner.reason == "android_disarmed: heartbeat_expired"
    events = [json.loads(line) for line in (tmp_path / "events.jsonl").read_text().splitlines()]
    diagnostics = next(e for e in events if e["kind"] == "guard_diagnostics")
    assert diagnostics["first_disarm"]["reason"] == "heartbeat_expired"
    assert [e["kind"] for e in events].index("guard_diagnostics") < [e["kind"] for e in events].index(
        "release_ack"
    )
    assert not [call for call in bridge.calls if call[0] in ("arm", "command")]


def test_diagnostic_write_failure_cannot_skip_physical_release(tmp_path):
    bridge, runner = executor(tmp_path)
    bridge.diagnostics = lambda: {}
    original = runner.journal.event

    def write(kind, **kwargs):
        if kind == "guard_diagnostics":
            raise OSError("disk unavailable")
        original(kind, **kwargs)

    runner.journal.event = write
    with pytest.raises(OSError):
        runner.stop()
    assert ("release", True) in bridge.calls
    assert not runner.running and runner.stop_event.is_set()
