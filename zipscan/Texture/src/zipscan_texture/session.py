from __future__ import annotations

import hashlib
import json
import shutil
import stat
import zipfile
from pathlib import Path

import numpy as np

REQUIRED = {"video.mp4", "frames.jsonl", "mesh.obj", "depth.bin", "confidence.bin", "depth-index.jsonl", "events.jsonl", "validation.json"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def json_lines(path: Path):
    with path.open("rb") as stream:
        for number, line in enumerate(stream, 1):
            if not line.endswith(b"\n"):
                raise ValueError(f"Truncated {path.name}:{number}")
            if line.strip():
                yield json.loads(line)


def extract_verified(source: Path, destination: Path) -> dict:
    """Accept flat v1 packages only; never trust ZIP paths or unchecked cache files."""
    if source.is_dir():
        root = source
    else:
        destination.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(source) as archive:
            infos = archive.infolist()
            names = [item.filename for item in infos]
            if len(names) != len(set(names)):
                raise ValueError("Duplicate ZIP entries")
            for item in infos:
                if item.is_dir() or Path(item.filename).name != item.filename or item.filename in {".", ".."} or "\\" in item.filename or stat.S_ISLNK(item.external_attr >> 16):
                    raise ValueError(f"Unsafe or non-flat ZIP entry: {item.filename}")
            if "manifest.json" not in names or archive.getinfo("manifest.json").file_size > 1_048_576:
                raise ValueError("Missing/oversized manifest")
            manifest = json.loads(archive.read("manifest.json"))
            entries = manifest.get("files", [])
            declared = {item["name"] for item in entries}
            if len(declared) != len(entries) or set(names) != declared | {"manifest.json"}:
                raise ValueError("ZIP contents do not match manifest")
            total = sum(item.file_size for item in infos)
            if total > 12_000_000_000:
                raise ValueError("Package exceeds the 12 GB input limit")
            for item in infos:
                target = destination / item.filename
                expected = next((f for f in entries if f["name"] == item.filename), None)
                if expected and item.file_size != expected["bytes"]:
                    raise ValueError(f"ZIP size mismatch: {item.filename}")
                # Reuse only verified payloads from an interrupted run.
                if expected and target.is_file() and target.stat().st_size == expected["bytes"] and sha256(target) == expected["sha256"]:
                    continue
                if shutil.disk_usage(destination).free < item.file_size + 268_435_456:
                    raise ValueError("Not enough space to unpack session")
                temporary = target.with_suffix(target.suffix + ".part")
                with archive.open(item) as reader, temporary.open("wb") as writer:
                    shutil.copyfileobj(reader, writer, length=4 * 1024 * 1024)
                temporary.replace(target)
        root = destination
    manifest = read_json(root / "manifest.json")
    if manifest.get("format_version") != "1.0":
        raise ValueError("Only Zipscan package 1.0 is supported")
    if manifest.get("status") not in {"complete", "partial"}:
        raise ValueError("Input must be a finalized complete/partial session")
    names = {entry["name"] for entry in manifest["files"]}
    if not REQUIRED <= names:
        raise ValueError(f"Missing required input: {sorted(REQUIRED - names)}")
    for entry in manifest["files"]:
        name = entry["name"]
        if Path(name).name != name or name in {".", ".."} or "\\" in name:
            raise ValueError("Invalid manifest path")
        path = root / name
        if path.is_symlink() or not path.is_file() or path.stat().st_size != entry["bytes"] or sha256(path) != entry["sha256"]:
            raise ValueError(f"Payload checksum mismatch: {name}")
    if not np.allclose(manifest["settings"]["video_transform"], [1, 0, 0, 1, 0, 0], atol=1e-8):
        raise ValueError("Non-identity encoded video transform requires explicit support")
    return {"root": root, "manifest": manifest}


class Session:
    def __init__(self, root: Path, manifest: dict):
        self.root = root
        self.manifest = manifest
        self.frames = {}
        for frame in json_lines(root / "frames.jsonl"):
            fid = frame["frame_id"]
            if fid in self.frames:
                raise ValueError(f"Duplicate frame ID: {fid}")
            transform = np.asarray(frame["camera_transform"], dtype=np.float64)
            intrinsics = np.asarray(frame["intrinsics"], dtype=np.float64)
            if transform.shape != (4, 4) or intrinsics.shape != (3, 3) or not np.isfinite(transform).all() or not np.isfinite(intrinsics).all():
                raise ValueError("Invalid camera matrix")
            if not np.allclose(transform[3], [0, 0, 0, 1], atol=1e-4) or not np.allclose(transform[:3, :3].T @ transform[:3, :3], np.eye(3), atol=1e-3):
                raise ValueError("Camera transform is not rigid")
            if intrinsics[0, 0] <= 0 or intrinsics[1, 1] <= 0 or frame["image_width"] <= 0 or frame["image_height"] <= 0:
                raise ValueError("Invalid image calibration")
            if frame["video_status"] == "written":
                if abs(frame["video_pts"] - (frame["ar_timestamp"] - manifest["time_origin"])) > 2e-6:
                    raise ValueError("AR/video time origin mismatch")
            elif "video_pts" in frame:
                raise ValueError("Unwritten frame claims a video PTS")
            frame["transform"] = transform
            frame["k"] = intrinsics
            self.frames[fid] = frame
        self.depths = {}
        depth_end = confidence_end = 0
        for depth in json_lines(root / "depth-index.jsonl"):
            fid = depth["frame_id"]
            if fid in self.depths or fid not in self.frames:
                raise ValueError("Invalid depth/frame association")
            if abs(depth["ar_timestamp"] - self.frames[fid]["ar_timestamp"]) > 1e-6:
                raise ValueError("Depth and camera are not from the same ARFrame")
            self.depths[fid] = depth
            if depth.get("missing_reason"):
                continue
            w, h = depth["width"], depth["height"]
            if not (0 < w <= 16384 and 0 < h <= 16384) or depth["depth_length"] != w * h * 4 or depth["confidence_length"] != w * h:
                raise ValueError("Invalid depth dimensions")
            if depth["depth_offset"] != depth_end or depth["confidence_offset"] != confidence_end:
                raise ValueError("Noncontiguous or overlapping depth index")
            frame = self.frames[fid]
            expected = np.diag([w / frame["image_width"], h / frame["image_height"], 1]) @ frame["k"]
            if not np.allclose(depth["intrinsics"], expected, rtol=1e-5, atol=1e-4):
                raise ValueError("Depth intrinsics disagree with source image calibration")
            depth_end += depth["depth_length"]
            confidence_end += depth["confidence_length"]
        if depth_end != (root / "depth.bin").stat().st_size or confidence_end != (root / "confidence.bin").stat().st_size:
            raise ValueError("Depth index does not cover the binary files")
        self.depth_bytes = np.memmap(root / "depth.bin", mode="r", dtype="u1")
        self.confidence_bytes = np.memmap(root / "confidence.bin", mode="r", dtype="u1")

    def depth_maps(self, fid: int):
        item = self.depths[fid]
        if item.get("missing_reason"):
            raise ValueError("No depth for this frame")
        offset = item["depth_offset"]
        depth = self.depth_bytes[offset:offset + item["depth_length"]].view("<f4").reshape(item["height"], item["width"])
        offset = item["confidence_offset"]
        confidence = self.confidence_bytes[offset:offset + item["confidence_length"]].reshape(item["height"], item["width"])
        return depth, confidence
