"""Serialized Astra planning and Luna control atop the independent 20Hz executor."""

import time
import uuid
from collections import deque
from dataclasses import asdict

import numpy as np

from .actions import STATUS_ACTIONS, ActionAdapter, Subgoal
from .camera import camera_rect
from .flight_profile import DEFAULT_AXES
from .i18n import LANGUAGES, error_text
from .i18n import message as m
from .mission import Mission
from .planning import parse_plan

POLICY_VERSION = "astra-luna-handheld-1"
MIN_REQUEST_INTERVAL_S = 0.2
MAX_LUNA_OBSERVATION_AGE_S = 2.0
VERIFY_INTERVAL_S = 0.5
STATE_LABELS = {
    "idle": m("대기"),
    "planning": m("계획 중"),
    "replanning": m("재계획 중"),
    "running": m("조작 중"),
    "verifying": m("완료 확인"),
    "paused": m("중단"),
    "completed": m("완료"),
    "selecting_camera": m("영역 선택 중"),
}


class GuidanceMission(Mission):
    def __init__(self, bridge, decider, planner, goal, *, mode="hierarchical", language="ko", **kwargs):
        if mode not in ("hierarchical", "direct"):
            raise ValueError("Unknown guidance mode")
        if language not in LANGUAGES:
            raise ValueError("Unsupported language")
        self.language = language
        super().__init__(bridge, decider, goal, **kwargs)
        self.decider, self.planner = decider, planner
        self.mode = mode
        self.session_id = uuid.uuid4().hex
        self.plan_version = 0
        self.subgoal = Subgoal.direct(self.goal, self.language) if mode == "direct" else None
        self.completed_subgoals = deque(maxlen=40)
        self.trigger = "mission_start"
        self.last_sample_sequence = -1
        self.last_request_at = 0.0
        self.next_sample_at = 0.0
        self.last_action = ""
        self.records = []
        self.requests = []
        self.executor.model = "gpt-6-luna"
        self.executor.policy = POLICY_VERSION

    @property
    def state_label(self):
        return STATE_LABELS.get(self.state, self.state)

    def start(self, require_ui=False):
        if self.state != "idle":
            raise RuntimeError(m("새 임무를 시작하세요."))
        # Mission.start sets running before launching the thread; _run selects its initial phase.
        super().start(require_ui)

    def set_camera_roi(self, roi):
        with self.executor.lock:
            if roi is not None:
                frame = self.executor.bridge.latest_frame()
                if frame is None:
                    raise ValueError(m("최신 화면이 필요합니다."))
                roi = list(camera_rect(roi, frame.width, frame.height))
            self.executor.neutral("camera_region_changed")
            self.executor.camera_roi = roi
            self.plan_version += 1
            self.previous = None
            self.completed_subgoals.clear()
            self.verifications = 0
            self.next_sample_at = 0
            self.subgoal = Subgoal.direct(self.goal, self.language) if self.mode == "direct" else None
            self.trigger = "camera_region_changed"
            self.state = ("running" if self.mode == "direct" else "replanning") if roi else "selecting_camera"
            self.message = m("새 카메라 영역으로 판단합니다.") if roi else m("카메라 영역을 지정하세요.")

    def _schedule_plan(self, trigger):
        self.executor.neutral("planning: " + trigger)
        self.mode = "hierarchical"
        self.plan_version += 1
        self.trigger = trigger
        self.state = "replanning"
        self.message = m("Astra가 영상으로 다음 접근을 계획합니다.")
        self.verifications = 0
        self._after_current_frame()

    def _after_current_frame(self):
        frame = self.executor.bridge.latest_frame()
        if frame:
            self.last_sample_sequence = max(self.last_sample_sequence, frame.sequence)

    def _observation(self):
        observation = self.executor.observe(self.goal, self.state == "verifying")
        observation.metadata.update(
            session_id=self.session_id,
            plan_version=self.plan_version,
            controller_mode=self.mode,
            response_language="English" if self.language == "en" else "Korean",
            planning_trigger=self.trigger,
            current_subgoal=asdict(self.subgoal) if self.subgoal else None,
            completed_subgoals=list(self.completed_subgoals),
            subgoal_elapsed_ms=max(
                0, (time.monotonic() - getattr(self, "subgoal_started", time.monotonic())) * 1000
            ),
        )
        return observation

    def _discard_reason(self, observation, stage):
        if not self.executor.valid(observation):
            return "observation_invalidated"
        if observation.metadata["session_id"] != self.session_id:
            return "previous_session"
        if observation.metadata["plan_version"] != self.plan_version:
            return "previous_plan"
        if (
            stage == "luna"
            and time.monotonic() - observation.metadata["observation_at"] > MAX_LUNA_OBSERVATION_AGE_S
        ):
            return "luna_observation_older_than_2s"
        return None

    def _begin_verification(self):
        self.executor.neutral("verifying_completion")
        self.state = "verifying"
        self.verifications = 0
        self.next_sample_at = time.monotonic() + VERIFY_INTERVAL_S
        self._after_current_frame()

    def _verified(self):
        self.verifications += 1
        self.next_sample_at = time.monotonic() + VERIFY_INTERVAL_S
        self._after_current_frame()
        if self.verifications >= 2:
            self.executor.stop("completed")
            self.state = "completed"

    def _apply_plan(self, decision):
        args = parse_plan(decision.name, decision.arguments)
        self.message = args.get("reason", args.get("evidence", ""))
        if decision.name == "need_operator":
            self.stop("need_operator: " + args["reason"])
        elif decision.name == "finish":
            if self.state == "verifying":
                self._verified()
            else:
                self._begin_verification()
        else:
            new = Subgoal(**args)
            if self.trigger == "SUBGOAL_DONE" and self.subgoal and new.goal != self.subgoal.goal:
                self.completed_subgoals.append({**asdict(self.subgoal), "review": self.message})
            self.subgoal = new
            self.plan_version += 1
            self.subgoal_started = time.monotonic()
            self.state = "running"
            self.trigger = "plan_accepted"
            self.verifications = 0
            self.next_sample_at = 0
            self.journal.event("subgoal", plan_version=self.plan_version, subgoal=asdict(new))
            # No planner-frame command: Luna must look after plan acceptance.
            self._after_current_frame()

    def _apply_action(self, decision, observation):
        action = decision.action
        if action not in (*self.subgoal.allowed_actions, *STATUS_ACTIONS):
            raise ValueError("Luna selected an action outside the active subgoal")
        self.last_action = action
        if action == "REPLAN":
            self._schedule_plan("REPLAN")
        elif self.state == "verifying":
            if action == "SUBGOAL_DONE":
                self._verified()
            else:
                self.verifications = 0
                self.state = "running"
                self.next_sample_at = 0
                self.message = m("완료 조건을 다시 확인하고 조작을 이어갑니다.")
                self._after_current_frame()
        elif action == "SUBGOAL_DONE":
            self.message = m("영상에서 목표 달성 여부를 확인합니다.")
            if self.mode == "direct":
                self._begin_verification()
            else:
                self._schedule_plan("SUBGOAL_DONE")
        elif action == "WAIT":
            self.executor.neutral("observing")
            self.message = m("입력을 해제하고 새 영상을 관찰합니다.")
            self._after_current_frame()
        else:
            axes = self.executor.profile.axes if self.executor.profile else DEFAULT_AXES
            command = ActionAdapter.command(action, observation.id, self.subgoal, axes, self.language)
            self.message = command["reason"]
            self.executor.submit(
                observation,
                command,
                source="luna_decisions",
                context={
                    "session_id": self.session_id,
                    "plan_version": self.plan_version,
                    "observation_id": observation.id,
                    "action": action,
                    "confidence": decision.confidence,
                    "response_id": decision.response_id,
                },
            )

    def _run(self):
        try:
            with self.executor.lock:
                self.state = "running" if self.mode == "direct" else "planning"
                self.subgoal_started = time.monotonic()
                self.journal.event(
                    "guidance_start",
                    mode=self.mode,
                    language=self.language,
                    session_id=self.session_id,
                    planner_model="gpt-6-astra",
                    controller_model="gpt-6-luna",
                )
            while self.executor.running:
                with self.executor.lock:
                    self.executor.tick()
                    if not self.executor.running:
                        break
                    frame = self.executor.bridge.latest_frame()
                    ready = (
                        self.executor.camera_roi is not None
                        and frame.sequence > self.last_sample_sequence
                        and time.monotonic()
                        >= max(self.next_sample_at, self.last_request_at + MIN_REQUEST_INTERVAL_S)
                    )
                    if ready:
                        stage = (
                            "astra"
                            if self.state in ("planning", "replanning")
                            or (self.state == "verifying" and self.mode == "hierarchical")
                            else "luna"
                        )
                        observation = self._observation()
                        self.last_sample_sequence = observation.frame.sequence
                        self.last_request_at = time.monotonic()
                        self.provider = self.planner if stage == "astra" else self.decider
                if not ready:
                    try:
                        self.executor.bridge.wait_frame(self.last_sample_sequence, timeout=0.05)
                    except TimeoutError:
                        pass
                    self.executor.stop_event.wait(0.01)
                    continue
                self.journal.observation(observation)
                request = {
                    "stage": stage,
                    "observation_id": observation.id,
                    "plan_version": observation.metadata["plan_version"],
                    "status": "pending",
                }
                self.requests.append(request)
                request_started = time.monotonic()
                try:
                    decision = self._call(observation)
                    request["status"] = "completed" if decision is not None else "cancelled"
                except Exception as exc:
                    request["status"] = "error"
                    request["error"] = error_text(exc)
                    with self.executor.lock:
                        if self.executor.running and self._discard_reason(observation, "astra"):
                            self.discarded += 1
                            self.journal.event("discarded", **request, reason="invalidated_request_error")
                            continue
                    raise
                finally:
                    request["latency"] = time.monotonic() - request_started
                    self.journal.event("api_request", **request)
                if decision is None or not self.executor.running:
                    break
                record = {
                    "stage": stage,
                    "session_id": self.session_id,
                    "plan_version": observation.metadata["plan_version"],
                    "observation_id": observation.id,
                    **asdict(decision),
                }
                self.records.append(record)
                self.decisions.append(decision)
                self.journal.event("decision", **record)
                with self.executor.lock:
                    self.executor.tick()
                    reason = self._discard_reason(observation, stage)
                    if reason:
                        self.discarded += 1
                        self.journal.event(
                            "discarded",
                            stage=stage,
                            reason=reason,
                            observation_id=observation.id,
                            plan_version=record["plan_version"],
                        )
                        continue
                    if stage == "astra":
                        self._apply_plan(decision)
                    else:
                        self._apply_action(decision, observation)
                    self.previous = observation
            if self.state not in ("completed", "paused"):
                self.state = "paused"
                self.message = self.executor.reason
        except Exception as exc:
            self.stop("error: " + error_text(exc))
            self.journal.event("error", message=error_text(exc))
        finally:
            self.executor.stop(self.message or "finished")
            for provider in (self.decider, self.planner):
                try:
                    provider.close()
                except Exception:
                    pass
            self.report()

    def report(self):
        import json

        result = super().report()
        metrics = {}
        for stage in ("astra", "luna"):
            records = [r for r in self.requests if r["stage"] == stage]
            times = [r["latency"] * 1000 for r in records]
            metrics[stage] = {
                "calls": len(records),
                "errors": sum(r["status"] == "error" for r in records),
                "cancelled": sum(r["status"] == "cancelled" for r in records),
                "p50_ms": float(np.percentile(times, 50)) if times else None,
                "p95_ms": float(np.percentile(times, 95)) if times else None,
            }
        result.update(
            session_id=self.session_id,
            controller_mode=self.mode,
            plan_version=self.plan_version,
            language=self.language,
            decision_policy=POLICY_VERSION,
            model_metrics=metrics,
            completed_subgoals=list(self.completed_subgoals),
        )
        (self.journal.path / "report.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n"
        )
        return result
