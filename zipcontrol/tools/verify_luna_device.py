"""Real Chrome touches for all semantic enums. Choices are fixtures, no model/drone commands."""

import json
import threading
import time
import traceback
from dataclasses import asdict
from pathlib import Path

from PIL import Image

from zipcontrol.actions import MOVEMENTS, ActionAdapter, Subgoal
from zipcontrol.execution import CommandStream, execute_command
from zipcontrol.guard import GuardBridge
from zipcontrol.guard_validation import _wait_pair_released
from zipcontrol.lab import TouchLab, calibrate_lab
from zipcontrol.simulation import Simulation
from zipcontrol.validation import _wait_event

output = Path("artifacts/luna-device-path")
output.mkdir(parents=True, exist_ok=True)
report = {
    "scope": "real Android Chrome touches; fixture enums via ActionAdapter; no API or aircraft movement",
    "directions": [],
    "errors": [],
}
bridge = lab = worker = None
stop = threading.Event()
stream = CommandStream()
sim = Simulation()
try:
    bridge = GuardBridge().connect()
    lab = TouchLab(bridge.adb, output).start()
    lab.open_phone()
    frame, layout, (ox, oy, sx, sy) = calibrate_lab(bridge, lab)

    def heartbeat():
        while not stop.wait(0.05):
            try:
                bridge.guard.heartbeat()
                if bridge.guard.snapshot().get("expires_at_ms"):
                    bridge.guard.update()
            except Exception as exc:
                report["errors"].append(str(exc))
                return

    worker = threading.Thread(target=heartbeat, daemon=True)
    worker.start()
    for action in MOVEMENTS:
        bridge.arm("com.android.chrome")
        started = time.monotonic()
        command = ActionAdapter.command(action, action, Subgoal.direct("8방향 실기 진단"))
        left, right = command["left_xy"], command["right_xy"]
        ack, event = execute_command(
            bridge,
            left,
            right,
            command["valid_for_ms"],
            stream=stream,
            source="luna_decisions",
            reason=command["reason"],
        )
        assert ack["active"] == 1
        sim.consume(event)
        selected = 0 if left is not None else 1
        xy = left if selected == 0 else right
        px, py = bridge.controller.sticks[selected].target(xy)
        tx, ty = (px - ox) / sx, (py - oy) / sy
        down = _wait_event(lab, lambda e: e["kind"] == "down" and e["active"] == 1, started)
        move = _wait_event(
            lab,
            lambda e, pid=down["id"], x=tx, y=ty: (
                e["kind"] == "move"
                and e.get("id") == pid
                and e["active"] == 1
                and abs(e["x"] - x) < 2
                and abs(e["y"] - y) < 2
            ),
            started,
        )
        sim.advance(time.monotonic())
        assert sim.label == MOVEMENTS[action][2] and sim.show_arrows
        report["directions"].append(
            {
                "action": action,
                "ack": ack,
                "event": asdict(event),
                "observed_css_xy": [move["x"], move["y"]],
                "label": sim.label,
            }
        )
        pair = {"ids": (down["id"],), "seq": down["seq"], "page_id": down.get("page_id")}
        if action == "BACKWARD":
            _wait_pair_released(lab, pair, timeout=3)
            sim.advance(time.monotonic())
            status = bridge.guard.snapshot()
            assert status["active"] == 0 and status["expires_at_ms"] == 0
            assert sim.deadline == 0
            report["expiry"] = {"status": status, "virtual_motion_stopped": True}
        else:
            bridge.guard.release()
            _wait_pair_released(lab, pair)
        print(action + " passed", flush=True)
    Image.fromarray(bridge.latest_frame().rgb).save(output / "android.png")
except Exception as exc:
    report["errors"].append(f"{type(exc).__name__}: {exc}")
    report["traceback"] = traceback.format_exc()
    if bridge:
        report["bridge_error"] = bridge.error
        report["transport_logs"] = list(bridge.transport.logs)
finally:
    stop.set()
    if worker:
        worker.join(1)
    if bridge:
        bridge.close()
    if lab:
        lab.close()
    report["status"] = "passed" if len(report["directions"]) == 8 and not report["errors"] else "failed"
    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(
        json.dumps(
            {"status": report["status"], "directions": len(report["directions"]), "errors": report["errors"]},
            ensure_ascii=False,
        ),
        flush=True,
    )
raise SystemExit(report["status"] != "passed")
