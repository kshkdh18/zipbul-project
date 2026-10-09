from __future__ import annotations

import json
import struct
import zipfile
from fractions import Fraction
from pathlib import Path

import av
import cv2
import numpy as np
import pytest
from PIL import Image

from zipscan_texture.atlas import Patch, pack, patch_uv, correct_frame
from zipscan_texture.geometry import Mesh, project, depth_visibility, face_adjacency
from zipscan_texture.keyframes import extract_keyframes
from zipscan_texture.pipeline import bake
from zipscan_texture.selection import Images, choose_views, apply_gain
from zipscan_texture.session import Session, extract_verified, sha256, write_json


def fixture(tmp_path):
    root = tmp_path / "session"; root.mkdir()
    width = height = 128
    k = [[90., 0, 63.5], [0, 90., 63.5], [0, 0, 1.]]
    kd = (np.diag([.125, .125, 1]) @ k).tolist()
    frames, depths = [], []
    depth_bytes, confidence_bytes = bytearray(), bytearray()
    colors = []
    for i, pts in enumerate([0, .1, .2, .3]):
        f = {"frame_id": i+1, "ar_timestamp": 100 + pts, "camera_transform": np.eye(4).tolist(), "intrinsics": k, "image_width": width, "image_height": height, "tracking_state": "normal", "display_transform": [1, 0, 0, 1.6, 0, -.3], "video_status": "queue_full" if i == 1 else "written"}
        if i != 1:
            f["video_pts"] = pts
        frames.append(f)
        depths.append({"frame_id": i+1, "ar_timestamp": 100+pts, "width": 16, "height": 16, "intrinsics": kd, "depth_offset": len(depth_bytes), "depth_length": 16*16*4, "confidence_offset": len(confidence_bytes), "confidence_length": 256})
        depth_bytes.extend(np.full((16, 16), 2, dtype="<f4").tobytes())
        confidence_bytes.extend(bytes([2])*256)
    for name, rows in [("frames.jsonl", frames), ("depth-index.jsonl", depths)]:
        (root / name).write_text("".join(json.dumps(row)+"\n" for row in rows))
    (root / "depth.bin").write_bytes(depth_bytes)
    (root / "confidence.bin").write_bytes(confidence_bytes)
    (root / "mesh.obj").write_text("v -1 -1 -2\nv 1 -1 -2\nv 1 1 -2\nv -1 1 -2\nf 1 2 3\nf 1 3 4\n")
    (root / "events.jsonl").write_text('{"type":"capture_stopped","message":"user"}\n')
    write_json(root / "validation.json", {"issues": [], "warnings": ["one dropped frame"]})
    with av.open(str(root / "video.mp4"), "w") as container:
        stream = container.add_stream("libx264", rate=10)
        stream.width = width; stream.height = height; stream.pix_fmt = "yuv420p"
        stream.codec_context.time_base = Fraction(1, 1_000_000)
        stream.options = {"preset": "ultrafast", "crf": "0", "bf": "0"}
        for index, pts in enumerate([0, .2, .3]):
            image = np.zeros((height, width, 3), np.uint8)
            image[:64, :64] = [230, 25, 25]
            image[:64, 64:] = [25, 230, 25]
            image[64:, :64] = [25, 25, 230]
            image[64:, 64:] = [230, 230, 25]
            image[2:8, 10:110] = 40 + index*50
            video = av.VideoFrame.from_ndarray(image, format="rgb24")
            video.pts = round(pts*1_000_000); video.time_base = Fraction(1, 1_000_000)
            for packet in stream.encode(video):
                container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)
    manifest = {"format_version": "1.0", "session_id": "fixture", "status": "partial", "time_origin": 100, "coordinates": "ARKit world meters", "settings": {"image_width": width, "image_height": height, "video_transform": [1, 0, 0, 1, 0, 0]}, "summary": {"duration": .4, "video_dropped": 1}, "files": [{"name": p.name, "bytes": p.stat().st_size, "sha256": sha256(p)} for p in sorted(root.iterdir())]}
    write_json(root / "manifest.json", manifest)
    archive = tmp_path / "session.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as z:
        for p in root.iterdir():
            z.write(p, p.name)
    return root, archive, manifest


