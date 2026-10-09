from __future__ import annotations

import json
import shutil
import struct
from pathlib import Path

import numpy as np

from .atlas import patch_uv


def page_geometry(mesh, face_ids, patches, face_patch, session, keyframes, dimensions):
    patch_ids = face_patch[face_ids]
    if np.all(patch_ids < 0):
        unique, inverse = np.unique(mesh.faces[face_ids].ravel(), return_inverse=True)
        return mesh.vertices[unique], np.zeros((len(unique), 2), np.float32), inverse.astype(np.uint32), unique
    keys = (mesh.faces[face_ids].ravel().astype(np.uint64) << np.uint64(32)) | np.repeat(patch_ids, 3).astype(np.uint64)
    unique, inverse = np.unique(keys, return_inverse=True)
    source_vertices = (unique >> np.uint64(32)).astype(np.uint32)
    source_patches = (unique & np.uint64(0xffffffff)).astype(np.int32)
    uv = np.empty((len(unique), 2), np.float32)
    for patch_id in np.unique(source_patches):
        keep = source_patches == patch_id
        patch = patches[patch_id]
        keyframe = keyframes[patch.view]
        frame = session.frames[keyframe["frame_id"]]
        uv[keep] = patch_uv(mesh.vertices[source_vertices[keep]], patch, frame, keyframe, dimensions[patch.page])
    if not np.isfinite(uv).all() or uv.min(initial=0) < 0 or uv.max(initial=0) > 1:
        raise ValueError("Exported UV is outside the atlas")
    return mesh.vertices[source_vertices], uv, inverse.astype(np.uint32), source_vertices


class GLB:
    def __init__(self, binary_path: Path):
        self.path = binary_path
        self.stream = binary_path.open("wb")
        self.document = {"asset": {"version": "2.0", "generator": "Zipscan Texture 0.1.0"}, "scene": 0, "scenes": [{"nodes": [0]}], "nodes": [{"mesh": 0, "name": "Zipscan world mesh"}], "meshes": [{"name": "Zipscan", "primitives": []}], "buffers": [], "bufferViews": [], "accessors": [], "images": [], "textures": [], "samplers": [{"magFilter": 9729, "minFilter": 9729, "wrapS": 33071, "wrapT": 33071}], "materials": [], "extensionsUsed": ["KHR_materials_unlit"]}

    def add_bytes(self, data, target=None):
        offset = self.stream.tell()
        self.stream.write(data)
        length = self.stream.tell() - offset
        self.stream.write(b"\x00" * (-length % 4))
        view = {"buffer": 0, "byteOffset": offset, "byteLength": length}
        if target:
            view["target"] = target
        index = len(self.document["bufferViews"])
        self.document["bufferViews"].append(view)
        return index

    def array(self, data, component, kind, target, bounds=False):
        data = np.ascontiguousarray(data)
        view = self.add_bytes(memoryview(data).cast("B"), target)
        accessor = {"bufferView": view, "componentType": component, "count": len(data), "type": kind}
        if bounds:
            accessor["min"] = data.min(axis=0).tolist(); accessor["max"] = data.max(axis=0).tolist()
        index = len(self.document["accessors"])
        self.document["accessors"].append(accessor)
        return index

    def material(self, name, image_path=None):
        material = {"name": name, "doubleSided": True, "pbrMetallicRoughness": {"metallicFactor": 0, "roughnessFactor": 1, "baseColorFactor": [0.35, 0.38, 0.42, 1]}}
        if image_path:
            view = self.add_bytes(image_path.read_bytes())
            image = len(self.document["images"])
            self.document["images"].append({"bufferView": view, "mimeType": "image/jpeg", "name": image_path.name})
            self.document["textures"].append({"source": image, "sampler": 0})
            material["pbrMetallicRoughness"].update({"baseColorFactor": [1, 1, 1, 1], "baseColorTexture": {"index": image}})
            material["extensions"] = {"KHR_materials_unlit": {}}
        index = len(self.document["materials"])
        self.document["materials"].append(material)
        return index

    def primitive(self, positions, uv, indices, material, face_offset):
        self.document["meshes"][0]["primitives"].append({"attributes": {"POSITION": self.array(positions.astype("<f4"), 5126, "VEC3", 34962, bounds=True), "TEXCOORD_0": self.array(uv.astype("<f4"), 5126, "VEC2", 34962)}, "indices": self.array(indices.astype("<u4"), 5125, "SCALAR", 34963), "material": material, "mode": 4, "extras": {"originalFaceMapOffset": face_offset}})

    def finish(self, path: Path):
        size = self.stream.tell(); self.stream.close()
        self.document["buffers"] = [{"byteLength": size}]
        data = json.dumps(self.document, separators=(",", ":"), allow_nan=False).encode()
        data += b" " * (-len(data) % 4)
        total = 12 + 8 + len(data) + 8 + size
        if total >= 2**32:
            raise ValueError("GLB exceeds the 4 GB format limit")
        temporary = path.with_suffix(".glb.part")
        with temporary.open("wb") as out, self.path.open("rb") as binary:
            out.write(struct.pack("<4sII", b"glTF", 2, total))
            out.write(struct.pack("<I4s", len(data), b"JSON")); out.write(data)
            out.write(struct.pack("<I4s", size, b"BIN\x00"))
            shutil.copyfileobj(binary, out, 4 * 1024 * 1024)
        temporary.replace(path)
        self.path.unlink()


