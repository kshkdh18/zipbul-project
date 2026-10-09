"""Exercise the real Android -> common command -> Qt 3D path on Chrome's diagnostic page.

Run from the project directory with an idle, unlocked USB phone. Never touches DJI controls.
"""

import json
import traceback
from dataclasses import asdict
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtQuickWidgets import QQuickWidget
from PySide6.QtWidgets import QApplication

from zipcontrol.execution import execute_command
from zipcontrol.guard import GuardBridge
from zipcontrol.gui import Window, configure_application
from zipcontrol.lab import TouchLab, calibrate_lab

output = Path("artifacts/device-display")
output.mkdir(parents=True, exist_ok=True)
app = QApplication([])
configure_application(app)
bridge = GuardBridge().connect()
lab = TouchLab(bridge.adb, output).start()
window = None
report = {"scope": "actual Android Chrome touches and Qt visualization; no drone/API commands"}
failures = []
try:
    lab.open_phone()
    frame, layout, transform = calibrate_lab(bridge, lab)
    window = Window()
    window.connected(bridge)
    ox, oy, sx, sy = transform
    # Explicit diagnostic viewport selection, kept in memory only.
    x, y = max(0, int(ox) + 1), max(0, int(oy) + 1)
    w = min(frame.width - x, int(layout["width"] * sx) - 2)
    h = min(frame.height - y, int(layout["height"] * sy) - 2)
    window.flight.roi = [x, y, w, h]
    window.flight.roi_epoch = frame.epoch
    window.tabs.setCurrentIndex(1)
    window.flight.goal.setPlainText("실기 진단 · Android 두 포인터와 3D 표현 확인")
    window.show()

    def fail(exc):
        timer.stop()
        failures.append(f"{type(exc).__name__}: {exc}")
        report["failure_traceback"] = traceback.format_exc()
        app.quit()

    def start():
        try:
            bridge.arm("com.android.chrome")
            ack, event = execute_command(
                bridge,
                (0, -0.5),
                (0.5, -0.5),
                2000,
                stream=window.command_stream,
                reason="실기 진단: 위·앞·오른쪽 이동",
            )
            report.update(
                command_ack=ack, execution_event=asdict(event), frame_size=[frame.width, frame.height]
            )
        except Exception as exc:
            fail(exc)

    def heartbeat():
        if "command_ack" not in report:
            return
        try:
            bridge.guard.heartbeat()
            bridge.guard.update()
        except Exception as exc:
            fail(exc)

    def capture():
        try:
            window.grab().save(str(output / "window.png"))
            view = window.simulation_panel.view
            report["qml_ready"] = view.status() == QQuickWidget.Status.Ready
            view.grabFramebuffer().save(str(output / "scene.png"))
            sim = window.simulation_panel.simulation
            report["virtual_position"] = [sim.x, sim.y, sim.z]
            report["android_received_two_touches"] = any(
                e["kind"] == "down" and e["active"] == 2 for e in lab.snapshot()
            )
            assert report["qml_ready"] and report["android_received_two_touches"]
            assert sim.x > 0 and sim.y > 0 and sim.z < 0
        except Exception as exc:
            fail(exc)

    def finish():
        timer.stop()
        try:
            report["final_guard"] = bridge.guard.snapshot()
            report["android_released"] = any(e["kind"] == "up" and e["active"] == 0 for e in lab.snapshot())
            assert report["final_guard"]["active"] == 0 and report["android_released"]
            assert window.simulation_panel.simulation.deadline == 0
        except Exception as exc:
            failures.append(str(exc) or type(exc).__name__)
        app.quit()

    timer = QTimer()
    timer.timeout.connect(heartbeat)
    timer.start(50)
    QTimer.singleShot(400, start)
    QTimer.singleShot(1400, capture)
    QTimer.singleShot(2800, finish)
    app.exec()
    timer.stop()
    if "final_guard" not in report:
        failures.append("Device verification did not reach completion")
except Exception as exc:
    failures.append(f"{type(exc).__name__}: {exc}")
    report["failure_traceback"] = traceback.format_exc()
finally:
    if window:
        window.close()
    bridge.close()
    lab.close()
    report.update(status="failed" if failures else "passed", errors=failures)
    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False), flush=True)
raise SystemExit(bool(failures))
