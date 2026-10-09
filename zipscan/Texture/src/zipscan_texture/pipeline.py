from __future__ import annotations

import fcntl
import json
import shutil
import time
from pathlib import Path

import cv2
import numpy as np

from .atlas import make_patches, pack, seam_constraints, build_atlases
from .export import export_models
from .geometry import Mesh, face_adjacency
from .keyframes import extract_keyframes
from .selection import Images, choose_views, smooth_labels
from .session import Session, extract_verified, read_json, write_json, sha256


def selection_fingerprint(manifest, keyframes, config):
    return {"algorithm": 1, "payloads": {f["name"]: f["sha256"] for f in manifest["files"] if f["name"] in {"mesh.obj", "video.mp4", "depth.bin", "confidence.bin", "frames.jsonl", "depth-index.jsonl"}}, "keyframes": [[f["frame_id"], f["width"], f["height"], f["sharpness"]] for f in keyframes], "config": config}


def bake(source: Path, output: Path, *, interval=0.75, image_size=1920, atlas_size=4096, max_distance=5.0, depth_tolerance=0.12, min_confidence=1, log=print):
    source, output = source.resolve(), output.resolve()
    if not source.exists():
        raise ValueError("Input does not exist")
    if source == output or output in source.parents or (source.is_dir() and source in output.parents):
        raise ValueError("Output must be separate from the input session")
    if not 0.1 <= interval <= 10 or not 256 <= image_size <= 4096 or atlas_size not in {2048, 4096, 8192} or not 0.5 <= max_distance <= 10 or not 0.01 <= depth_tolerance <= 0.5 or min_confidence not in {1, 2}:
        raise ValueError("Invalid texture settings")
    output.mkdir(parents=True, exist_ok=True)
    owner = output / ".zipscan-texture.json"
    if not owner.exists() and set(p.name for p in output.iterdir()) - {".work"}:
        raise ValueError("Output is not an empty/managed Zipscan texture directory")
    with (output / ".zipscan-texture.lock").open("a+") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ValueError("Another bake is using this output") from error
        started = time.monotonic()
        work = output / ".work"; work.mkdir(exist_ok=True)
        source_digest = sha256(source / "manifest.json" if source.is_dir() else source)
        if owner.exists() and read_json(owner)["input_sha256"] != source_digest:
            raise ValueError("This output belongs to another input; choose a different directory")
        write_json(owner, {"input_sha256": source_digest, "input": str(source), "state": "running"})
        cv2.setNumThreads(2)
        log("Verifying source payloads and frame/depth associations...")
        info = extract_verified(source, work / "source")
        session = Session(**info)
        mesh = Mesh.load(session.root / "mesh.obj")
        log(f"Input: {len(mesh.faces):,} triangles, {len(session.frames):,} frame records")
        keyframes = extract_keyframes(session, work / "keyframes", interval, image_size, log)
        images = Images(work / "keyframes", keyframes)
        config = {"max_distance": max_distance, "depth_tolerance": depth_tolerance, "min_confidence": min_confidence}
        fingerprint = selection_fingerprint(session.manifest, keyframes, config)
        selection_file, selection_info = work / "selection.npz", work / "selection-info.json"
        if selection_file.exists() and selection_info.exists() and read_json(selection_info).get("fingerprint") == fingerprint:
            log("Reusing verified view-selection cache")
            saved = np.load(selection_file, allow_pickle=False)
            labels, gains = saved["labels"], saved["gains"]
            adjacency = (saved["adj_left"], saved["adj_right"], saved["adj_edges"])
            meta = read_json(selection_info)
            stats, changed = meta["stats"], meta["smoothed_faces"]
        else:
            best, second, scores, second_scores, gains, stats = choose_views(mesh, session, keyframes, images, config, log)
            log("Building shared-edge neighborhoods...")
            adjacency = face_adjacency(mesh.faces)
            labels, changed = smooth_labels(best, second, scores, second_scores, adjacency, mesh.normals)
            np.savez_compressed(selection_file, labels=labels, gains=gains, adj_left=adjacency[0], adj_right=adjacency[1], adj_edges=adjacency[2])
            write_json(selection_info, {"fingerprint": fingerprint, "stats": stats, "smoothed_faces": changed})
        log("Packing projected image patches...")
        patches, face_patch = make_patches(mesh, session, keyframes, images, labels)
        dimensions = pack(patches, size=atlas_size)
        log(f"{len(patches):,} cropped patches in {len(dimensions)} atlases")
        constraints, seam_stats = seam_constraints(mesh, session, keyframes, images, labels, gains, adjacency, config, log)
        atlas_files = build_atlases(patches, dimensions, images, gains, constraints, work / "corrected", output / "textures", log=log)
        exported = export_models(mesh, session, keyframes, labels, patches, face_patch, dimensions, atlas_files, output, log)
        if exported["exported_faces"] != len(mesh.faces):
            raise ValueError("Export changed the input triangle count")
        source_frames = []
        for index, keyframe in enumerate(keyframes):
            frame = session.frames[keyframe["frame_id"]]
            source_frames.append({"frame_id": frame["frame_id"], "video_pts": frame["video_pts"], "camera_transform": frame["camera_transform"], "intrinsics": frame["intrinsics"], "image_width": frame["image_width"], "image_height": frame["image_height"], "sharpness": keyframe["sharpness"], "linear_rgb_gain": gains[index].tolist()})
        write_json(output / "source-frames.json", source_frames)
        static = Path(__file__).parent / "static"
        for name in ["viewer.html", "viewer.js", "favicon.svg"]:
            shutil.copyfile(static / name, output / name)
        shutil.copytree(static / "vendor", output / "vendor", dirs_exist_ok=True)
        covered = labels >= 0
        files = ["textured.glb", "textured.obj", "textured.mtl", "face-sources.npz", "source-frames.json"] + ["textures/"+f for f in atlas_files]
        report = {
            "format_version": "zipscan-texture-0.1", "session_id": session.manifest["session_id"], "input_sha256": source_digest,
            "input_status": session.manifest["status"], "input_duration_seconds": session.manifest["summary"]["duration"], "input_video_dropped": session.manifest["summary"]["video_dropped"],
            "mesh": {"vertices": len(mesh.vertices), "faces": len(mesh.faces), "geometry_changed": False, "coordinates": session.manifest["coordinates"]},
            "coverage": {"faces": int(covered.sum()), "face_fraction": float(covered.mean()), "area_fraction": float(mesh.areas[covered].sum() / max(mesh.areas.sum(), 1e-12)), "unobserved_faces": int((~covered).sum())},
            "keyframes": {"selected": len(keyframes), "used": len(np.unique(labels[covered])), "interval_seconds": interval, "max_image_dimension": image_size},
            "settings": {**config, "relative_depth_tolerance": 0.02, "near_distance": 0.2, "min_absolute_incidence_cosine": 0.15, "atlas_size": atlas_size, "gutter": 8, "patch_tile": 256},
            "atlases": [{"file": filename, "width": wh[0], "height": wh[1]} for filename, wh in zip(atlas_files, dimensions)],
            "selection": {**stats, "smoothed_faces": changed}, "seams": seam_stats,
            "camera_height_median": float(np.median([f["camera_transform"][1][3] for f in source_frames])),
            "export": exported, "files": [{"name": f, "bytes": (output / f).stat().st_size, "sha256": sha256(output / f)} for f in files],
            "run_wall_seconds": time.monotonic()-started,
            "limitations": ["Gray faces have no depth-consistent selected view; they are not filled.", "Mesh holes, moving objects and historical AR pose drift are not repaired.", "Exposure and narrow seam correction are conservative approximations, not photogrammetric bundle adjustment.", "Area coverage describes accepted projections under the recorded thresholds, not a ground-truth accuracy score."]
        }
        write_json(output / "report.json", report)
        write_json(owner, {"input_sha256": source_digest, "input": str(source), "state": "finished"})
        log(f"Finished: {report['coverage']['area_fraction']:.1%} of mesh area textured; GLB {exported['glb_bytes']/1048576:.1f} MiB")
        return report
