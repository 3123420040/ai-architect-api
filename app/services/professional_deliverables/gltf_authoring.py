from __future__ import annotations

import json
import math
import struct
from pathlib import Path

from app.services.professional_deliverables.scene_contract import BoxMeshElement, SceneContract, TEXTURE_SLOTS, TextureSlot
from app.services.professional_deliverables.texture_authoring import AuthoredTexture

ARRAY_BUFFER = 34962
ELEMENT_ARRAY_BUFFER = 34963
FLOAT = 5126
UNSIGNED_SHORT = 5123


class GLTFAuthoringError(RuntimeError):
    pass


def _align4(data: bytearray) -> None:
    while len(data) % 4:
        data.append(0)


def _append_view(buffer: bytearray, payload: bytes, *, target: int | None = None) -> dict:
    _align4(buffer)
    offset = len(buffer)
    buffer.extend(payload)
    view = {"buffer": 0, "byteOffset": offset, "byteLength": len(payload)}
    if target is not None:
        view["target"] = target
    return view


def _pack_floats(values: list[float]) -> bytes:
    return struct.pack("<" + "f" * len(values), *values)


def _pack_ushort(values: list[int]) -> bytes:
    return struct.pack("<" + "H" * len(values), *values)


def _rotate(point: tuple[float, float], degrees: float) -> tuple[float, float]:
    angle = math.radians(degrees)
    c = math.cos(angle)
    s = math.sin(angle)
    return (point[0] * c - point[1] * s, point[0] * s + point[1] * c)


def _box_geometry(element: BoxMeshElement) -> tuple[list[float], list[float], list[float], list[float], list[int]]:
    sx, sy, sz = element.size_m
    cx, cy, cz = element.center_m
    hx, hy, hz = sx / 2.0, sy / 2.0, sz / 2.0
    faces = [
        (((hx, -hy, -hz), (hx, hy, -hz), (hx, hy, hz), (hx, -hy, hz)), (1.0, 0.0, 0.0)),
        (((-hx, hy, -hz), (-hx, -hy, -hz), (-hx, -hy, hz), (-hx, hy, hz)), (-1.0, 0.0, 0.0)),
        (((-hx, hy, -hz), (hx, hy, -hz), (hx, hy, hz), (-hx, hy, hz)), (0.0, 1.0, 0.0)),
        (((hx, -hy, -hz), (-hx, -hy, -hz), (-hx, -hy, hz), (hx, -hy, hz)), (0.0, -1.0, 0.0)),
        (((-hx, -hy, hz), (hx, -hy, hz), (hx, hy, hz), (-hx, hy, hz)), (0.0, 0.0, 1.0)),
        (((-hx, hy, -hz), (hx, hy, -hz), (hx, -hy, -hz), (-hx, -hy, -hz)), (0.0, 0.0, -1.0)),
    ]
    uvs = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
    positions: list[float] = []
    normals: list[float] = []
    texcoords: list[float] = []
    tangents: list[float] = []
    indices: list[int] = []
    for face_index, (corners, normal) in enumerate(faces):
        base = face_index * 4
        nx, ny = _rotate((normal[0], normal[1]), element.rotation_z_degrees)
        edge_u = (
            corners[1][0] - corners[0][0],
            corners[1][1] - corners[0][1],
            corners[1][2] - corners[0][2],
        )
        tx, ty = _rotate((edge_u[0], edge_u[1]), element.rotation_z_degrees)
        tz = edge_u[2]
        tangent_length = math.sqrt(tx * tx + ty * ty + tz * tz) or 1.0
        for corner, uv in zip(corners, uvs):
            rx, ry = _rotate((corner[0], corner[1]), element.rotation_z_degrees)
            positions.extend([cx + rx, cy + ry, cz + corner[2]])
            normals.extend([nx, ny, normal[2]])
            texcoords.extend([uv[0], uv[1]])
            tangents.extend([tx / tangent_length, ty / tangent_length, tz / tangent_length, 1.0])
        indices.extend([base, base + 1, base + 2, base, base + 2, base + 3])
    return positions, normals, texcoords, tangents, indices


def _vec_min_max(values: list[float], width: int) -> tuple[list[float], list[float]]:
    rows = [values[index : index + width] for index in range(0, len(values), width)]
    return (
        [min(row[i] for row in rows) for i in range(width)],
        [max(row[i] for row in rows) for i in range(width)],
    )


def _relative_uri(path: Path, base: Path) -> str:
    return path.relative_to(base).as_posix()


