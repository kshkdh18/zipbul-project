from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np

from .geometry import Mesh, depth_visibility, project
from .session import Session


def srgb_to_linear(rgb):
    value = np.asarray(rgb, np.float32) / 255
    return np.where(value <= 0.04045, value / 12.92, ((value + 0.055) / 1.055) ** 2.4)


def apply_gain(image, gain):
    values = srgb_to_linear(np.arange(256, dtype=np.float32))[:, None] * np.asarray(gain)[None, :]
    values = np.where(values <= 0.0031308, values * 12.92, 1.055 * np.maximum(values, 0) ** (1 / 2.4) - 0.055)
    table = np.clip(np.rint(values * 255), 0, 255).astype(np.uint8)
    return table[image, np.arange(3)]


class Images:
    def __init__(self, directory: Path, keyframes: list[dict]):
        self.directory = directory
        self.keyframes = keyframes

    @lru_cache(maxsize=8)
    def raw(self, index: int):
        image = cv2.imread(str(self.directory / self.keyframes[index]["image"]))
        if image is None:
            raise ValueError("Missing decoded keyframe")
        return cv2.cvtColor(image, cv2.COLOR_BGR2RGB)

    def pixel_coordinates(self, index, uv, frame):
        keyframe = self.keyframes[index]
        scale = np.array([keyframe["width"] / frame["image_width"], keyframe["height"] / frame["image_height"]])
        # OpenCV resize preserves pixel centers, not the top-left pixel corner.
        return (uv + 0.5) * scale - 0.5

    def sample(self, index, uv, frame, gain=None):
        image = self.raw(int(index))
        coordinates = self.pixel_coordinates(index, uv, frame)
        x, y = coordinates[..., 0].astype(np.float32), coordinates[..., 1].astype(np.float32)
        shape = x.shape
        x, y = x.ravel(), y.ravel()
        pieces = [cv2.remap(image, x[start:start+16384].reshape(-1, 1), y[start:start+16384].reshape(-1, 1), interpolation=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE).reshape(-1, 3) for start in range(0, len(x), 16384)]
        rgb = np.concatenate(pieces).reshape(*shape, 3) if pieces else np.empty((*shape, 3), np.uint8)
        return rgb if gain is None else apply_gain(rgb, gain)


