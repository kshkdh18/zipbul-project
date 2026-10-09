from __future__ import annotations

from array import array
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from scipy.spatial import cKDTree


@dataclass
class Mesh:
    vertices: np.ndarray
    faces: np.ndarray
    centers: np.ndarray
    normals: np.ndarray
    areas: np.ndarray
    tree: cKDTree

    @classmethod
    def load(cls, path: Path):
        vertices, faces = array("f"), array("I")
        with path.open() as stream:
            for line in stream:
                if line.startswith("v "):
                    parts = line.split()
                    if len(parts) != 4:
                        raise ValueError("Expected XYZ vertices")
                    vertices.extend(map(float, parts[1:]))
                elif line.startswith("f "):
                    parts = line.split()
                    if len(parts) != 4 or any("/" in item for item in parts[1:]):
                        raise ValueError("Input must be the untextured triangular Zipscan OBJ")
                    indices = [int(item) - 1 for item in parts[1:]]
                    if min(indices) < 0:
                        raise ValueError("Negative/zero OBJ indices are unsupported")
                    faces.extend(indices)
        v = np.frombuffer(vertices, dtype=np.float32).reshape(-1, 3)
        f = np.frombuffer(faces, dtype=np.uint32).reshape(-1, 3)
        if not len(v) or not len(f) or not np.isfinite(v).all() or int(f.max()) >= len(v):
            raise ValueError("Empty/invalid mesh")
        # Keep shared source positions and face order; never silently repair or decimate.
        centers = np.empty((len(f), 3), np.float32)
        normals = np.empty_like(centers)
        areas = np.empty(len(f), np.float32)
        for start in range(0, len(f), 100_000):
            end = min(start + 100_000, len(f))
            triangles = v[f[start:end]]
            centers[start:end] = triangles.mean(axis=1)
            cross = np.cross(triangles[:, 1] - triangles[:, 0], triangles[:, 2] - triangles[:, 0])
            size = np.linalg.norm(cross, axis=1)
            normals[start:end] = cross / np.maximum(size[:, None], 1e-12)
            areas[start:end] = size / 2
        return cls(v, f, centers, normals, areas, cKDTree(centers))


def project(points: np.ndarray, camera_to_world: np.ndarray, intrinsics: np.ndarray):
    """World -> ARKit camera (+Y up/-Z forward) -> sensor pixels (+v down)."""
    camera = (points - camera_to_world[:3, 3]) @ camera_to_world[:3, :3]
    z = -camera[..., 2]
    image_axes = camera * np.array([1, -1, -1])
    homogeneous = image_axes @ intrinsics.T
    uv = homogeneous[..., :2] / np.where(z > 1e-8, z, 1)[..., None]
    return uv, z


def depth_visibility(points, transform, k_depth, depth, confidence, *, near=0.2, far=5.0, tolerance=0.12, relative_tolerance=0.02, min_confidence=1):
    uv, z = project(points, transform, k_depth)
    finite = np.isfinite(uv).all(axis=-1) & np.isfinite(z)
    safe_uv = np.where(finite[..., None], uv, 0)
    x, y = np.rint(safe_uv[..., 0]).astype(np.int32), np.rint(safe_uv[..., 1]).astype(np.int32)
    inside = finite & (z >= near) & (z <= far) & (x >= 0) & (y >= 0) & (x < depth.shape[1]) & (y < depth.shape[0])
    x = np.clip(x, 0, depth.shape[1] - 1)
    y = np.clip(y, 0, depth.shape[0] - 1)
    observed, conf = depth[y, x], confidence[y, x]
    residual = np.abs(observed - z)
    valid = inside & np.isfinite(observed) & (observed > 0) & (conf >= min_confidence) & (conf <= 2) & (residual <= tolerance + relative_tolerance * z)
    return valid, residual, conf


def face_adjacency(faces: np.ndarray):
    """Return shared-edge face pairs without changing indices or merging anchors."""
    edge_count = len(faces) * 3
    keys = np.empty(edge_count, np.uint64)
    for edge in range(3):
        a, b = faces[:, edge].astype(np.uint64), faces[:, (edge + 1) % 3].astype(np.uint64)
        keys[edge::3] = (np.minimum(a, b) << np.uint64(32)) | np.maximum(a, b)
    order = np.argsort(keys)
    sorted_keys = keys[order]
    paired = np.flatnonzero(sorted_keys[1:] == sorted_keys[:-1])
    # Ignore nonmanifold groups (3+ incident faces); a seam blend requires one shared edge.
    clean = np.ones(len(paired), dtype=bool)
    if len(paired) > 1:
        repeats = np.diff(paired) == 1
        clean[1:] &= ~repeats; clean[:-1] &= ~repeats
    paired = paired[clean]
    a = (order[paired] // 3).astype(np.int32)
    b = (order[paired + 1] // 3).astype(np.int32)
    shared = sorted_keys[paired]
    edges = np.column_stack([shared >> np.uint64(32), shared & np.uint64(0xffffffff)]).astype(np.uint32)
    return a, b, edges