def write_source_gltf(
    scene: SceneContract,
    authored_textures: dict[str, dict[TextureSlot, AuthoredTexture]],
    output_dir: Path,
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    buffer = bytearray()
    buffer_views: list[dict] = []
    accessors: list[dict] = []
    meshes: list[dict] = []
    nodes: list[dict] = []

    images: list[dict] = []
    textures: list[dict] = []
    materials: list[dict] = []
    texture_indices: dict[tuple[str, TextureSlot], int] = {}

    for material in scene.materials:
        for slot in TEXTURE_SLOTS:
            image_index = len(images)
            source_path = authored_textures[material.name][slot].source_path
            images.append(
                {
                    "name": material.texture_stem(slot),
                    "uri": _relative_uri(source_path, output_dir),
                    "mimeType": "image/png",
                }
            )
            texture_index = len(textures)
            textures.append({"source": image_index, "sampler": 0, "name": material.texture_stem(slot)})
            texture_indices[(material.name, slot)] = texture_index

        material_payload = {
            "name": material.name,
            "pbrMetallicRoughness": {
                "baseColorTexture": {"index": texture_indices[(material.name, "baseColor")], "texCoord": 0},
                "metallicRoughnessTexture": {
                    "index": texture_indices[(material.name, "metallicRoughness")],
                    "texCoord": 0,
                },
                "baseColorFactor": [1.0, 1.0, 1.0, material.channels.base_color_rgba[3] / 255.0],
                "metallicFactor": 1.0,
                "roughnessFactor": 1.0,
            },
            "normalTexture": {"index": texture_indices[(material.name, "normal")], "texCoord": 0},
            "occlusionTexture": {"index": texture_indices[(material.name, "ao")], "texCoord": 0, "strength": 1.0},
            "emissiveTexture": {"index": texture_indices[(material.name, "emissive")], "texCoord": 0},
            "emissiveFactor": [1.0, 1.0, 1.0],
            "extras": {
                "workflow": material.workflow,
                "resolution": material.resolution_label,
                "texture_codec": material.texture_codec,
                "tier": material.tier,
            },
        }
        if material.channels.base_color_rgba[3] < 255:
            material_payload["alphaMode"] = "BLEND"
        materials.append(material_payload)

    material_index = {material.name: index for index, material in enumerate(scene.materials)}
    for element in scene.elements:
        positions, normals, texcoords, tangents, indices = _box_geometry(element)
        pos_view_index = len(buffer_views)
        buffer_views.append(_append_view(buffer, _pack_floats(positions), target=ARRAY_BUFFER))
        normal_view_index = len(buffer_views)
        buffer_views.append(_append_view(buffer, _pack_floats(normals), target=ARRAY_BUFFER))
        uv_view_index = len(buffer_views)
        buffer_views.append(_append_view(buffer, _pack_floats(texcoords), target=ARRAY_BUFFER))
        tangent_view_index = len(buffer_views)
        buffer_views.append(_append_view(buffer, _pack_floats(tangents), target=ARRAY_BUFFER))
        index_view_index = len(buffer_views)
        buffer_views.append(_append_view(buffer, _pack_ushort(indices), target=ELEMENT_ARRAY_BUFFER))

        pos_min, pos_max = _vec_min_max(positions, 3)
        pos_accessor = len(accessors)
        accessors.append(
            {
                "bufferView": pos_view_index,
                "componentType": FLOAT,
                "count": len(positions) // 3,
                "type": "VEC3",
                "min": pos_min,
                "max": pos_max,
            }
        )
        normal_accessor = len(accessors)
        accessors.append(
            {
                "bufferView": normal_view_index,
                "componentType": FLOAT,
                "count": len(normals) // 3,
                "type": "VEC3",
            }
        )
        uv_accessor = len(accessors)
        accessors.append(
            {
                "bufferView": uv_view_index,
                "componentType": FLOAT,
                "count": len(texcoords) // 2,
                "type": "VEC2",
                "min": [0.0, 0.0],
                "max": [1.0, 1.0],
            }
        )
        tangent_accessor = len(accessors)
        accessors.append(
            {
                "bufferView": tangent_view_index,
                "componentType": FLOAT,
                "count": len(tangents) // 4,
                "type": "VEC4",
            }
        )
        index_accessor = len(accessors)
        accessors.append(
            {
                "bufferView": index_view_index,
                "componentType": UNSIGNED_SHORT,
                "count": len(indices),
                "type": "SCALAR",
            }
        )
        mesh_index = len(meshes)
        meshes.append(
            {
                "name": element.name,
                "primitives": [
                    {
                        "attributes": {
                            "POSITION": pos_accessor,
                            "NORMAL": normal_accessor,
                            "TEXCOORD_0": uv_accessor,
                            "TANGENT": tangent_accessor,
                        },
                        "indices": index_accessor,
                        "material": material_index[element.material_name],
                    }
                ],
            }
        )
        nodes.append(
            {
                "name": element.name,
                "mesh": mesh_index,
                "extras": {
                    "id": element.id,
                    "category": element.category,
                    "lod": element.lod,
                    "material": element.material_name,
                },
            }
        )

    _align4(buffer)
    bin_path = output_dir / "scene.bin"
    bin_path.write_bytes(bytes(buffer))
    payload = {
        "asset": {"version": "2.0", "generator": "AI Architect Sprint 2 deterministic glTF authoring"},
        "scene": 0,
        "scenes": [{"name": scene.project_name, "nodes": list(range(len(nodes)))}],
        "nodes": nodes,
        "meshes": meshes,
        "materials": materials,
        "samplers": [{"magFilter": 9729, "minFilter": 9987, "wrapS": 10497, "wrapT": 10497}],
        "textures": textures,
        "images": images,
        "buffers": [{"uri": bin_path.name, "byteLength": len(buffer)}],
        "bufferViews": buffer_views,
        "accessors": accessors,
        "extras": {
            "project_id": scene.project_id,
            "lod_summary": scene.lod_summary,
            "sprint2_metadata_stub": True,
        },
    }
    gltf_path = output_dir / "scene.gltf"
    gltf_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return gltf_path


def _material_payload(material, texture_indices: dict[tuple[str, TextureSlot], int]) -> dict:
    payload = {
        "name": material.name,
        "pbrMetallicRoughness": {
            "baseColorTexture": {"index": texture_indices[(material.name, "baseColor")], "texCoord": 0},
            "metallicRoughnessTexture": {
                "index": texture_indices[(material.name, "metallicRoughness")],
                "texCoord": 0,
            },
            "baseColorFactor": [1.0, 1.0, 1.0, material.channels.base_color_rgba[3] / 255.0],
            "metallicFactor": 1.0,
            "roughnessFactor": 1.0,
        },
        "normalTexture": {"index": texture_indices[(material.name, "normal")], "texCoord": 0},
        "occlusionTexture": {"index": texture_indices[(material.name, "ao")], "texCoord": 0, "strength": 1.0},
        "emissiveTexture": {"index": texture_indices[(material.name, "emissive")], "texCoord": 0},
        "emissiveFactor": [1.0, 1.0, 1.0],
        "extras": {
            "workflow": material.workflow,
            "resolution": material.resolution_label,
            "texture_codec": material.texture_codec,
            "tier": material.tier,
        },
    }
    if material.channels.base_color_rgba[3] < 255:
        payload["alphaMode"] = "BLEND"
    return payload


def _append_scene_geometry(
    scene: SceneContract,
    buffer: bytearray,
    buffer_views: list[dict],
    accessors: list[dict],
    meshes: list[dict],
    nodes: list[dict],
) -> None:
    material_index = {material.name: index for index, material in enumerate(scene.materials)}
    for element in scene.elements:
        positions, normals, texcoords, tangents, indices = _box_geometry(element)
        pos_view_index = len(buffer_views)
        buffer_views.append(_append_view(buffer, _pack_floats(positions), target=ARRAY_BUFFER))
        normal_view_index = len(buffer_views)
        buffer_views.append(_append_view(buffer, _pack_floats(normals), target=ARRAY_BUFFER))
        uv_view_index = len(buffer_views)
        buffer_views.append(_append_view(buffer, _pack_floats(texcoords), target=ARRAY_BUFFER))
        tangent_view_index = len(buffer_views)
        buffer_views.append(_append_view(buffer, _pack_floats(tangents), target=ARRAY_BUFFER))
        index_view_index = len(buffer_views)
        buffer_views.append(_append_view(buffer, _pack_ushort(indices), target=ELEMENT_ARRAY_BUFFER))

        pos_min, pos_max = _vec_min_max(positions, 3)
        pos_accessor = len(accessors)
        accessors.append(
            {
                "bufferView": pos_view_index,
                "componentType": FLOAT,
                "count": len(positions) // 3,
                "type": "VEC3",
                "min": pos_min,
                "max": pos_max,
            }
        )
        normal_accessor = len(accessors)
        accessors.append(
            {
                "bufferView": normal_view_index,
                "componentType": FLOAT,
                "count": len(normals) // 3,
                "type": "VEC3",
            }
        )
        uv_accessor = len(accessors)
        accessors.append(
            {
                "bufferView": uv_view_index,
                "componentType": FLOAT,
                "count": len(texcoords) // 2,
                "type": "VEC2",
                "min": [0.0, 0.0],
                "max": [1.0, 1.0],
            }
        )
        tangent_accessor = len(accessors)
        accessors.append(
            {
                "bufferView": tangent_view_index,
                "componentType": FLOAT,
                "count": len(tangents) // 4,
                "type": "VEC4",
            }
        )
        index_accessor = len(accessors)
        accessors.append(
            {
                "bufferView": index_view_index,
                "componentType": UNSIGNED_SHORT,
                "count": len(indices),
                "type": "SCALAR",
            }
        )
        mesh_index = len(meshes)
        meshes.append(
            {
                "name": element.name,
                "primitives": [
                    {
                        "attributes": {
                            "POSITION": pos_accessor,
                            "NORMAL": normal_accessor,
                            "TEXCOORD_0": uv_accessor,
                            "TANGENT": tangent_accessor,
                        },
                        "indices": index_accessor,
                        "material": material_index[element.material_name],
                    }
                ],
            }
        )
        nodes.append(
            {
                "name": element.name,
                "mesh": mesh_index,
                "extras": {
                    "id": element.id,
                    "category": element.category,
                    "lod": element.lod,
                    "material": element.material_name,
                },
            }
        )


def _write_glb(path: Path, payload: dict, buffer: bytearray) -> None:
    _align4(buffer)
    json_bytes = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    json_padding = (4 - len(json_bytes) % 4) % 4
    json_chunk = json_bytes + (b" " * json_padding)
    bin_chunk = bytes(buffer)
    total_length = 12 + 8 + len(json_chunk) + 8 + len(bin_chunk)
    output = bytearray()
    output.extend(b"glTF")
    output.extend(struct.pack("<II", 2, total_length))
    output.extend(struct.pack("<I4s", len(json_chunk), b"JSON"))
    output.extend(json_chunk)
    output.extend(struct.pack("<I4s", len(bin_chunk), b"BIN\x00"))
    output.extend(bin_chunk)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(bytes(output))


def write_ktx_glb(scene: SceneContract, textures_dir: Path, output_glb: Path) -> Path:
    buffer = bytearray()
    buffer_views: list[dict] = []
    accessors: list[dict] = []
    meshes: list[dict] = []
    nodes: list[dict] = []
    images: list[dict] = []
    textures: list[dict] = []
    materials: list[dict] = []
    texture_indices: dict[tuple[str, TextureSlot], int] = {}

    for material in scene.materials:
        for slot in TEXTURE_SLOTS:
            ktx_path = textures_dir / material.texture_filename(slot, extension="ktx2")
            if not ktx_path.exists():
                raise GLTFAuthoringError(f"Missing KTX2 texture for GLB embedding: {ktx_path}")
            view_index = len(buffer_views)
            buffer_views.append(_append_view(buffer, ktx_path.read_bytes()))
            image_index = len(images)
            images.append(
                {
                    "name": material.texture_stem(slot),
                    "mimeType": "image/ktx2",
                    "bufferView": view_index,
                }
            )
            texture_index = len(textures)
            textures.append(
                {
                    "sampler": 0,
                    "name": material.texture_stem(slot),
                    "extensions": {"KHR_texture_basisu": {"source": image_index}},
                }
            )
            texture_indices[(material.name, slot)] = texture_index
        materials.append(_material_payload(material, texture_indices))

    _append_scene_geometry(scene, buffer, buffer_views, accessors, meshes, nodes)
    _align4(buffer)
    payload = {
        "asset": {"version": "2.0", "generator": "AI Architect Sprint 2 KTX2 GLB authoring"},
        "scene": 0,
        "scenes": [{"name": scene.project_name, "nodes": list(range(len(nodes)))}],
        "nodes": nodes,
        "meshes": meshes,
        "materials": materials,
        "samplers": [{"magFilter": 9729, "minFilter": 9987, "wrapS": 10497, "wrapT": 10497}],
        "textures": textures,
        "images": images,
        "buffers": [{"byteLength": len(buffer)}],
        "bufferViews": buffer_views,
        "accessors": accessors,
        "extensionsUsed": ["KHR_texture_basisu"],
        "extensionsRequired": ["KHR_texture_basisu"],
        "extras": {
            "project_id": scene.project_id,
            "lod_summary": scene.lod_summary,
            "sprint2_metadata_stub": True,
        },
    }
    _write_glb(output_glb, payload, buffer)
    return output_glb


def write_geometry_glb(scene: SceneContract, output_glb: Path) -> Path:
    buffer = bytearray()
    buffer_views: list[dict] = []
    accessors: list[dict] = []
    meshes: list[dict] = []
    nodes: list[dict] = []
    _append_scene_geometry(scene, buffer, buffer_views, accessors, meshes, nodes)
    _align4(buffer)
    materials = [
        {
            "name": material.name,
            "pbrMetallicRoughness": {
                "baseColorFactor": [
                    material.channels.base_color_rgba[0] / 255.0,
                    material.channels.base_color_rgba[1] / 255.0,
                    material.channels.base_color_rgba[2] / 255.0,
                    material.channels.base_color_rgba[3] / 255.0,
                ],
                "metallicFactor": material.channels.metallic / 255.0,
                "roughnessFactor": material.channels.roughness / 255.0,
            },
            "extras": {
                "workflow": material.workflow,
                "resolution": material.resolution_label,
                "texture_codec": material.texture_codec,
                "tier": material.tier,
            },
        }
        for material in scene.materials
    ]
    payload = {
        "asset": {"version": "2.0", "generator": "AI Architect Sprint 2 geometry GLB authoring"},
        "scene": 0,
        "scenes": [{"name": scene.project_name, "nodes": list(range(len(nodes)))}],
        "nodes": nodes,
        "meshes": meshes,
        "materials": materials,
        "buffers": [{"byteLength": len(buffer)}],
        "bufferViews": buffer_views,
        "accessors": accessors,
        "extras": {
            "project_id": scene.project_id,
            "lod_summary": scene.lod_summary,
            "sprint2_metadata_stub": True,
        },
    }
    _write_glb(output_glb, payload, buffer)
    return output_glb


def _read_glb(path: Path) -> tuple[dict, bytes]:
    data = path.read_bytes()
    if len(data) < 20 or data[:4] != b"glTF":
        raise GLTFAuthoringError(f"{path} is not a GLB file")
    version, total_length = struct.unpack("<II", data[4:12])
    if version != 2 or total_length != len(data):
        raise GLTFAuthoringError(f"{path} has invalid GLB header")
    offset = 12
    payload: dict | None = None
    bin_chunk = b""
    while offset < len(data):
        chunk_length, chunk_type = struct.unpack("<I4s", data[offset : offset + 8])
        offset += 8
        chunk = data[offset : offset + chunk_length]
        offset += chunk_length
        if chunk_type == b"JSON":
            payload = json.loads(chunk.rstrip(b" \x00").decode("utf-8"))
        elif chunk_type == b"BIN\x00":
            bin_chunk = chunk
    if payload is None:
        raise GLTFAuthoringError(f"{path} has no JSON chunk")
    return payload, bin_chunk


def embed_ktx_textures_in_glb(source_glb: Path, scene: SceneContract, textures_dir: Path, output_glb: Path) -> Path:
    payload, bin_chunk = _read_glb(source_glb)
    buffer = bytearray(bin_chunk)
    images: list[dict] = []
    textures: list[dict] = []
    texture_indices: dict[tuple[str, TextureSlot], int] = {}

    for material in scene.materials:
        for slot in TEXTURE_SLOTS:
            ktx_path = textures_dir / material.texture_filename(slot, extension="ktx2")
            if not ktx_path.exists():
                raise GLTFAuthoringError(f"Missing KTX2 texture for GLB embedding: {ktx_path}")
            image_index = len(images)
            images.append(
                {
                    "name": material.texture_stem(slot),
                    "uri": f"../textures/{ktx_path.name}",
                }
            )
            texture_index = len(textures)
            textures.append(
                {
                    "sampler": 0,
                    "name": material.texture_stem(slot),
                    "extensions": {"KHR_texture_basisu": {"source": image_index}},
                }
            )
            texture_indices[(material.name, slot)] = texture_index

    materials_by_name = scene.material_by_name
    for material_payload in payload.get("materials", []):
        material = materials_by_name.get(material_payload.get("name"))
        if material is None:
            continue
        material_payload.update(_material_payload(material, texture_indices))

    payload["images"] = images
    payload["textures"] = textures
    payload["samplers"] = [{"magFilter": 9729, "minFilter": 9987, "wrapS": 10497, "wrapT": 10497}]
    extensions_used = set(payload.get("extensionsUsed", []))
    extensions_used.add("KHR_texture_basisu")
    payload["extensionsUsed"] = sorted(extensions_used)
    extensions_required = set(payload.get("extensionsRequired", []))
    extensions_required.add("KHR_texture_basisu")
    payload["extensionsRequired"] = sorted(extensions_required)
    _align4(buffer)
    payload["buffers"] = [{"byteLength": len(buffer)}]
    _write_glb(output_glb, payload, buffer)
    return output_glb


def read_glb_json(path: Path) -> dict:
    payload, _ = _read_glb(path)
    return payload
