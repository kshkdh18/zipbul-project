"""Optional axis settings and per-session UI references, separate from L/R calibration."""

import hashlib
import json
import math
import os
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
from PIL import Image

from .control import Stick

AXES = ("yaw", "vertical", "lateral", "forward")
DEFAULT_AXES = (("yaw", 1), ("vertical", -1), ("lateral", 1), ("forward", -1))


def validate_camera(camera, width, height):
    if camera is None:
        return
    if len(camera) != 4 or any(type(v) not in (int, float) or not math.isfinite(v) for v in camera):
        raise ValueError("Invalid camera ROI")
    x, y, w, h = camera
    if not (x >= 0 and y >= 0 and w >= 30 and h >= 30 and x + w <= width and y + h <= height):
        raise ValueError("Camera ROI outside frame")


def anchor(frame, stick):
    # Fixed pixels outside the moving knob; small enough to avoid the camera viewport.
    r = stick.radius
    x0, y0 = max(0, int(stick.x - r)), max(0, int(stick.y - r))
    crop = frame.rgb[y0 : int(stick.y + r) + 1, x0 : int(stick.x + r) + 1]
    gray = np.asarray(Image.fromarray(crop).convert("L").resize((32, 32)), dtype=np.float32)
    yy, xx = np.indices((32, 32))
    ring = (xx - 15.5) ** 2 + (yy - 15.5) ** 2 > 9**2
    return gray[ring].astype(int).tolist()


@dataclass
class FlightProfile:
    serial: str
    width: int
    height: int
    sticks: list
    axes: list
    camera: list | None
    anchors: list
    verified: bool = False

    def validate(self):
        # "verified" describes old operator-saved records; it is not a prerequisite to run.
        if len(self.sticks) != 2 or len(self.axes) != 4 or len(self.anchors) != 2:
            raise ValueError("Incomplete flight profile")
        for s in self.sticks:
            Stick(**s).validate(self.width, self.height)
        if sorted(x[0] for x in self.axes) != sorted(AXES):
            raise ValueError("Assign each flight axis exactly once")
        if any(len(x) != 2 or type(x[1]) is not int or x[1] not in (-1, 1) for x in self.axes):
            raise ValueError("Axis sign must be -1 or 1")
        validate_camera(self.camera, self.width, self.height)
        if any(not a or any(type(v) is not int or not 0 <= v <= 255 for v in a) for a in self.anchors):
            raise ValueError("Invalid UI anchors")

    @classmethod
    def capture_layout(cls, frame, sticks):
        """An in-memory reference of the current controls, never saved or called verified."""
        if not sticks or len(sticks) != 2:
            raise ValueError("L/R 조이스틱 위치 보정이 필요합니다.")
        for stick in sticks:
            stick.validate(frame.width, frame.height)
        return cls(
            "",
            frame.width,
            frame.height,
            [asdict(s) for s in sticks],
            [list(a) for a in DEFAULT_AXES],
            None,
            [anchor(frame, s) for s in sticks],
            False,
        )

    def matches(self, frame, sticks):
        return (frame.width, frame.height) == (self.width, self.height) and self.sticks == [
            asdict(s) for s in sticks
        ]

    def visible(self, frame):
        if (frame.width, frame.height) != (self.width, self.height):
            return False
        for saved, s in zip(self.anchors, self.sticks, strict=True):
            current = anchor(frame, Stick(**s))
            if len(saved) != len(current) or np.mean(np.abs(np.array(saved) - current)) > 25:
                return False
        return True


class FlightProfileStore:
    def __init__(self, directory=None):
        self.directory = Path(directory or ".runtime/flight-profiles")

    def path(self, serial, width, height):
        identity = hashlib.sha256(serial.encode()).hexdigest()[:16]
        return self.directory / f"{identity}-{width}x{height}.json"

    def save(self, profile):
        profile.validate()
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self.path(profile.serial, profile.width, profile.height)
        name = None
        try:
            with tempfile.NamedTemporaryFile("w", dir=self.directory, delete=False) as f:
                name = Path(f.name)
                json.dump({"version": 1, **asdict(profile)}, f, ensure_ascii=False, allow_nan=False)
                f.flush()
                os.fsync(f.fileno())
            name.replace(path)
        finally:
            if name:
                name.unlink(missing_ok=True)

    def load(self, serial, width, height):
        path = self.path(serial, width, height)
        if not path.exists():
            return None
        data = json.loads(path.read_text())
        if data.pop("version") != 1:
            raise ValueError("Unsupported flight profile")
        profile = FlightProfile(**data)
        profile.validate()
        if (profile.serial, profile.width, profile.height) != (serial, width, height):
            raise ValueError("Flight profile identity mismatch")
        return profile
