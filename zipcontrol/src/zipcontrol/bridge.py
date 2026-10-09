from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass
from fractions import Fraction

import av
import numpy as np

from .adb import Adb, Transport
from .control import Controller, Stick
from .protocol import Session, read_packet


@dataclass(frozen=True)
class Frame:
    rgb: np.ndarray
    sequence: int
    received_at: float  # Mac monotonic clock; NOT the device's clock
    decoded_at: float
    pts_us: int
    epoch: int

    @property
    def width(self):
        return self.rgb.shape[1]

    @property
    def height(self):
        return self.rgb.shape[0]


class Bridge:
    def __init__(self, serial=None, server_path=None, max_size=1280, max_fps=30):
        self.adb = Adb(serial)
        self.transport = Transport(self.adb, server_path)
        self.max_size, self.max_fps = max_size, max_fps
        self.controller: Controller | None = None
        self._frame: Frame | None = None
        self._condition = threading.Condition()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.error: str | None = None
        self._times = deque(maxlen=180)
        self._closed = False

    def connect(self):
        if self._closed or self.controller:
            raise RuntimeError("Create a fresh Bridge for every connection")
        self.transport.start(self.max_size, self.max_fps)
        self.controller = Controller(self.transport.control.sendall, self._fail)
        self._thread = threading.Thread(target=self._receive, name="scrcpy-video", daemon=True)
        self._thread.start()
        try:
            self.wait_frame(timeout=10)
        except BaseException:
            self.close()
            raise
        return self

    def _fail(self, error):
        self.error = str(error)
        with self._condition:
            self._condition.notify_all()

    def _receive(self):
        codec = None
        sequence = 0
        try:
            while not self._stop.is_set():
                packet = read_packet(self.transport.video)
                received_at = time.monotonic()
                if isinstance(packet, Session):
                    self.controller.geometry(packet.width, packet.height)
                    with self._condition:
                        self._frame = None
                    codec = av.CodecContext.create("h264", "r")
                    codec.thread_count = 1
                    codec.options = {"flags": "low_delay"}
                    continue
                if codec is None:
                    raise ValueError("Missing scrcpy session header")
                if packet.config:
                    codec.extradata = packet.data
                    continue
                encoded = av.Packet(packet.data)
                encoded.pts = packet.pts
                encoded.time_base = Fraction(1, 1_000_000)
                for decoded in codec.decode(encoded):
                    # FFmpeg may pad RGB scanlines (e.g. 810px wide), leaving a strided view.
                    # Publish tightly packed frames for Python buffer consumers such as QImage.
                    rgb = np.ascontiguousarray(decoded.to_ndarray(format="rgb24"))
                    rgb.flags.writeable = False
                    sequence += 1
                    now = time.monotonic()
                    frame = Frame(rgb, sequence, received_at, now, packet.pts, self.controller.epoch)
                    with self._condition:
                        self._frame = frame
                        self._times.append(now)
                        self._condition.notify_all()
        except Exception as exc:
            if not self._stop.is_set():
                self._fail(exc)
                try:
                    self.controller.release_all("Video connection lost")
                except Exception:
                    pass
                self.controller.sticks = None

    def latest_frame(self) -> Frame | None:
        with self._condition:
            return self._frame

    def wait_frame(self, after: int = 0, timeout: float = 5) -> Frame:
        deadline = time.monotonic() + timeout
        with self._condition:
            while True:
                if self.error:
                    raise RuntimeError(self.error)
                if self._frame and self._frame.sequence > after:
                    return self._frame
                remaining = deadline - time.monotonic()
                if remaining <= 0 or self._stop.is_set():
                    raise TimeoutError("No new video frame")
                self._condition.wait(remaining)

    @property
    def fps(self):
        with self._condition:
            times = list(self._times)
        return (len(times) - 1) / (times[-1] - times[0]) if len(times) > 1 else 0.0

    def calibrate(self, left: Stick, right: Stick, frame: Frame):
        if self.error or not self.controller:
            raise RuntimeError(self.error or "Not connected")
        self.controller.calibrate(left, right, frame.epoch)

    def set_sticks(self, left_xy, right_xy, ttl_ms: int = 500):
        if self.error or not self.controller:
            raise RuntimeError(self.error or "Not connected")
        self.controller.set_sticks(left_xy, right_xy, ttl_ms)

    def release_all(self):
        if self.controller:
            self.controller.release_all()

    def close(self):
        if self._closed:
            return
        self._closed = True
        try:
            if self.controller:
                self.controller.close()
        except Exception:
            pass
        self._stop.set()
        self.transport.close()
        if self._thread:
            self._thread.join(timeout=2)
        with self._condition:
            self._condition.notify_all()

    def __enter__(self):
        return self.connect()

    def __exit__(self, *_):
        self.close()
