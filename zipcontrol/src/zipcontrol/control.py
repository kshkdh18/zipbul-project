from __future__ import annotations

import math
import threading
import time
from dataclasses import dataclass
from typing import Callable

from .protocol import DOWN, MOVE, UP, touch


@dataclass(frozen=True)
class Stick:
    x: float
    y: float
    radius: float

    def validate(self, width: int, height: int):
        values = (self.x, self.y, self.radius)
        if not all(
            isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in values
        ):
            raise ValueError("Invalid joystick calibration")
        if self.radius < 2:
            raise ValueError("Invalid joystick radius")
        if not (
            0 <= self.x - self.radius
            and self.x + self.radius < width
            and 0 <= self.y - self.radius
            and self.y + self.radius < height
        ):
            raise ValueError("Joystick circle must fit inside the image")

    def target(self, xy: tuple[float, float]) -> tuple[float, float]:
        if len(xy) != 2 or not all(math.isfinite(v) for v in xy):
            raise ValueError("Stick coordinates must be two finite numbers")
        x, y = (max(-1.0, min(1.0, v)) for v in xy)
        scale = max(1.0, math.hypot(x, y))
        return self.x + x / scale * self.radius, self.y + y / scale * self.radius


class Controller:
    def __init__(self, send: Callable[[bytes], None], on_error: Callable[[str], None] = lambda _: None):
        self._send = send
        self._on_error = on_error
        self._lock = threading.RLock()
        self.size = (0, 0)
        self.epoch = 0
        self.sticks: tuple[Stick, Stick] | None = None
        self.active: dict[int, tuple[float, float]] = {}
        self.deadline = 0.0
        self.last_reason = "Not calibrated"
        self._stop = threading.Event()
        self._watchdog = threading.Thread(target=self._watch, name="touch-expiry", daemon=True)
        self._watchdog.start()

    def _write(self, data: bytes):
        if not data:
            return
        try:
            self._send(data)
        except Exception as exc:
            self.active.clear()
            self.deadline = 0
            self.sticks = None
            self.last_reason = "Connection lost; physical touch state unknown"
            self._on_error(str(exc))
            raise

    def geometry(self, width: int, height: int):
        with self._lock:
            old_width, old_height = self.size
            self.size = width, height
            # Use current video dimensions even when the old session's coordinates are obsolete.
            data = bytearray()
            for pointer, (x, y) in self.active.items():
                px = min(width - 1, x / max(1, old_width) * width)
                py = min(height - 1, y / max(1, old_height) * height)
                data.extend(touch(UP, pointer, px, py, width, height))
            try:
                self._write(bytes(data))
            finally:
                self.active.clear()
                self.sticks = None
                self.deadline = 0
                self.epoch += 1
                self.last_reason = "Geometry changed; recalibrate"

    def calibrate(self, left: Stick, right: Stick, epoch: int):
        with self._lock:
            if epoch != self.epoch:
                raise ValueError("Stale frame; calibrate again")
            width, height = self.size
            for s in (left, right):
                s.validate(width, height)
            self.release_all("Recalibrated")
            self.sticks = left, right
            self.last_reason = "Ready"

    def set_sticks(self, left_xy, right_xy, ttl_ms: int = 500):
        """None releases only that side. Positive Y points down the phone screen."""
        if not isinstance(ttl_ms, int) or not 50 <= ttl_ms <= 2000:
            raise ValueError("ttl_ms must be an integer between 50 and 2000")
        with self._lock:
            if not self.sticks or self._stop.is_set():
                raise RuntimeError("Connect and calibrate the current frame before input")
            # Validate both targets before producing any side effects.
            targets = [
                None if xy is None else stick.target(xy)
                for xy, stick in zip((left_xy, right_xy), self.sticks, strict=True)
            ]
            next_active = dict(self.active)
            data = bytearray()
            for pointer, (target, stick) in enumerate(zip(targets, self.sticks, strict=True), start=1):
                if target is None:
                    if pointer in next_active:
                        data.extend(touch(MOVE, pointer, stick.x, stick.y, *self.size))
                        data.extend(touch(UP, pointer, stick.x, stick.y, *self.size))
                        del next_active[pointer]
                else:
                    if pointer not in next_active:
                        data.extend(touch(DOWN, pointer, stick.x, stick.y, *self.size))
                    data.extend(touch(MOVE, pointer, *target, *self.size))
                    next_active[pointer] = target
            self._write(bytes(data))
            self.active = next_active
            self.deadline = time.monotonic() + ttl_ms / 1000 if next_active else 0
            self.last_reason = "Holding" if next_active else "Released"

    def release_all(self, reason: str = "Released"):
        with self._lock:
            data = bytearray()
            for pointer, point in self.active.items():
                if self.sticks:
                    s = self.sticks[pointer - 1]
                    point = (s.x, s.y)
                    data.extend(touch(MOVE, pointer, *point, *self.size))
                data.extend(touch(UP, pointer, *point, *self.size))
            try:
                self._write(bytes(data))
            finally:
                self.active.clear()
                self.deadline = 0
                self.last_reason = reason

    def _watch(self):
        while not self._stop.wait(0.01):
            with self._lock:
                if self.deadline and time.monotonic() >= self.deadline:
                    try:
                        self.release_all("Command expired")
                    except Exception:
                        pass

    def close(self):
        self._stop.set()
        try:
            self.release_all("Closed")
        finally:
            if threading.current_thread() != self._watchdog:
                self._watchdog.join(timeout=1)
