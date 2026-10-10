"""Render the real Mac Qt scene with synthetic inputs; never connects to Android or an API.

Run: QT_QPA_PLATFORM=cocoa uv run python tools/render_preview.py
"""

import argparse
import json
import time
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
from PySide6.QtCore import QTimer
from PySide6.QtQuickWidgets import QQuickWidget
from PySide6.QtWidgets import QApplication

from zipcontrol.bridge import Frame
from zipcontrol.camera import crop_frame
from zipcontrol.flight_profile import DEFAULT_AXES
from zipcontrol.gui import Window, configure_application

parser = argparse.ArgumentParser()
parser.add_argument("--language", choices=("en", "ko"), default="en")
parser.add_argument("--output", type=Path, default=Path("artifacts/ui-preview"))
args = parser.parse_args()
output = args.output
output.mkdir(parents=True, exist_ok=True)
english = args.language == "en"
app = QApplication([])
configure_application(app)
window = Window(settings_path=output / "settings.json")
window.language_combo.setCurrentIndex(window.language_combo.findData(args.language))
window.timer.stop()
window.resize(1500, 920)
window.tabs.setCurrentIndex(1)
window.flight.goal.setPlainText(
    "Center the red box in the camera view" if english else "빨간 상자가 화면 중앙에 오도록 시점을 맞춰"
)
window.flight.status.setText(
    "Synthetic preview · No Android or API connection"
    if english
    else "화면 검증용 합성 영상 · Android와 API 연결 없음"
)
image = Image.new("RGB", (800, 1200), "#15212b")
draw = ImageDraw.Draw(image)
draw.rectangle((30, 190, 770, 730), fill="#c7cbd0")
draw.polygon(((30, 730), (770, 730), (570, 420), (220, 420)), fill="#8e9aa2")
for x in range(50, 790, 90):
    draw.line((400, 420, x, 730), fill="#b5c0c8", width=2)
draw.rectangle((475, 380, 615, 545), fill="#db6652")
draw.polygon(((475, 380), (525, 340), (665, 340), (615, 380)), fill="#ee9c83")
draw.polygon(((615, 380), (665, 340), (665, 505), (615, 545)), fill="#a6473b")
for cx in (180, 620):
    draw.ellipse((cx - 90, 900, cx + 90, 1080), outline="#527087", width=4)
    draw.ellipse((cx - 24, 966, cx + 24, 1014), fill="#dbe3e8")
frame = Frame(np.array(image), 1, time.monotonic(), time.monotonic(), 0, 1)
window.preview.frame = frame
window.camera_preview.frame = crop_frame(frame, [30, 190, 740, 540])
window.show()
Image.fromarray(window.camera_preview.frame.rgb).save(output / "camera.png")
failures = []


def command():
    now = time.monotonic()
    window.command_stream.accepted(
        (0.6, -0.8),
        (0.6, -0.8),
        2000,
        {"expires_at_ms": 2000, "device_time_ms": 0},
        "ai",
        "Turn right and move forward to center the box."
        if english
        else "상자를 중앙에 맞추도록 오른쪽으로 돌며 앞으로 이동하세요.",
        DEFAULT_AXES,
        now,
    )


def capture():
    view = window.simulation_panel.view
    errors = [e.toString() for e in view.errors()]
    if view.status() != QQuickWidget.Status.Ready or errors:
        failures.extend(errors or ["QML not ready"])
    framebuffer = view.grabFramebuffer()
    if framebuffer.isNull():
        failures.append("No 3D framebuffer")
    else:
        framebuffer.save(str(output / "scene.png"))
    window.grab().save(str(output / "window.png"))
    window.tabs.setCurrentIndex(2)
    window.grab().save(str(output / "options.png"))
    result = {
        "qml_ready": view.status() == QQuickWidget.Status.Ready,
        "framebuffer_size": [framebuffer.width(), framebuffer.height()],
        "synthetic_input": True,
        "android_connected": False,
        "language": args.language,
        "errors": failures,
    }
    (output / "report.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result), flush=True)
    window.close()
    app.quit()


QTimer.singleShot(400, command)
QTimer.singleShot(1600, capture)
app.exec()
raise SystemExit(bool(failures))
