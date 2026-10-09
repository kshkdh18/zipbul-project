from __future__ import annotations

import json
from pathlib import Path

import av
import cv2
import numpy as np

from .session import Session, read_json, write_json


def candidate_frames(session: Session, interval: float):
    eligible = sorted((f for fid, f in session.frames.items() if f["video_status"] == "written" and f["tracking_state"] == "normal" and fid in session.depths and not session.depths[fid].get("missing_reason")), key=lambda f: f["video_pts"])
    if not eligible:
        raise ValueError("No same-frame video/depth observations with normal tracking")
    bins = {}
    for i, frame in enumerate(eligible):
        previous = eligible[max(0, i-1)]
        dt = max(0.01, frame["video_pts"] - previous["video_pts"])
        translation = np.linalg.norm(frame["transform"][:3, 3] - previous["transform"][:3, 3]) / dt
        relative = previous["transform"][:3, :3].T @ frame["transform"][:3, :3]
        angular = np.arccos(np.clip((np.trace(relative) - 1) / 2, -1, 1)) / dt
        frame["motion"] = float(translation + 2 * angular)
        bucket = int((frame["video_pts"] + 1e-9) / interval)
        bins.setdefault(bucket, []).append(frame)
    # Decode two calm candidates per time bin, then let measured image sharpness choose.
    return {bucket: sorted(items, key=lambda f: (f["motion"], f["frame_id"]))[:2] for bucket, items in bins.items()}


def extract_keyframes(session: Session, cache: Path, interval: float, image_size: int, log=print):
    cache.mkdir(parents=True, exist_ok=True)
    cache_file = cache / "index.json"
    fingerprint = {"video_sha256": next(f["sha256"] for f in session.manifest["files"] if f["name"] == "video.mp4"), "interval": interval, "image_size": image_size, "algorithm": 1}
    if cache_file.exists():
        saved = read_json(cache_file)
        if saved["fingerprint"] == fingerprint and all((cache / f["image"]).exists() for f in saved["frames"]):
            log(f"Reusing {len(saved['frames'])} decoded keyframes")
            return saved["frames"]
    buckets = candidate_frames(session, interval)
    targets = sorted((f["video_pts"], bucket, f) for bucket, items in buckets.items() for f in items)
    target_pts = np.array([f[0] for f in targets])
    matches, selected = set(), {}
    with av.open(str(session.root / "video.mp4")) as container:
        stream = container.streams.video[0]
        stream.codec_context.thread_count = 4
        stream.thread_type = "AUTO"
        for video in container.decode(stream):
            if video.pts is None:
                continue
            pts = float(video.pts * video.time_base)
            at = int(np.searchsorted(target_pts, pts - 0.000_003))
            if at >= len(targets) or abs(target_pts[at] - pts) > 0.000_003:
                continue
            _, bucket, frame = targets[at]
            if at in matches:
                raise ValueError("Duplicate decoded PTS")
            matches.add(at)
            if (video.width, video.height) != (frame["image_width"], frame["image_height"]):
                raise ValueError("Decoded image size disagrees with camera calibration")
            rgb = video.to_ndarray(format="rgb24")
            sample = cv2.resize(rgb, (480, max(1, round(480 * video.height / video.width))), interpolation=cv2.INTER_AREA)
            sharpness = float(cv2.Laplacian(cv2.cvtColor(sample, cv2.COLOR_RGB2GRAY), cv2.CV_32F).var())
            quality = sharpness / (1 + 0.05 * frame["motion"])
            if bucket in selected and quality <= selected[bucket]["quality"]:
                continue
            scale = min(1.0, image_size / max(video.width, video.height))
            width, height = round(video.width * scale), round(video.height * scale)
            rgb = cv2.resize(rgb, (width, height), interpolation=cv2.INTER_AREA) if scale < 1 else rgb
            image_name = f"frame-{frame['frame_id']:08d}.png"
            # PNG cache avoids an extra lossy JPEG generation before atlas assembly.
            cv2.imwrite(str(cache / image_name), cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_PNG_COMPRESSION, 1])
            selected[bucket] = {"frame_id": frame["frame_id"], "video_pts": pts, "image": image_name, "width": width, "height": height, "sharpness": sharpness, "quality": quality}
            if len(selected) % 40 == 0:
                log(f"Decoded keyframes: {len(selected)}/{len(buckets)} ({pts:.0f}s)")
    if len(matches) != len(targets):
        raise ValueError(f"Video PTS mismatch: found {len(matches)} of {len(targets)} expected keyframe candidates")
    frames = [selected[k] for k in sorted(selected)]
    if not frames:
        raise ValueError("No usable decoded keyframes")
    write_json(cache_file, {"fingerprint": fingerprint, "frames": frames})
    return frames
