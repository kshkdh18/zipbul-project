"""Camera-only observations and device/geometry-bound ROI persistence."""

import hashlib
import json
import math
import os
import tempfile
from dataclasses import replace
from pathlib import Path

import numpy as np

from .i18n import message as m


def camera_rect(roi, width, height):
    if roi is None:
        raise ValueError(m("Astra가 볼 카메라 영상 영역을 먼저 지정하세요."))
    if len(roi) != 4 or any(
        isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in roi
    ):
        raise ValueError(m("잘못된 카메라 영역입니다."))
    x, y, w, h = roi
    if x < 0 or y < 0 or w < 30 or h < 30 or x + w > width or y + h > height:
        raise ValueError(m("카메라 영역이 화면 범위를 벗어났습니다. 다시 지정하세요."))
    # Round inward: a fractional border must never reveal pixels outside the selected area.
    x0, y0, x1, y1 = math.ceil(x), math.ceil(y), math.floor(x + w), math.floor(y + h)
    return x0, y0, x1 - x0, y1 - y0


def crop_frame(frame, roi):
    x, y, w, h = camera_rect(roi, frame.width, frame.height)
    rgb = np.array(frame.rgb[y : y + h, x : x + w], copy=True, order="C")
    rgb.flags.writeable = False
    return replace(frame, rgb=rgb)


class CameraStore:
    def __init__(self, directory=".runtime/cameras"):
        self.directory = Path(directory)

    def path(self, serial, width, height):
        key = hashlib.sha256(serial.encode()).hexdigest()[:16]
        return self.directory / f"{key}-{width}x{height}.json"

    def load(self, serial, width, height):
        path = self.path(serial, width, height)
        if not path.exists():
            return None
        data = json.loads(path.read_text())
        if data.get("version") != 1 or data.get("size") != [width, height]:
            raise ValueError(m("카메라 영역 설정이 현재 화면과 다릅니다."))
        return list(camera_rect(data["roi"], width, height))

    def save(self, serial, width, height, roi):
        rect = camera_rect(roi, width, height)
        self.directory.mkdir(parents=True, exist_ok=True)
        name = None
        try:
            with tempfile.NamedTemporaryFile("w", dir=self.directory, delete=False) as file:
                name = Path(file.name)
                json.dump({"version": 1, "size": [width, height], "roi": rect}, file)
                file.flush()
                os.fsync(file.fileno())
            name.replace(self.path(serial, width, height))
        finally:
            if name:
                name.unlink(missing_ok=True)