def test_camera_axes_and_nonidentity_pose():
    t = np.eye(4); t[:3, 3] = [3, 4, 5]
    t[:3, :3] = [[0, 0, 1], [0, 1, 0], [-1, 0, 0]]
    camera = np.array([[0, 0, -2], [1, 1, -2], [0, 0, 2.]])
    world = camera @ t[:3, :3].T + t[:3, 3]
    uv, z = project(world, t, np.array([[100, 0, 50], [0, 100, 40], [0, 0, 1]]))
    np.testing.assert_allclose(uv[:2], [[50, 40], [100, -10]])
    np.testing.assert_allclose(z, [2, 2, -2])


def test_depth_is_optical_axis_and_occlusion_confidence_reject():
    k = np.array([[4, 0, 4], [0, 4, 4], [0, 0, 1]])
    points = np.array([[1, 0, -2], [0, 0, -3], [0, 0, 2], [100, 0, -2.]])
    depth = np.full((9, 9), 2.)
    conf = np.full((9, 9), 2, np.uint8)
    good, _, _ = depth_visibility(points, np.eye(4), k, depth, conf)
    assert good.tolist() == [True, False, False, False]
    conf[:] = 0
    assert not depth_visibility(points, np.eye(4), k, depth, conf)[0].any()
    depth[:] = np.nan; conf[:] = 2
    assert not depth_visibility(points, np.eye(4), k, depth, conf)[0].any()


def test_atlas_uv_conventions_and_packing():
    patch = Patch(0, np.array([0]), (10, 20, 70, 80))
    other = Patch(0, np.array([1]), (0, 0, 60, 60))
    sizes = pack([patch, other], size=128, gutter=8)
    assert patch.page != other.page
    frame = {"transform": np.eye(4), "k": np.array([[100, 0, 50], [0, 100, 50], [0, 0, 1]]), "image_width": 100, "image_height": 100}
    key = {"width": 100, "height": 100}
    uv = patch_uv(np.array([[0, 0, -2.]]), patch, frame, key, sizes[patch.page])
    expected = np.array([patch.x + 50-10+.5, patch.y + 50-20+.5]) / sizes[patch.page]
    np.testing.assert_allclose(uv[0], expected)
    obj = patch_uv(np.array([[0, 0, -2.]]), patch, frame, key, sizes[patch.page], obj=True)
    assert abs(obj[0, 1] + uv[0, 1] - 1) < 1e-6


def test_color_seams_are_bounded_and_reduce_difference():
    low, high = np.full((32, 32, 3), 90, np.uint8), np.full((32, 32, 3), 120, np.uint8)
    segment = np.array([[[16, 2], [16, 29]]])
    a = correct_frame(low, np.ones(3), segment, np.array([[15, 15, 15]]))
    b = correct_frame(high, np.ones(3), segment, np.array([[-15, -15, -15]]))
    assert abs(int(a[16, 16, 0]) - int(b[16, 16, 0])) < 30
    np.testing.assert_array_equal(a[16, 0], low[16, 0])
    assert np.max(np.abs(a.astype(float) - low)) <= 16
    np.testing.assert_array_equal(apply_gain(low, np.ones(3)), low)


def test_adjacency_is_shared_edges_only():
    faces = np.array([[0, 1, 2], [0, 2, 3], [4, 5, 6]], np.uint32)
    left, right, edges = face_adjacency(faces)
    assert len(left) == 1 and {int(left[0]), int(right[0])} == {0, 1}
    np.testing.assert_array_equal(edges[0], [0, 2])


def test_malicious_zip_and_checksum_mismatch_rejected(tmp_path):
    archive = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("../escape", "bad")
    with pytest.raises(ValueError, match="Unsafe"):
        extract_verified(archive, tmp_path / "out")
    root, archive, manifest = fixture(tmp_path)
    (root / "depth.bin").write_bytes(b"bad")
    with pytest.raises(ValueError, match="checksum"):
        extract_verified(root, tmp_path / "unused")


