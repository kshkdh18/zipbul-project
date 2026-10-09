"""Persist manual joystick geometry; never persist touches or movement commands."""

import json
import os
import tempfile
from dataclasses import asdict
from pathlib import Path

from .control import Stick


class CalibrationStore:
    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path is not None else Path.cwd() / "calibration.json"

    def _read(self):
        if not self.path.exists():
            return {"version": 1, "devices": {}}
        try:
            data = json.loads(self.path.read_text())
            if (
                not isinstance(data, dict)
                or data.get("version") != 1
                or not isinstance(data.get("devices"), dict)
            ):
                raise ValueError("Unsupported calibration file")
            return data
        except (ValueError, TypeError) as exc:
            raise ValueError(f"Invalid calibration file: {self.path}") from exc

    def load(self, serial: str, width: int, height: int) -> tuple[Stick, Stick] | None:
        data = self._read()
        try:
            profile = data["devices"].get(serial, {}).get(f"{width}x{height}")
            if profile is None:
                return None
            sticks = tuple(Stick(**profile[side]) for side in ("left", "right"))
            for stick in sticks:
                stick.validate(width, height)
            return sticks
        except (TypeError, ValueError, KeyError, AttributeError) as exc:
            raise ValueError(f"Invalid joystick profile: {serial} / {width}x{height}") from exc

    def save(self, serial: str, width: int, height: int, left: Stick, right: Stick):
        for stick in (left, right):
            stick.validate(width, height)
        data = self._read()
        profiles = data["devices"].setdefault(serial, {})
        if not isinstance(profiles, dict):
            raise ValueError("Invalid device calibration profiles")
        profiles[f"{width}x{height}"] = {"left": asdict(left), "right": asdict(right)}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(
                "w", dir=self.path.parent, prefix=".calibration-", delete=False
            ) as file:
                temporary = Path(file.name)
                json.dump(data, file, ensure_ascii=False, indent=2, allow_nan=False)
                file.write("\n")
                file.flush()
                os.fsync(file.fileno())
            temporary.replace(self.path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
