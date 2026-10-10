"""Held-button control: renew only while the GUI reports a current physical press."""

import math
import threading
import time
from dataclasses import asdict

from .execution import execute_command
from .flight_profile import DEFAULT_AXES
from .i18n import error_text
from .i18n import message as m


def manual_targets(axis, sign, strength):
    if type(axis) is not int or not 0 <= axis < 4 or type(sign) is not int or sign not in (-1, 1):
        raise ValueError("Invalid manual axis")
    if type(strength) not in (int, float) or not math.isfinite(strength) or not 0.05 <= strength <= 1:
        raise ValueError("Manual drag must be 5–100% of the calibrated radius")
    xy = [0.0, 0.0]
    xy[axis % 2] = strength * sign
    return (tuple(xy), None) if axis < 2 else (None, tuple(xy))


class ManualHold:
    def __init__(
        self,
        bridge,
        axis,
        sign,
        max_seconds=3.0,
        clock=time.monotonic,
        strength=1.0,
        stream=None,
        axes=DEFAULT_AXES,
    ):
        self.targets = manual_targets(axis, sign, strength)
        if not 1 <= max_seconds <= 10:
            raise ValueError("Manual hold limit must be 1–10 seconds")
        self.bridge = bridge
        self.axis, self.sign = axis, sign
        self.max_seconds = max_seconds
        self.strength = strength
        self.clock = clock
        self.stream = stream
        self.axes = axes
        self.lock = threading.RLock()
        self.cancelled = threading.Event()
        self.pressed_at = clock()
        self.epoch = None
        self.started = None
        self.last_command = None
        self.armed = False
        self.release_error = ""
        self.reason = m("버튼 해제")
        self.target_points = [None, None]
        self.distance_px = 0.0
        self.command_count = 0
        self.update_count = 0
        self.last_ack = {}
        self.events = []

    def _record(self, kind, ack=None, **fields):
        if isinstance(ack, dict):
            self.last_ack = dict(ack)
        self.events.append({"kind": kind, "host_monotonic": self.clock(), "ack": ack, **fields})

    def pressed(self):
        self.pressed_at = self.clock()

    def stop(self, reason=None):
        # Invalidate before taking the lock so a pending arm cannot send a late command.
        self.reason = m("버튼 해제") if reason is None else reason
        self.cancelled.set()
        with self.lock:
            try:
                self._release()
            except Exception as exc:
                self.release_error = error_text(exc)

    def _release(self):
        if self.armed:
            try:
                ack = self.bridge.guard.release(True)
                self._record("release", ack)
            finally:
                self.armed = False
                if self.stream:
                    self.stream.release(self.reason)

    def _valid(self):
        now = self.clock()
        if self.cancelled.is_set():
            return False
        if now - self.pressed_at > 0.25:
            self.reason = m("버튼 상태 갱신 중단")
            return False
        if self.started is not None and now - self.started >= self.max_seconds:
            self.reason = m("설정한 최대 유지 시간 도달")
            return False
        frame = self.bridge.latest_frame()
        if self.bridge.error or frame is None or now - frame.decoded_at > 0.5:
            self.reason = m("영상 지연 또는 연결 종료")
            return False
        if self.epoch is not None and frame.epoch != self.epoch:
            self.reason = m("화면 세션 변경")
            return False
        return True

    def begin(self):
        with self.lock:
            if not self._valid():
                return False
            self.epoch = self.bridge.latest_frame().epoch
            self.bridge.arm("dji.go.v5")
            self.armed = True
            if not self._valid():
                self._release()
                return False
            self.started = self.clock()
            self.target_points = [
                None if xy is None else stick.target(xy)
                for stick, xy in zip(self.bridge.controller.sticks, self.targets, strict=True)
            ]
            self.distance_px = self.bridge.controller.sticks[self.axis // 2].radius * self.strength
            self._record(
                "start",
                axis=self.axis,
                sign=self.sign,
                strength=self.strength,
                targets=self.targets,
                target_points=self.target_points,
                distance_video_px=self.distance_px,
                max_seconds=self.max_seconds,
            )
            return True

    def tick(self):
        with self.lock:
            if not self.armed or not self._valid():
                self.cancelled.set()
                self._release()
                return False
            self.bridge.guard.heartbeat()
            if not self._valid():
                self._release()
                return False
            # A short device lease stays short even when the operator holds for several seconds.
            # Each renewal is backed by a fresh GUI press, not an old AI response.
            if self.last_command is None or self.clock() - self.last_command >= 0.2:
                ack, event = execute_command(
                    self.bridge,
                    *self.targets,
                    500,
                    stream=self.stream,
                    source="manual",
                    reason=m("수동 조작"),
                    axes=self.axes,
                )
                self.command_count += 1
                self._record(
                    "command",
                    ack,
                    targets=self.targets,
                    ttl_ms=500,
                    execution_event=asdict(event) if event else None,
                )
                self.last_command = self.clock()
            else:
                # Drive the server's 100ms interpolation all the way to the target.
                ack = self.bridge.guard.update()
                self.update_count += 1
                self._record("update", ack)
            return True

    def run(self):
        try:
            if self.begin():
                while self.tick():
                    if self.cancelled.wait(0.05):
                        break
        except Exception as exc:
            self.reason = m("축 확인 오류: ") + error_text(exc)
        finally:
            with self.lock:
                self.cancelled.set()
                try:
                    self._release()
                except Exception as exc:
                    self.release_error = error_text(exc)
        if self.release_error:
            self._record("finished", reason=self.reason, release_error=self.release_error)
            return self.reason + m(" · 해제 확인 실패: ") + self.release_error
        self._record("finished", reason=self.reason)
        return self.reason + m(" · 입력 종료")