def test_real_video_pts_survive_dropped_frame(tmp_path):
    root, archive, manifest = fixture(tmp_path)
    info = extract_verified(archive, tmp_path / "unpacked")
    session = Session(**info)
    frames = extract_keyframes(session, tmp_path / "frames", .1, 128, log=lambda _: None)
    assert [f["frame_id"] for f in frames] == [1, 3, 4]
    np.testing.assert_allclose([f["video_pts"] for f in frames], [0, .2, .3], atol=2e-6)
    samples = Images(tmp_path / "frames", frames).sample(0, np.tile([40, 40.], (50_000, 1)), session.frames[1])
    assert samples.shape == (50_000, 3)


def test_occluded_faces_receive_no_texture(tmp_path):
    root, archive, manifest = fixture(tmp_path)
    session = Session(root, manifest)
    mesh = Mesh.load(root / "mesh.obj")
    frames = extract_keyframes(session, tmp_path / "frames", .1, 128, log=lambda _: None)
    # Retain camera calibration, but a foreground surface hides the mesh plane.
    (root / "depth.bin").write_bytes(np.ones(16*16*4, dtype="<f4").tobytes())
    best, *_ = choose_views(mesh, session, frames, Images(tmp_path / "frames", frames), {"max_distance": 5, "depth_tolerance": .12, "min_confidence": 1}, log=lambda _: None)
    assert (best == -1).all()


def test_end_to_end_preserves_mesh_exports_uv_and_input(tmp_path):
    root, archive, manifest = fixture(tmp_path)
    before = sha256(archive)
    output = tmp_path / "result"
    report = bake(archive, output, interval=.1, image_size=256, atlas_size=2048, log=lambda _: None)
    assert report["coverage"]["faces"] == 2
    assert report["export"]["exported_faces"] == 2
    assert report["mesh"]["geometry_changed"] is False
    assert sha256(archive) == before
    source_map = np.load(output / "face-sources.npz", allow_pickle=False)
    assert sorted(source_map["export_face_order"].tolist()) == [0, 1]
    assert set(source_map["source_frame_id"]) <= {1, 3, 4}
    raw = (output / "textured.glb").read_bytes()
    magic, version, length = struct.unpack_from("<4sII", raw)
    assert magic == b"glTF" and version == 2 and length == len(raw)
    json_size, _ = struct.unpack_from("<I4s", raw, 12)
    model = json.loads(raw[20:20+json_size])
    binary_start = 20 + json_size + 8
    def accessor(index, dtype, columns):
        spec = model["accessors"][index]; view = model["bufferViews"][spec["bufferView"]]
        return np.frombuffer(raw, dtype=dtype, count=spec["count"]*columns, offset=binary_start+view.get("byteOffset", 0)).reshape(-1, columns)
    for primitive in model["meshes"][0]["primitives"]:
        positions = accessor(primitive["attributes"]["POSITION"], "<f4", 3)
        uv = accessor(primitive["attributes"]["TEXCOORD_0"], "<f4", 2)
        indices = accessor(primitive["indices"], "<u4", 1).ravel()
        assert indices.max() < len(positions)
        assert np.isfinite(positions).all() and ((uv >= 0) & (uv <= 1)).all()
        assert np.all(positions[:, 2] == -2)
        # Top of the plane must sample the red/green (top) half, not blue/yellow.
        if primitive["material"] > 0:
            atlas = np.asarray(Image.open(output / "textures" / report["atlases"][primitive["material"]-1]["file"]))
            left_top = np.flatnonzero((positions[:, 0] == -1) & (positions[:, 1] == 1))[0]
            u, v = uv[left_top]
            pixel = atlas[min(round(v*atlas.shape[0]-.5), atlas.shape[0]-1), min(round(u*atlas.shape[1]-.5), atlas.shape[1]-1)]
            assert pixel[0] > 180 and pixel[2] < 70
    assert (output / "viewer.html").exists()
    assert (output / "vendor" / "LICENSE").exists()
