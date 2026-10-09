from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from .geometry import project, depth_visibility
from .selection import Images, apply_gain


@dataclass
class Patch:
    view: int
    face_ids: np.ndarray
    crop: tuple[int, int, int, int]
    page: int = -1
    x: int = 0
    y: int = 0

    @property
    def width(self):
        return self.crop[2] - self.crop[0]

    @property
    def height(self):
        return self.crop[3] - self.crop[1]


def make_patches(mesh, session, keyframes, images, labels, tile_size=256):
    patches = []
    face_patch = np.full(len(labels), -1, np.int32)
    order = np.argsort(labels, kind="stable")
    views, starts = np.unique(labels[order], return_index=True)
    ends = np.r_[starts[1:], len(order)]
    for view, start, end in zip(views, starts, ends):
        if view < 0:
            continue
        ids = order[start:end]
        frame = session.frames[keyframes[int(view)]["frame_id"]]
        uv, _ = project(mesh.vertices[mesh.faces[ids]], frame["transform"], frame["k"])
        uv = images.pixel_coordinates(view, uv, frame)
        center = uv.mean(axis=1)
        width, height = keyframes[view]["width"], keyframes[view]["height"]
        columns = (width + tile_size - 1) // tile_size
        tile = (center[:, 1].astype(np.int32) // tile_size) * columns + center[:, 0].astype(np.int32) // tile_size
        for cell in np.unique(tile):
            keep = tile == cell
            points = uv[keep].reshape(-1, 2)
            low = np.maximum(0, np.floor(points.min(axis=0)).astype(int) - 1)
            high = np.minimum([width, height], np.ceil(points.max(axis=0)).astype(int) + 2)
            selected = ids[keep]
            face_patch[selected] = len(patches)
            patches.append(Patch(int(view), selected, (int(low[0]), int(low[1]), int(high[0]), int(high[1]))))
    return patches, face_patch


def pack(patches: list[Patch], size=4096, gutter=8):
    """Deterministic height-sorted shelf packing; UVs include replicated gutters."""
    pages = []
    for index in sorted(range(len(patches)), key=lambda i: (-patches[i].height, -patches[i].width, i)):
        patch = patches[index]
        w, h = patch.width + gutter * 2, patch.height + gutter * 2
        if w > size or h > size:
            raise ValueError("Patch exceeds atlas size; use a larger --atlas-size")
        choices = []
        for page_id, rows in enumerate(pages):
            for row_id, row in enumerate(rows):
                if h <= row[1] and row[2] + w <= size:
                    choices.append((row[1] - h, size - row[2] - w, page_id, row_id))
        if choices:
            _, _, page_id, row_id = min(choices)
            row = pages[page_id][row_id]
        else:
            page_id = next((i for i, rows in enumerate(pages) if rows[-1][0] + rows[-1][1] + h <= size), len(pages))
            if page_id == len(pages):
                pages.append([])
            rows = pages[page_id]
            row = [rows[-1][0] + rows[-1][1] if rows else 0, h, 0]
            rows.append(row)
        patch.page = page_id; patch.x = row[2] + gutter; patch.y = row[0] + gutter
        row[2] += w
    dimensions = []
    for page_id in range(len(pages)):
        members = [p for p in patches if p.page == page_id]
        w = max(p.x + p.width + gutter for p in members)
        h = max(p.y + p.height + gutter for p in members)
        dimensions.append((min(size, 1 << (w-1).bit_length()), min(size, 1 << (h-1).bit_length())))
    return dimensions


def seam_constraints(mesh, session, keyframes, images, labels, gains, adjacency, config, log=print):
    left, right, edge_vertices = adjacency
    eligible = (labels[left] >= 0) & (labels[right] >= 0) & (labels[left] != labels[right])
    eligible &= np.abs(np.einsum("ij,ij->i", mesh.normals[left], mesh.normals[right])) > 0.98
    left, right, edge_vertices = left[eligible], right[eligible], edge_vertices[eligible]
    if not len(left):
        return {}, {"eligible_edges": 0, "mean_color_difference_before": 0.0}
    points = mesh.vertices[edge_vertices]
    centers = points.mean(axis=1)
    # Endpoints and midpoint must be visible in BOTH source images.
    test_points = np.concatenate([points, centers[:, None, :]], axis=1)
    colors = np.zeros((len(left), 2, 3), np.float32)
    valid = np.ones(len(left), bool)
    projected = np.zeros((len(left), 2, 2, 2), np.float32)
    views = np.column_stack([labels[left], labels[right]])
    for view in np.unique(views):
        frame = session.frames[keyframes[view]["frame_id"]]
        depth, confidence = session.depth_maps(keyframes[view]["frame_id"])
        kd = np.asarray(session.depths[keyframes[view]["frame_id"]]["intrinsics"])
        for side in range(2):
            ids = np.flatnonzero(views[:, side] == view)
            if not len(ids):
                continue
            visible, _, _ = depth_visibility(test_points[ids], frame["transform"], kd, depth, confidence, far=config["max_distance"], tolerance=config["depth_tolerance"], min_confidence=config["min_confidence"])
            valid[ids] &= visible.all(axis=1)
            uv, _ = project(centers[ids], frame["transform"], frame["k"])
            colors[ids, side] = images.sample(view, uv, frame, gains[view])
            edges_uv, _ = project(points[ids], frame["transform"], frame["k"])
            projected[ids, side] = images.pixel_coordinates(view, edges_uv, frame)
    constraints = {}
    target = colors.mean(axis=1)
    for view in np.unique(views):
        segments, corrections = [], []
        for side in range(2):
            ids = np.flatnonzero(valid & (views[:, side] == view))
            segments.append(projected[ids, side])
            corrections.append(np.clip(target[ids] - colors[ids, side], -16, 16))
        constraints[int(view)] = (np.concatenate(segments), np.concatenate(corrections))
    before = float(np.mean(np.abs(colors[valid, 0] - colors[valid, 1]))) if valid.any() else 0.0
    log(f"Conservative seam correction: {valid.sum():,} shared edges")
    return constraints, {"eligible_edges": int(valid.sum()), "mean_color_difference_before": before, "band_pixels": 2, "max_channel_adjustment": 16}


def correct_frame(image, gain, segments=None, corrections=None):
    image = apply_gain(image, gain)
    if segments is None or not len(segments):
        return image
    delta = np.zeros((*image.shape[:2], 3), np.float32)
    weight = np.zeros(image.shape[:2], np.float32)
    # A capped, narrow band changes seam color; it does not invent unseen surfaces.
    for line, value in zip(segments, corrections):
        a, b = np.rint(line).astype(int)
        # Direct drawing keeps work proportional to edge length, not full image size.
        cv2.line(delta, tuple(a), tuple(b), tuple(float(v) for v in value), 2, cv2.LINE_8)
        cv2.line(weight, tuple(a), tuple(b), 1.0, 2, cv2.LINE_8)
    delta = cv2.GaussianBlur(delta, (5, 5), 0.8)
    weight = cv2.GaussianBlur(weight, (5, 5), 0.8)
    # Do not divide by tiny alpha: taper the adjustment into the original image.
    return np.clip(np.rint(image.astype(np.float32) + delta * np.minimum(1, weight[..., None] * 2)), 0, 255).astype(np.uint8)


def build_atlases(patches, dimensions, images, gains, constraints, corrected_directory: Path, output: Path, gutter=8, log=print):
    corrected_directory.mkdir(parents=True, exist_ok=True)
    output.mkdir(parents=True, exist_ok=True)
    used = sorted({p.view for p in patches})
    for n, view in enumerate(used):
        segments, corrections = constraints.get(view, (None, None))
        rgb = correct_frame(images.raw(view), gains[view], segments, corrections)
        cv2.imwrite(str(corrected_directory / f"{view}.png"), cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_PNG_COMPRESSION, 1])
        if (n+1) % 40 == 0:
            log(f"Color correction {n+1}/{len(used)}")
    files = []
    for page_id, (width, height) in enumerate(dimensions):
        canvas = np.full((height, width, 3), 100, np.uint8)
        members = sorted((p for p in patches if p.page == page_id), key=lambda p: p.view)
        last_view, image = -1, None
        for patch in members:
            if patch.view != last_view:
                image = cv2.cvtColor(cv2.imread(str(corrected_directory / f"{patch.view}.png")), cv2.COLOR_BGR2RGB)
                last_view = patch.view
            x0, y0, x1, y1 = patch.crop
            tile = cv2.copyMakeBorder(image[y0:y1, x0:x1], gutter, gutter, gutter, gutter, cv2.BORDER_REPLICATE)
            canvas[patch.y-gutter:patch.y+patch.height+gutter, patch.x-gutter:patch.x+patch.width+gutter] = tile
        filename = f"atlas-{page_id:03d}.jpg"
        Image.fromarray(canvas).save(output / filename, quality=95, subsampling=0)
        files.append(filename)
        log(f"Atlas {page_id+1}/{len(dimensions)} · {width}×{height}")
    return files


def patch_uv(vertices, patch, frame, keyframe, page_size, *, obj=False):
    uv, _ = project(vertices, frame["transform"], frame["k"])
    scale = np.array([keyframe["width"] / frame["image_width"], keyframe["height"] / frame["image_height"]])
    resized = (uv + 0.5) * scale - 0.5
    pixels = resized - patch.crop[:2] + [patch.x, patch.y] + 0.5
    result = pixels / page_size
    if obj:
        result[:, 1] = 1 - result[:, 1]
    return result.astype(np.float32)
