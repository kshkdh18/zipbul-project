"""Deterministic command visualization in virtual units; never aircraft telemetry."""

import math
from collections import deque


def semantic_axes(event):
    values = (*(event.left or (0, 0)), *(event.right or (0, 0)))
    return {axis: value * sign for value, (axis, sign) in zip(values, event.axes, strict=True)}


def instruction(axes):
    labels = []
    for axis, negative, positive in (
        ("forward", "뒤로 이동", "앞으로 이동"),
        ("lateral", "왼쪽으로 이동", "오른쪽으로 이동"),
        ("vertical", "아래로 이동", "위로 이동"),
        ("yaw", "왼쪽으로 회전", "오른쪽으로 회전"),
    ):
        value = axes.get(axis, 0)
        if abs(value) > 1e-6:
            labels.append(positive if value > 0 else negative)
    return " · ".join(labels) or "제자리 유지"


class Simulation:
    def __init__(self):
        self.x = self.y = self.z = self.yaw = 0.0
        self.axes = dict(yaw=0.0, vertical=0.0, lateral=0.0, forward=0.0)
        self.trail = deque([(0.0, 0.0, 0.0)], maxlen=1500)
        self.last_time = None
        self.deadline = 0
        self.last_id = 0
        self.label = "이동 지시 대기"
        self.reason = "목표를 입력하고 카메라 영역을 지정하세요."
        self.state = "대기"
        self.source = ""
        self.show_arrows = False

    def reset(self):
        self.x = self.y = self.z = self.yaw = 0.0
        self.trail.clear()
        self.trail.append((0.0, 0.0, 0.0))

    def advance(self, now):
        if self.last_time is None:
            self.last_time = now
        end = min(now, self.deadline)
        dt = max(0.0, end - self.last_time)
        # Fixed maximum integration step keeps rotation+translation independent of render cadence.
        while dt > 1e-9:
            step = min(dt, 1 / 120)
            heading = math.radians(self.yaw + self.axes["yaw"] * 45 * step / 2)
            forward, lateral = self.axes["forward"], self.axes["lateral"]
            self.x += (math.sin(heading) * forward + math.cos(heading) * lateral) * step
            self.z += (-math.cos(heading) * forward + math.sin(heading) * lateral) * step
            self.y += self.axes["vertical"] * step
            self.yaw = (self.yaw + self.axes["yaw"] * 45 * step) % 360
            dt -= step
        self.last_time = max(self.last_time, now)
        if math.dist(self.trail[-1], (self.x, self.y, self.z)) >= 0.04:
            self.trail.append((self.x, self.y, self.z))
        if self.deadline and now >= self.deadline:
            self.deadline = 0
            self.state = "다음 판단 중"

    def consume(self, event):
        self.advance(event.at)
        if event.kind == "command":
            if event.command_id <= self.last_id:
                return
            self.last_id = event.command_id
            self.axes = semantic_axes(event)
            self.label = instruction(self.axes)
            self.reason = event.reason
            self.source = event.source
            self.deadline = event.deadline
            self.show_arrows = any(abs(v) > 1e-6 for v in self.axes.values())
            self.state = "입력 중" if event.deadline > event.at else "다음 판단 중"
        else:
            self.deadline = 0
            self.state = "다음 판단 중" if event.kind == "expire" else "중단 / 완료"
            if event.kind == "stop":
                self.show_arrows = False
                self.label = "이동 지시 중단"
                self.reason = event.reason
