"""Bounded visual mission loop. The 20Hz executor never waits for model inference."""

from __future__ import annotations

import json
import threading
import time
import uuid
from collections import deque
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
from PIL import Image

from .astra import POLICY_VERSION, parse_decision
from .camera import camera_rect, crop_frame
from .execution import execute_command
from .flight_profile import DEFAULT_AXES
from .i18n import error_text
from .i18n import message as m
from .stick_input import directed_targets, drag_fraction
from .validation import output_directory

API_TIMEOUT_S = 15


class Journal:
    def __init__(self, path=None):
        self.path = Path(path) if path else output_directory("mission")
        self.path.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()
        self.history = deque(maxlen=20)

    def event(self, kind, **data):
        record = {"kind": kind, "host_monotonic": time.monotonic(), **data}
        with self.lock:
            with (self.path / "events.jsonl").open("a") as f:
                f.write(json.dumps(record, ensure_ascii=False, allow_nan=False) + "\n")
            self.history.append(record)

    def observation(self, observation):
        Image.fromarray(observation.frame.rgb).save(self.path / f"{observation.id}.jpg", quality=85)
        self.event("observation", **observation.metadata)


@dataclass(frozen=True)
class Observation:
    id: str
    frame: object
    generation: int
    metadata: dict


class Executor:
    """One command owner. stop(), submit(), and timer transitions share a lock."""

    def __init__(
        self,
        bridge,
        live,
        profile,
        journal,
        clock=time.monotonic,
        camera_roi=None,
        drag_strength=1.0,
        stream=None,
    ):
        self.bridge, self.live, self.profile, self.journal = bridge, live, profile, journal
        self.clock = clock
        self.stream = stream
        self.drag_strength = drag_fraction(drag_strength)
        self.lock = threading.RLock()
        self.generation = 0
        self.running = False
        self.reason = "idle"
        self.deadline = 0.0
        self.started = 0.0
        self.last_heartbeat = 0.0
        self.ui_heartbeat = clock()
        self.require_ui = False
        self.command = None
        self.epoch = None
        self.last_observation = None
        self.stop_event = threading.Event()
        self.thread = None
        self.command_seconds = 0.0
        self.command_started = 0.0
        self.expirations = 0
        self.submissions = 0
        self.continuous_updates = 0
        self.direction_started = 0.0
        self.model = "gpt-6-astra"
        self.policy = POLICY_VERSION
        self.last_tick_at = 0.0
        self.max_tick_gap_ms = 0.0
        self.layout = None
        self.camera_roi = camera_roi if camera_roi is not None else (profile.camera if profile else None)

    def start(self, require_ui=False):
        with self.lock:
            frame = self.bridge.latest_frame()
            if frame is None or self.clock() - frame.decoded_at > 0.5:
                raise RuntimeError(m("최신 화면이 필요합니다."))
            self.epoch = frame.epoch
            if self.profile is not None:
                self.profile.validate()
            camera_rect(self.camera_roi, frame.width, frame.height)
            if self.live:
                if not hasattr(self.bridge, "guard") or self.bridge.guard is None:
                    raise RuntimeError(m("Android 입력 서버 연결이 필요합니다."))
                if not self.bridge.controller.sticks:
                    raise ValueError(m("L/R 조이스틱 위치 보정이 필요합니다."))
                for stick in self.bridge.controller.sticks:
                    stick.validate(frame.width, frame.height)
                self.bridge.arm("dji.go.v5")
            self.running = True
            self.reason = "running"
            self.started = self.clock()
            self.ui_heartbeat = self.started
            self.require_ui = require_ui
            self.journal.event(
                "start",
                live=self.live,
                model=self.model,
                decision_policy=self.policy,
                operator_drag_fraction=self.drag_strength,
                mission_limit_s=None,
                server_sha256=getattr(self.bridge.transport, "server_sha256", None),
                axis_mapping_source="saved_settings" if self.profile else "default",
                axis_mapping_verified=bool(getattr(self.profile, "verified", False)),
            )
            self.thread = threading.Thread(target=self._loop, name="flight-executor", daemon=True)
            self.thread.start()

    def _release(self, why, disarm=False):
        if self.command_started:
            self.command_seconds += max(0, min(self.clock(), self.deadline) - self.command_started)
        self.command_started = 0
        self.direction_started = 0
        self.deadline = 0
        self.command = None
        self.generation += 1
        self.reason = why
        if self.live:
            try:
                status = self.bridge.guard.release(disarm)
                self.journal.event("release_ack", status=status)
            except Exception as exc:
                self.journal.event("release_failed", error=error_text(exc), physical_state="unknown")
                self.running = False
        if self.stream:
            self.stream.release(why, clear=why != "command_expired" or not self.running)
        self.journal.event("release", reason=why, generation=self.generation)

    def stop(self, reason="paused"):
        with self.lock:
            if not self.running:
                return
            self.running = False
            try:
                if self.live and hasattr(self.bridge.guard, "diagnostics"):
                    self.journal.event(
                        "guard_diagnostics",
                        reason=reason,
                        last_heartbeat_age_ms=max(0, (self.clock() - self.last_heartbeat) * 1000),
                        max_tick_gap_ms=self.max_tick_gap_ms,
                        **self.bridge.guard.diagnostics(),
                    )
            finally:
                # Diagnostic collection/writes must never prevent the physical release.
                try:
                    self._release(reason, disarm=True)
                finally:
                    self.stop_event.set()

    def neutral(self, reason):
        with self.lock:
            if self.running:
                self._release(reason)

    def tick(self):
        with self.lock:
            if not self.running:
                return
            now = self.clock()
            if self.last_tick_at:
                self.max_tick_gap_ms = max(self.max_tick_gap_ms, (now - self.last_tick_at) * 1000)
            self.last_tick_at = now
            frame = self.bridge.latest_frame()
            if self.bridge.error or frame is None or now - frame.decoded_at > 0.5:
                self.stop("video_stale_or_disconnected")
                return
            if frame.epoch != self.epoch:
                self.stop("geometry_changed")
                return
            if self.live and not self.bridge.guard.snapshot().get("armed"):
                guard = self.bridge.guard
                diagnostics = guard.diagnostics() if hasattr(guard, "diagnostics") else {}
                cause = diagnostics.get("first_disarm") or guard.snapshot()
                self.stop("android_disarmed: " + cause.get("reason", "unknown"))
                return
            if self.deadline and now >= self.deadline:
                self.expirations += 1
                self._release("command_expired")
            if self.live:
                if now - self.last_heartbeat >= 0.1:
                    self.bridge.guard.heartbeat()
                    self.last_heartbeat = self.clock()
                if self.deadline:
                    # Device timer can win before the host timer by a few milliseconds.
                    status = self.bridge.guard.snapshot()
                    if status.get("expires_at_ms") == 0:
                        self.expirations += 1
                        self._release("command_expired")
                    else:
                        self.bridge.guard.update()

    def _loop(self):
        while not self.stop_event.wait(0.05):
            try:
                self.tick()
            except Exception as exc:
                self.stop("executor_error: " + error_text(exc))
            if not self.running:
                return

    def observe(self, goal, verification=False):
        with self.lock:
            if not self.running:
                raise RuntimeError(self.reason)
            frame = self.bridge.latest_frame()
            if frame is None or self.clock() - frame.decoded_at > 0.5 or frame.epoch != self.epoch:
                raise RuntimeError("No fresh observation")
            oid = "obs-" + uuid.uuid4().hex[:16]
            self.last_observation = oid
            metadata = {
                "observation_id": oid,
                "goal": goal,
                "mode": "LIVE" if self.live else "OBSERVATION_ONLY",
                "decision_policy": self.policy,
                "operator_drag_fraction": self.drag_strength,
                "stick_command_semantics": "nonzero direction scaled to operator_drag_fraction",
                "completion_verification": verification,
                "frame_sequence": frame.sequence,
                "frame_epoch": frame.epoch,
                "frame_received_at": frame.received_at,
                "frame_decoded_at": frame.decoded_at,
                "observation_at": self.clock(),
                "current_command": self.command,
                "continuous_hold_ms": max(0, (self.clock() - self.direction_started) * 1000)
                if self.command
                else 0,
                "command_remaining_ms": max(0, (self.deadline - self.clock()) * 1000),
                "axis_mapping_screen_lx_ly_rx_ry": self.profile.axes
                if self.profile
                else [list(a) for a in DEFAULT_AXES],
                "axis_mapping_source": "saved_settings" if self.profile else "default",
                "axis_mapping_verified": bool(getattr(self.profile, "verified", False)),
                "camera_roi": list(self.camera_roi),
                "camera_only": True,
                "camera_roi_source": "cropped",
                "recent_results": list(self.journal.history)[-12:],
            }
            # Do not recursively embed old observation payloads in each new request.
            metadata["recent_results"] = [
                x for x in metadata["recent_results"] if x["kind"] in ("executed", "proposed_only", "release")
            ]
            return Observation(oid, crop_frame(frame, self.camera_roi), self.generation, metadata)

    def valid(self, observation):
        return (
            self.running
            and observation.generation == self.generation
            and observation.frame.epoch == self.epoch
            and observation.id == self.last_observation
        )

    def submit(self, observation, arguments, *, source="ai", context=None):
        with self.lock:
            self.tick()  # deadlines and stale video win over model delivery
            if not self.valid(observation) or arguments["observation_id"] != observation.id:
                raise ValueError("Stale observation; command discarded")
            parse_decision("command_sticks", arguments)
            left, right = directed_targets(arguments["left_xy"], arguments["right_xy"], self.drag_strength)
            command = {**arguments, "left_xy": left, "right_xy": right}
            sent_at = self.clock()
            event = None
            status = None
            if self.live:
                status, event = execute_command(
                    self.bridge,
                    left,
                    right,
                    command["valid_for_ms"],
                    stream=self.stream,
                    reason=command["reason"],
                    source=source,
                    axes=self.profile.axes if self.profile else DEFAULT_AXES,
                )
                if event:
                    self.journal.event("execution_event", event=asdict(event), context=context)
                self.journal.event("command_ack", status=status, context=context)
                # Use a conservative host deadline; device clock is authoritative.
                duration = max(0, status["expires_at_ms"] - status["device_time_ms"]) / 1000
            else:
                duration = arguments["valid_for_ms"] / 1000
            self.continuous_updates += bool(self.deadline)
            self.submissions += 1
            if self.command_started:
                self.command_seconds += max(0, min(self.clock(), self.deadline) - self.command_started)
            if not self.command or (self.command["left_xy"], self.command["right_xy"]) != (left, right):
                self.direction_started = self.clock()
            self.command = command
            self.command_started = self.clock()
            self.deadline = min(sent_at + command["valid_for_ms"] / 1000, self.command_started + duration)
            if event:
                self.deadline = min(self.deadline, event.deadline)
            self.last_observation = None  # an observation can authorize at most one command
            self.reason = "running"
            self.journal.event(
                "executed" if self.live else "proposed_only",
                command=command,
                requested_command=arguments,
                operator_drag_fraction=self.drag_strength,
                context=context,
            )
            return event