def choose_views(mesh: Mesh, session: Session, keyframes: list[dict], images: Images, config: dict, log=print):
    count = len(mesh.faces)
    best = np.full(count, -1, np.int32)
    second = best.copy()
    scores = np.zeros(count, np.float32)
    second_scores = scores.copy()
    gains = np.ones((len(keyframes), 3), np.float32)
    reference_color = np.zeros((count, 3), np.float32)
    reference_seen = np.zeros(count, bool)
    sharp_median = max(1, np.median([item["sharpness"] for item in keyframes]))
    stats = {"nearby_face_tests": 0, "depth_consistent_face_tests": 0, "exposure_corrected_frames": 0}
    for index, keyframe in enumerate(keyframes):
        frame = session.frames[keyframe["frame_id"]]
        transform, k = frame["transform"], frame["k"]
        depth, confidence = session.depth_maps(keyframe["frame_id"])
        kd = np.asarray(session.depths[keyframe["frame_id"]]["intrinsics"])
        candidate = np.asarray(mesh.tree.query_ball_point(transform[:3, 3], config["max_distance"] * 1.6), np.int32)
        stats["nearby_face_tests"] += len(candidate)
        accepted, candidate_scores, accepted_uv = [], [], []
        for start in range(0, len(candidate), 50_000):
            ids = candidate[start:start+50_000]
            centers = mesh.centers[ids]
            uv, z = project(centers, transform, k)
            in_image = (uv[:, 0] >= 2) & (uv[:, 1] >= 2) & (uv[:, 0] < frame["image_width"]-2) & (uv[:, 1] < frame["image_height"]-2)
            valid, residual, conf = depth_visibility(centers, transform, kd, depth, confidence, far=config["max_distance"], tolerance=config["depth_tolerance"], min_confidence=config["min_confidence"])
            view = transform[:3, 3] - centers
            distance = np.linalg.norm(view, axis=1)
            cosine = np.abs(np.einsum("ij,ij->i", mesh.normals[ids], view)) / np.maximum(distance, 1e-8)
            keep = valid & in_image & (cosine >= 0.15) & (mesh.areas[ids] > 1e-10)
            ids, uv, z, cosine, residual, conf = ids[keep], uv[keep], z[keep], cosine[keep], residual[keep], conf[keep]
            if not len(ids):
                continue
            triangles = mesh.vertices[mesh.faces[ids]]
            # Check vertices AND edge midpoints. A centroid alone misses silhouette occlusions.
            points = np.concatenate([triangles, (triangles + np.roll(triangles, 1, axis=1)) / 2], axis=1)
            vertices_ok, _, _ = depth_visibility(points, transform, kd, depth, confidence, far=config["max_distance"], tolerance=config["depth_tolerance"], min_confidence=config["min_confidence"])
            projected, _ = project(points, transform, k)
            visible = vertices_ok.all(axis=1) & (projected[..., 0] >= 1).all(axis=1) & (projected[..., 1] >= 1).all(axis=1) & (projected[..., 0] < frame["image_width"]-1).all(axis=1) & (projected[..., 1] < frame["image_height"]-1).all(axis=1)
            ids, uv, z, cosine, residual, conf = ids[visible], uv[visible], z[visible], cosine[visible], residual[visible], conf[visible]
            if not len(ids):
                continue
            center_weight = 1 - 0.25 * np.minimum(1, np.linalg.norm((uv / [frame["image_width"], frame["image_height"]] - 0.5) * 2, axis=1))
            quality = np.clip(np.sqrt(keyframe["sharpness"] / sharp_median), 0.5, 1.5)
            score = (cosine ** 2 / np.maximum(z*z, 0.04)) * center_weight * quality * (0.7 + conf * 0.15) * np.exp(-residual / (config["depth_tolerance"] + 0.02 * z))
            accepted.append(ids); accepted_uv.append(uv); candidate_scores.append(score.astype(np.float32))
        if accepted:
            ids, uv, values = np.concatenate(accepted), np.concatenate(accepted_uv), np.concatenate(candidate_scores)
            stats["depth_consistent_face_tests"] += len(ids)
            # Repeated static surface samples provide conservative per-channel exposure alignment.
            sampled = (ids % 23) == 0
            sample_ids = ids[sampled]
            rgb = images.sample(index, uv[sampled], frame)
            linear = srgb_to_linear(rgb)
            existing = reference_seen[sample_ids] & (rgb.min(axis=1) > 18) & (rgb.max(axis=1) < 235)
            if existing.sum() >= 48:
                ratios = reference_color[sample_ids[existing]] / np.maximum(linear[existing], 0.005)
                gains[index] = np.clip(np.median(ratios, axis=0), 0.75, 1.33)
                stats["exposure_corrected_frames"] += 1
            unseen = ~reference_seen[sample_ids]
            reference_color[sample_ids[unseen]] = linear[unseen] * gains[index]
            reference_seen[sample_ids[unseen]] = True
            wins = values > scores[ids]
            winning_ids = ids[wins]
            second[winning_ids] = best[winning_ids]; second_scores[winning_ids] = scores[winning_ids]
            best[winning_ids] = index; scores[winning_ids] = values[wins]
            improves_second = ~wins & (values > second_scores[ids])
            second[ids[improves_second]] = index; second_scores[ids[improves_second]] = values[improves_second]
        if (index+1) % 10 == 0 or index == len(keyframes)-1:
            coverage = float(mesh.areas[best >= 0].sum() / max(mesh.areas.sum(), 1e-12))
            log(f"View selection {index+1}/{len(keyframes)} · observed surface area {coverage:.1%}")
    return best, second, scores, second_scores, gains, stats


def smooth_labels(best, second, scores, second_scores, adjacency, normals):
    left, right, _ = adjacency
    similar = np.abs(np.einsum("ij,ij->i", normals[left], normals[right])) > 0.95
    left, right = left[similar], right[similar]
    labels = best.copy()
    for _ in range(2):
        agreement_best = np.zeros(len(best), np.float32)
        agreement_second = agreement_best.copy()
        np.add.at(agreement_best, left, labels[right] == best[left])
        np.add.at(agreement_best, right, labels[left] == best[right])
        np.add.at(agreement_second, left, labels[right] == second[left])
        np.add.at(agreement_second, right, labels[left] == second[right])
        alternate_score = np.log(np.maximum(second_scores, 1e-20) / np.maximum(scores, 1e-20)) + 0.15 * agreement_second
        use_alternate = (second >= 0) & (second_scores >= 0.75 * scores) & (alternate_score > 0.15 * agreement_best)
        labels = np.where(use_alternate, second, best)
    return labels, int(np.count_nonzero(labels != best))
