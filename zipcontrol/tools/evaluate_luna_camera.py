"""Five labeled synthetic camera fixtures, real Decisions API, no Android connection."""

import json
import time
from dataclasses import asdict
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from zipcontrol.benchmark import fixture
from zipcontrol.bridge import Frame
from zipcontrol.luna import LunaDecider

output = Path("artifacts/luna-visual-evaluation")
output.mkdir(parents=True, exist_ok=True)
cases = [
    (120, 240, "YAW_LEFT"),
    (520, 240, "YAW_RIGHT"),
    (320, 80, "ASCEND"),
    (320, 400, "DESCEND"),
    (320, 240, "SUBGOAL_DONE"),
]
results = []
client = LunaDecider()
try:
    for x, y, expected in cases:
        image = Image.new("RGB", (640, 480), (180, 190, 200))
        draw = ImageDraw.Draw(image)
        draw.rectangle((x - 35, y - 35, x + 35, y + 35), fill=(230, 40, 30))
        image.save(output / f"{expected}.png")
        now = time.monotonic()
        frame = Frame(np.array(image), len(results) + 1, now, now, 0, 1)
        obs = fixture(frame, "빨간 사각형을 화면 중앙에 맞춰", expected, [0, 0, 640, 480])
        result = client.decide(obs)
        results.append({"expected": expected, "correct": result.action == expected, **asdict(result)})
        print(json.dumps(results[-1], ensure_ascii=False), flush=True)
finally:
    client.close()
    report = {
        "scope": "five labeled synthetic images; actual API; no Android input",
        "cases": results,
        "correct": sum(r["correct"] for r in results),
        "total": len(cases),
    }
    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
raise SystemExit(report["correct"] != report["total"])
