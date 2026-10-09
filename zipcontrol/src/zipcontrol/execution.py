"""A single acknowledged command path for AI, manual control and visualization."""

import threading
import time
from collections import deque
from dataclasses import dataclass

from .flight_profile import DEFAULT_AXES


@dataclass(frozen=True)
class ExecutionEvent:
    kind: str
    command_id: int
    at: float
    deadline: float = 0
    left: tuple | None = None
    right: tuple | None = None
    axes: tuple = DEFAULT_AXES
    source: str = "ai"
    reason: str = ""
    valid_for_ms: int = 0
    android_command_id: int | None = None


class CommandStream:
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.lock = threading.Lock()
        self.events = deque()
        self.sequence = 0

    def accepted(self, left, right, duration, ack, source, reason, axes, sent_at):
        if ack.get("ok") is False or ack.get("injection_ok") is False:
            raise RuntimeError("Android rejected command")
        with self.lock:
            self.sequence += 1
            now = self.clock()
            remaining = max(0, ack.get("expires_at_ms", duration) - ack.get("device_time_ms", 0)) / 1000
            # A delayed ACK cannot extend a lease beyond the original host send time.
            deadline = min(sent_at + duration / 1000, now + remaining)
            event = ExecutionEvent(
                "command",
                self.sequence,
                now,
                deadline,
                tuple(left) if left is not None else None,
                tuple(right) if right is not None else None,
                tuple(tuple(a) for a in axes),
                source,
                reason,
                duration,
                ack.get("command_id"),
            )
            self.events.append(event)
            return event

    def release(self, reason, clear=True):
        with self.lock:
            self.events.append(
                ExecutionEvent("stop" if clear else "expire", self.sequence, self.clock(), reason=reason)
            )

    def drain(self):
        with self.lock:
            events = list(self.events)
            self.events.clear()
            return events


def execute_command(bridge, left, right, duration, *, stream=None, source="ai", reason="", axes=DEFAULT_AXES):
    sent_at = stream.clock() if stream else time.monotonic()
    if source == "manual":
        ack = bridge.set_manual_sticks(left, right, ttl_ms=duration)
    else:
        ack = bridge.guard.command(left, right, duration)
    if ack.get("ok") is False or ack.get("injection_ok") is False:
        raise RuntimeError("Android rejected command")
    event = stream.accepted(left, right, duration, ack, source, reason, axes, sent_at) if stream else None
    return ack, event