def export_models(mesh, session, keyframes, labels, patches, face_patch, dimensions, atlas_files, output, log=print):
    pages = np.full(len(mesh.faces), -1, np.int32)
    if patches:
        patch_pages = np.array([p.page for p in patches], np.int32)
        textured = face_patch >= 0
        pages[textured] = patch_pages[face_patch[textured]]
    glb = GLB(output / ".work" / "model.bin")
    glb.material("unobserved")
    for index, filename in enumerate(atlas_files):
        glb.material(f"atlas_{index:03d}", output / "textures" / filename)
    with (output / "textured.mtl").open("w") as mtl:
        mtl.write("newmtl unobserved\nKd 0.35 0.38 0.42\nillum 1\n\n")
        for index, filename in enumerate(atlas_files):
            mtl.write(f"newmtl atlas_{index:03d}\nKa 1 1 1\nKd 1 1 1\nKs 0 0 0\nillum 1\nmap_Kd textures/{filename}\n\n")
    face_order = []
    uv_offset, triangle_offset = 1, 0
    with (output / "textured.obj").open("w", buffering=1_048_576) as obj:
        obj.write("# Zipscan texture; original ARKit world coordinates, meters, +Y up\nmtllib textured.mtl\n")
        for start in range(0, len(mesh.vertices), 20_000):
            obj.writelines(f"v {x:.9g} {y:.9g} {z:.9g}\n" for x, y, z in mesh.vertices[start:start+20_000])
        for page in sorted(np.unique(pages)):
            face_ids = np.flatnonzero(pages == page).astype(np.uint32)
            positions, uv, indices, source_vertices = page_geometry(mesh, face_ids, patches, face_patch, session, keyframes, dimensions)
            glb.primitive(positions, uv, indices, int(page)+1, triangle_offset)
            for start in range(0, len(uv), 20_000):
                obj.writelines(f"vt {u:.9g} {1-v:.9g}\n" for u, v in uv[start:start+20_000])
            obj.write("usemtl " + ("unobserved" if page < 0 else f"atlas_{page:03d}") + "\n")
            original = mesh.faces[face_ids] + 1
            uv_faces = indices.reshape(-1, 3) + uv_offset
            for start in range(0, len(face_ids), 20_000):
                obj.writelines(f"f {v[0]}/{t[0]} {v[1]}/{t[1]} {v[2]}/{t[2]}\n" for v, t in zip(original[start:start+20_000], uv_faces[start:start+20_000]))
            uv_offset += len(uv); triangle_offset += len(face_ids); face_order.append(face_ids)
            log(f"Exported {'gray fallback' if page < 0 else 'atlas '+str(page)}: {len(face_ids):,} triangles")
    glb.finish(output / "textured.glb")
    source_ids = np.full(len(labels), -1, np.int32)
    valid = labels >= 0
    source_ids[valid] = np.array([f["frame_id"] for f in keyframes], np.int32)[labels[valid]]
    np.savez_compressed(output / "face-sources.npz", source_frame_id=source_ids, face_patch=face_patch, export_face_order=np.concatenate(face_order))
    return {"exported_faces": triangle_offset, "exported_uv_vertices": uv_offset - 1, "glb_bytes": (output / "textured.glb").stat().st_size}
