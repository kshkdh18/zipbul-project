"""Authenticated by the private scrcpy connection; no remotely reachable control HTTP API."""

from __future__ import annotations

import json
import math
import socket
import struct
import threading
import time
from pathlib import Path

from .adb import Transport
from .bridge import Bridge
from .protocol import read_exact

PROTOCOL = "jipbul-guard-4"


def targets(left, right, limit=1.0):
    result = []
    for xy in (left, right):
        if xy is None:
            result.append(None)
            continue
        if not isinstance(xy, (list, tuple)) or len(xy) != 2:
            raise ValueError("Two coordinates required")
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in xy):
            raise ValueError("Finite coordinates required")
        if math.hypot(*xy) > limit + 0.0000001:
            raise ValueError(f"Each stick is limited to {limit * 100:g}% of its radius")
        result.append(list(xy))
    return result


class GuardClient:
    def __init__(self, sock):
        self.sock = sock
        self.sock.settimeout(None)
        self.send_lock = threading.Lock()
        self.condition = threading.Condition()
        self.request_id = 0
        self.command_id = 0
        self.responses = {}
        self.status = {}
        self.error = None
        self.events = []
        self.closed = False
        self.thread = threading.Thread(target=self._read, name="guard-events", daemon=True)
        self.thread.start()
        status = self.request("hello")
        if status.get("protocol") != PROTOCOL:
            raise RuntimeError("Required device guard protocol unavailable")

    def _read(self):
        try:
            while not self.closed:
                if read_exact(self.sock, 1) != b"\xc8":
                    raise ValueError("Unexpected guard message")
                size = struct.unpack(">I", read_exact(self.sock, 4))[0]
                if not 0 < size <= 8192:
                    raise ValueError("Invalid guard message length")
                status = json.loads(read_exact(self.sock, size))
                if status.get("protocol") != PROTOCOL:
                    raise ValueError("Guard identity mismatch")
                with self.condition:
                    self.status = status
                    self.events.append({**status, "host_received_at": time.monotonic()})
                    self.events = self.events[-3000:]
                    if status["request_id"]:
                        self.responses[status["request_id"]] = status
                        if len(self.responses) > 100:
                            self.responses.pop(next(iter(self.responses)))
                    self.condition.notify_all()
        except Exception as exc:
            with self.condition:
                self.error = str(exc)
                self.condition.notify_all()

    def request(self, op, timeout=0.5, **values):
        with self.send_lock:
            if self.error or self.closed:
                raise RuntimeError(self.error or "Guard closed")
            self.request_id += 1
            request_id = self.request_id
            message = json.dumps({"op": op, "request_id": request_id, **values}, allow_nan=False).encode()
            # A wedged writer must not block the UI indefinitely. Device leases remain independent.
            import select

            packet = memoryview(b"\xc8" + struct.pack(">I", len(message)) + message)
            send_deadline = time.monotonic() + 0.1
            while packet:
                remaining = send_deadline - time.monotonic()
                if remaining <= 0 or not select.select([], [self.sock], [], remaining)[1]:
                    raise TimeoutError("Guard socket not writable")
                try:
                    sent = self.sock.send(packet, socket.MSG_DONTWAIT)
                except BlockingIOError:
                    continue
                if not sent:
                    raise EOFError("Guard socket closed")
                packet = packet[sent:]
        deadline = time.monotonic() + timeout
        with self.condition:
            while request_id not in self.responses:
                if self.error:
                    raise RuntimeError(self.error)
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError(f"Guard acknowledgement timeout: {op}")
                self.condition.wait(remaining)
            status = self.responses.pop(request_id)
        if not status["ok"] or not status["injection_ok"]:
            raise RuntimeError("Android guard: " + status["reason"])
        return status

    def arm(self, sticks, package="dji.go.v5"):
        status = self.request("hello")
        self.command_id = max(self.command_id, status["command_id"])
        return self.request(
            "arm", epoch=status["epoch"], package=package, sticks=[[s.x, s.y, s.radius] for s in sticks]
        )

    def command(self, left, right, valid_for_ms=2000):
        xy = targets(left, right)
        if type(valid_for_ms) is not int or not 100 <= valid_for_ms <= 2000:
            raise ValueError("Command lifetime must be 100–2000ms")
        self.command_id += 1
        return self.request(
            "command",
            epoch=self.status["epoch"],
            command_id=self.command_id,
            valid_for_ms=valid_for_ms,
            targets=xy,
        )

    def heartbeat(self):
        return self.request("heartbeat", epoch=self.status["epoch"])

    def manual_command(self, left, right, valid_for_ms=500):
        xy = targets(left, right, limit=1.0)
        if type(valid_for_ms) is not int or not 100 <= valid_for_ms <= 500:
            raise ValueError("Manual command lifetime must be 100–500ms")
        self.command_id += 1
        return self.request(
            "manual_command",
            epoch=self.status["epoch"],
            command_id=self.command_id,
            valid_for_ms=valid_for_ms,
            targets=xy,
        )

    def update(self):
        return self.request("update", epoch=self.status["epoch"], command_id=self.command_id)

    def release(self, disarm=False):
        return self.request("stop" if disarm else "release")

    def snapshot(self):
        with self.condition:
            return dict(self.status)

    def close(self):
        if not self.closed:
            try:
                self.release(disarm=True)
            except Exception:
                pass
            self.closed = True


class GuardBridge(Bridge):
    def __init__(self, serial=None, server_path=None, **kwargs):
        path = Path(server_path) if server_path else Path.cwd() / "artifacts/android/scrcpy-server"
        if not path.is_file():
            raise RuntimeError("AI 서버를 먼저 빌드하세요: uv run --frozen python android/build.py")
        super().__init__(serial, str(path), **kwargs)
        self.transport = Transport(self.adb, str(path), guarded=True)
        self.guard = None

    def connect(self):
        try:
            super().connect()
            self.guard = GuardClient(self.transport.control)
            return self
        except BaseException:
            self.close()
            raise

    def arm(self, package="dji.go.v5"):
        if self.error or not self.controller.sticks:
            raise RuntimeError(self.error or "Calibrate before arming")
        status = self.guard.arm(self.controller.sticks, package)
        if (status["width"], status["height"]) != self.controller.size:
            self.guard.release(True)
            raise RuntimeError("Guard/video geometry mismatch")
        return status

    def set_sticks(self, left_xy, right_xy, ttl_ms=500):
        if self.error:
            raise RuntimeError(self.error)
        return self.guard.command(left_xy, right_xy, ttl_ms)

    def release_all(self):
        if self.guard:
            self.guard.release()

    def set_manual_sticks(self, left_xy, right_xy, ttl_ms=500):
        if self.error:
            raise RuntimeError(self.error)
        return self.guard.manual_command(left_xy, right_xy, ttl_ms)

    def close(self):
        if self.guard:
            self.guard.close()
        super().close()
