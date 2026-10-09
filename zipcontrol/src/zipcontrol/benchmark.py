"""Paired API measurements on identical cropped evidence; never emits input."""

import json
import time
from dataclasses import asdict
from pathlib import Path

import numpy as np
from PIL import Image

from .actions import MOVEMENTS, Subgoal
from .astra import Astra
from .bridge import Frame
from .camera import CameraStore, crop_frame
from .flight_profile import DEFAULT_AXES
from .guard import GuardBridge
from .luna import LunaDecider
from .mission import Observation
from .planning import AstraPlanner
from .validation import output_directory


def fixture(frame, goal, index, roi):
    now = time.monotonic()
    oid = f"benchmark-{index}"
    return Observation(
        oid,
        frame,
        0,
        {
            "observation_id": oid,
            "session_id": "benchmark",
            "plan_version": 0,
            "goal": goal,
            "mode": "OBSERVATION_ONLY",
            "camera_only": True,
            "camera_roi": roi,
            "current_subgoal": asdict(Subgoal.direct(goal)),
            "planning_trigger": "mission_start",
            "completed_subgoals": [],
            "completion_verification": False,
            "frame_sequence": frame.sequence,
            "frame_epoch": frame.epoch,
            "frame_received_at": frame.received_at,
            "frame_decoded_at": frame.decoded_at,
            "observation_at": now,
            "current_command": None,
            "command_remaining_ms": 0,
            "continuous_hold_ms": 0,
            "recent_results": [],
            "operator_drag_fraction": 1.0,
            "axis_mapping_screen_lx_ly_rx_ry": DEFAULT_AXES,
        },
    )


def astra_actions(decision):
    if decision.name != "command_sticks":
        return {"observe": ["WAIT"], "finish": ["SUBGOAL_DONE"], "need_operator": ["NEED_OPERATOR"]}[
            decision.name
        ]
    args = decision.arguments
    values = (*(args["left_xy"] or (0, 0)), *(args["right_xy"] or (0, 0)))
    actions = []
    for value, (axis, sign) in zip(values, DEFAULT_AXES, strict=True):
        if abs(value) > 1e-6:
            actions.append(
                next(
                    action
                    for action, (a, s, _) in MOVEMENTS.items()
                    if a == axis and s == (1 if value * sign > 0 else -1)
                )
            )
    return sorted(actions) or ["WAIT"]


def benchmark_luna(
    serial=None,
    server_path=None,
    output=None,
    *,
    image=None,
    samples=20,
    goal="빨간 상자가 화면 중앙에 오도록 시점을 맞춰",
):
    if samples < 1:
        raise ValueError("samples must be positive")
    output = Path(output) if output else output_directory("luna-benchmark")
    output.mkdir(parents=True, exist_ok=True)
    if image:
        pixels = np.array(Image.open(image).convert("RGB"))
        now = time.monotonic()
        frame = Frame(pixels, 1, now, now, 0, 1)
        roi = [0, 0, frame.width, frame.height]
        evidence_source = "explicitly supplied already-cropped image"
    else:
        with GuardBridge(serial, server_path) as bridge:
            full = bridge.latest_frame()
            roi = CameraStore().load(bridge.adb.serial, full.width, full.height)
            frame = crop_frame(full, roi)
        evidence_source = "one real Android frame cropped to saved camera ROI"
    Image.fromarray(frame.rgb).save(output / "camera.png")
    records = []
    clients = {"luna": LunaDecider(), "astra": Astra(), "planner": AstraPlanner()}
    previous = fixture(frame, goal, "previous", roi)
    try:
        for index in range(samples):
            obs = fixture(frame, goal, index, roi)
            # Alternate ordering to avoid assigning all cold-start/network drift to one model.
            stages = ("luna", "astra") if index % 2 == 0 else ("astra", "luna")
            for stage in stages:
                started = time.monotonic()
                try:
                    decision = clients[stage].decide(obs, previous)
                    actions = [decision.action] if stage == "luna" else astra_actions(decision)
                    record = {
                        "sample": index,
                        "stage": stage,
                        "status": "passed",
                        "actions": actions,
                        **asdict(decision),
                    }
                except Exception as exc:
                    record = {"sample": index, "stage": stage, "status": "failed", "error": str(exc)}
                record["wall_latency_ms"] = (time.monotonic() - started) * 1000
                records.append(record)
                with (output / "requests.jsonl").open("a") as f:
                    f.write(json.dumps(record, ensure_ascii=False) + "\n")
                print(
                    json.dumps({k: record[k] for k in ("sample", "stage", "status", "wall_latency_ms")}),
                    flush=True,
                )
        try:
            planner_result = {"status": "passed", **asdict(clients["planner"].decide(obs, previous))}
        except Exception as exc:
            planner_result = {"status": "failed", "error": str(exc)}
    finally:
        for client in clients.values():
            client.close()
    metrics = {}
    for stage in ("astra", "luna"):
        rows = [r for r in records if r["stage"] == stage]
        successful = [r for r in rows if r["status"] == "passed"]
        times = [r["wall_latency_ms"] for r in successful]
        metrics[stage] = {
            "calls": len(rows),
            "errors": len(rows) - len(successful),
            "p50_ms": float(np.percentile(times, 50)) if times else None,
            "p95_ms": float(np.percentile(times, 95)) if times else None,
            "over_2s": sum(t > 2000 for t in times),
        }
    pairs = [[r for r in records if r["sample"] == i and r["status"] == "passed"] for i in range(samples)]
    comparable = [p for p in pairs if len(p) == 2]
    result = {
        "status": "passed"
        if all(r["status"] == "passed" for r in records) and planner_result["status"] == "passed"
        else "failed",
        "scope": "API only; no Android touches or physical motion. Astra function arguments versus Luna enum choice.",
        "evidence_source": evidence_source,
        "samples_per_model": samples,
        "metrics": metrics,
        "exact_action_agreement": sum(p[0]["actions"] == p[1]["actions"] for p in comparable)
        / len(comparable)
        if comparable
        else None,
        "comparable_pairs": len(comparable),
        "planner_probe": planner_result,
        "camera_size": [frame.width, frame.height],
        "output": str(output.resolve()),
    }
    (output / "report.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False), flush=True)
    return result
