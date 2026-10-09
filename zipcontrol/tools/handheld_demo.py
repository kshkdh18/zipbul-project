"""Open the regular GUI with USB and a goal prepared; the user starts/stops the mission.

Writes local status and window captures for integration validation. Never auto-starts AI input.
"""

import argparse
import json
import signal
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from zipcontrol.gui import Window, configure_application

parser = argparse.ArgumentParser()
parser.add_argument("--goal", required=True)
args = parser.parse_args()
output = Path("artifacts/handheld-demo")
output.mkdir(parents=True, exist_ok=True)
app = QApplication([])
configure_application(app)
window = Window()
window.flight.goal.setPlainText(args.goal)
window.tabs.setCurrentIndex(1)
window.show()
window.toggle_connection()
signal.signal(signal.SIGINT, lambda *_: window.close())
signal.signal(signal.SIGTERM, lambda *_: window.close())


def capture():
    mission = window.flight.mission
    result = {
        "connected": bool(window.bridge and not window.bridge.error),
        "bridge_error": window.bridge.error if window.bridge else None,
        "roi": window.flight.roi,
        "start_enabled": window.flight.start_button.isEnabled(),
        "status": window.flight.status.text(),
        "connection_status": window.status.text(),
        "mission": str(mission.journal.path) if mission else None,
        "state": mission.state if mission else "idle",
        "commands": mission.executor.submissions if mission else 0,
    }
    (output / "status.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    # Grabbing a Qt Quick scene can stall Python threads while the GPU/PNG path runs.
    # Never take diagnostic screenshots while a mission or manual input owns the controls.
    if (
        not window.flight.active
        and not window.flight.busy
        and not window.holding
        and window.demo_started is None
    ):
        window.grab().save(str(output / "window.png"))


timer = QTimer()
timer.timeout.connect(capture)
timer.start(2000)
app.aboutToQuit.connect(timer.stop)
app.exec()