class Mission:
    def __init__(
        self,
        bridge,
        provider,
        goal,
        live=False,
        profile=None,
        output=None,
        camera_roi=None,
        drag_strength=1.0,
        stream=None,
    ):
        if not goal.strip():
            raise ValueError(m("목표를 입력하세요."))
        self.provider, self.goal = provider, goal.strip()
        self.journal = Journal(output)
        self.executor = Executor(
            bridge,
            live,
            profile,
            self.journal,
            camera_roi=camera_roi,
            drag_strength=drag_strength,
            stream=stream,
        )
        self.state = "idle"
        self.message = ""
        self.decisions = []
        self.discarded = 0
        self.thread = None
        self.previous = None
        self.verifications = 0
        self.last_verify_at = 0
        self.last_verify_sequence = 0
        self.api_timeouts = 0
        self.request_thread = None

    @property
    def busy(self):
        return bool(
            (self.thread and self.thread.is_alive())
            or (self.request_thread and self.request_thread.is_alive())
        )

    def start(self, require_ui=False):
        self.executor.start(require_ui)
        self.state = "running"
        self.thread = threading.Thread(target=self._run, name="astra-mission", daemon=True)
        self.thread.start()

    def stop(self, reason="user_paused"):
        if self.state == "completed":
            return
        self.executor.stop(reason)
        self.state = "paused"
        self.message = reason

    def set_camera_roi(self, roi):
        with self.executor.lock:
            if roi is not None:
                frame = self.executor.bridge.latest_frame()
                roi = list(camera_rect(roi, frame.width, frame.height))
            self.executor.neutral("camera_region_changed")
            self.executor.camera_roi = roi
            self.previous = None
            self.state = "running"
            self.verifications = 0

    def _call(self, observation):
        # Hard wall-clock bound in addition to HTTP per-operation timeout.
        result, done = [], threading.Event()
        previous = self.previous

        def request():
            try:
                result.append(self.provider.decide(observation, previous))
            except Exception as exc:
                result.append(exc)
            finally:
                done.set()

        worker = threading.Thread(target=request, name="astra-request", daemon=True)
        self.request_thread = worker
        worker.start()
        started = time.monotonic()
        while not done.wait(0.05):
            if not self.executor.running:
                # Keep the mission busy until this sole outstanding request is disposed of.
                self.provider.close()
                return None
            if time.monotonic() - started >= API_TIMEOUT_S:
                self.api_timeouts += 1
                self.executor.stop("api_timeout")
                self.provider.close()
                raise TimeoutError("AI response exceeded 15 seconds")
        if isinstance(result[0], Exception):
            raise result[0]
        return result[0]

    def _run(self):
        try:
            while self.executor.running:
                if self.executor.camera_roi is None:
                    time.sleep(0.05)
                    continue
                verification = self.state == "verifying"
                if verification:
                    frame = self.executor.bridge.latest_frame()
                    if (
                        time.monotonic() - self.last_verify_at < 0.5
                        or frame.sequence <= self.last_verify_sequence
                    ):
                        time.sleep(0.025)
                        continue
                with self.executor.lock:
                    if self.executor.camera_roi is None:
                        continue
                    observation = self.executor.observe(self.goal, verification)
                self.journal.observation(observation)
                decision = self._call(observation)
                if decision is None or not self.executor.running:
                    break
                self.decisions.append(decision)
                self.journal.event("decision", **asdict(decision), observation_id=observation.id)
                with self.executor.lock:
                    self.executor.tick()
                    if not self.executor.valid(observation):
                        self.discarded += 1
                        self.journal.event("discarded", observation_id=observation.id)
                        continue
                    args = parse_decision(decision.name, decision.arguments)
                    self.message = args.get("reason", args.get("evidence", decision.name))
                    if decision.name == "need_operator":
                        self.journal.event("operator_request", source="model", reason=args["reason"])
                        self.stop("need_operator: " + args["reason"])
                        break
                    if verification:
                        if decision.name == "finish":
                            self.verifications += 1
                            self.last_verify_at = time.monotonic()
                            self.last_verify_sequence = observation.frame.sequence
                            if self.verifications >= 2:
                                self.executor.stop("completed")
                                self.state = "completed"
                                break
                        else:
                            self.verifications = 0
                            self.state = (
                                "running"  # next fresh observation; do not execute during verification
                            )
                    elif decision.name == "finish":
                        self.executor.neutral("verifying_completion")
                        self.state = "verifying"
                        self.verifications = 0
                        self.last_verify_at = time.monotonic()
                        self.last_verify_sequence = observation.frame.sequence
                    elif decision.name == "observe":
                        self.executor.neutral("observing")
                    else:
                        self.executor.submit(observation, args)
                    self.previous = observation
                # Avoid repeatedly assessing the same frame after an immediate mock/provider response.
                try:
                    self.executor.bridge.wait_frame(observation.frame.sequence, timeout=0.5)
                except TimeoutError:
                    pass
            if self.state not in ("completed", "paused"):
                self.state = "paused"
                self.message = self.executor.reason
        except Exception as exc:
            self.stop("error: " + error_text(exc))
            self.journal.event("error", message=error_text(exc))
        finally:
            self.executor.stop(self.message or "finished")
            self.provider.close()
            self.report()

    def report(self):
        times = [d.latency * 1000 for d in self.decisions]
        elapsed = max(0, time.monotonic() - self.executor.started)
        result = {
            "goal": self.goal,
            "state": self.state,
            "reason": self.executor.reason,
            "message": self.message,
            "live": self.executor.live,
            "decision_policy": POLICY_VERSION,
            "operator_drag_fraction": self.executor.drag_strength,
            "decisions": len(self.decisions),
            "discarded_stale": self.discarded,
            "api_timeouts": self.api_timeouts,
            "command_expirations": self.executor.expirations,
            "commands": self.executor.submissions,
            "continuous_updates": self.executor.continuous_updates,
            "continuous_update_fraction": self.executor.continuous_updates
            / max(1, self.executor.submissions),
            "input_active_fraction": self.executor.command_seconds / max(0.001, elapsed),
            "api_latency_ms": {"p50": float(np.percentile(times, 50)), "p95": float(np.percentile(times, 95))}
            if times
            else {},
            "usage": [d.usage for d in self.decisions],
            "completion_verifications": self.verifications,
            "camera_latency": "not measured; screen freshness is not drone-camera freshness",
        }
        (self.journal.path / "report.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n"
        )
        return result
