"""Exercise the GUI/executor lease on Chrome, optionally reproducing active screenshot stalls."""

import argparse
import json
import time
import traceback
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from zipcontrol.astra import Decision
from zipcontrol.guard import GuardBridge
from zipcontrol.gui import Window, configure_application
from zipcontrol.guidance import GuidanceMission
from zipcontrol.lab import TouchLab, calibrate_lab
from zipcontrol.luna import ActionChoice

parser = argparse.ArgumentParser()
parser.add_argument("--active-capture", action="store_true")
parser.add_argument("--seconds", type=float, default=20)
parser.add_argument("--output", type=Path, required=True)
args = parser.parse_args()
args.output.mkdir(parents=True, exist_ok=True)


class DiagnosticBridge(GuardBridge):
    def arm(self, package="com.android.chrome"):
        # This test is strictly confined to Chrome regardless of production's DJI default.
        return super().arm("com.android.chrome")


class Planner:
    def decide(self, *_):
        return Decision(
            "set_subgoal",
            {
                "goal": "Chrome 포인터 유지 진단",
                "completion_criteria": "진단 종료",
                "allowed_actions": ["YAW_LEFT"],
                "reason": "진단용 고정 enum",
            },
        )

    def close(self):
        pass


class Decider(Planner):
    def decide(self, *_):
        time.sleep(0.4)
        return ActionChoice("YAW_LEFT", 1, {"YAW_LEFT": 1}, latency=0.4)


app = QApplication([])
configure_application(app)
window = Window()
bridge = DiagnosticBridge().connect()
lab = TouchLab(bridge.adb, args.output).start()
mission = None
report = {
    "scope": "real Chrome touch + Qt + fixture decisions; no aircraft/API commands",
    "active_capture": args.active_capture,
    "captures_ms": [],
}
try:
    lab.open_phone()
    window.connected(bridge)
    frame, layout, (ox, oy, sx, sy) = calibrate_lab(bridge, lab)
    roi = [
        max(0, int(ox) + 1),
        max(0, int(oy) + 1),
        int(layout["width"] * sx) - 2,
        int(layout["height"] * sy) - 2,
    ]
    roi[2] = min(roi[2], frame.width - roi[0])
    roi[3] = min(roi[3], frame.height - roi[1])
    window.flight.roi = roi
    window.flight.roi_epoch = frame.epoch
    window.tabs.setCurrentIndex(1)
    window.flight.goal.setPlainText("Chrome 전용 heartbeat 진단")
    mission = GuidanceMission(
        bridge,
        Decider(),
        Planner(),
        "Chrome 전용 heartbeat 진단",
        live=True,
        camera_roi=roi,
        output=args.output / "mission",
        stream=window.command_stream,
    )
    window.flight.mission = mission
    window.show()
    started = time.monotonic()
    ended = False

    def finish():
        global ended
        if ended:
            return
        ended = True
        timer.stop()
        sampler.stop()
        report["reason_before_stop"] = mission.executor.reason
        report["survived"] = mission.executor.running
        report["guard_before_stop"] = bridge.guard.diagnostics()
        mission.stop("diagnostic_finished")
        mission.thread.join(2)
        report["commands"] = mission.executor.submissions
        report["max_tick_gap_ms"] = mission.executor.max_tick_gap_ms
        window.close()
        app.quit()

    def sample():
        if args.active_capture and mission.executor.running:
            before = time.monotonic()
            window.grab().save(str(args.output / "active-window.png"))
            report["captures_ms"].append((time.monotonic() - before) * 1000)

    def check():
        if not mission.executor.running or time.monotonic() - started >= args.seconds:
            finish()

    timer, sampler = QTimer(), QTimer()
    timer.timeout.connect(check)
    sampler.timeout.connect(sample)
    mission.start()
    timer.start(100)
    sampler.start(2000)
    app.exec()
except Exception as exc:
    report["error"] = f"{type(exc).__name__}: {exc}"
    report["traceback"] = traceback.format_exc()
finally:
    if mission:
        mission.stop("diagnostic_closed")
    window.close()
    bridge.close()
    lab.close()
    report["transport_logs"] = list(bridge.transport.logs)
    report["status"] = "passed" if report.get("survived") and not report.get("error") else "failed"
    (args.output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(
        json.dumps(
            {k: v for k, v in report.items() if k not in ("guard_before_stop", "transport_logs")},
            ensure_ascii=False,
        ),
        flush=True,
    )
raise SystemExit(report["status"] != "passed")
