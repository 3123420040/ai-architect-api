from __future__ import annotations

import json

from app.services.professional_deliverables.gltf_authoring import read_glb_json, write_ktx_glb, write_source_gltf
from app.services.professional_deliverables.golden_fixture import build_golden_townhouse
from app.services.professional_deliverables.scene_builder import build_scene_from_project
from app.services.professional_deliverables.scene_contract import TEXTURE_SLOTS
from app.services.professional_deliverables.texture_authoring import AuthoredTexture, material_slot_color


def test_source_gltf_uses_metal_rough_materials_and_lod_extras(tmp_path) -> None:
    scene = build_scene_from_project(build_golden_townhouse())
    authored = {}
    source_dir = tmp_path / "source-textures"
    source_dir.mkdir()
    for material in scene.materials:
        authored[material.name] = {}
        for slot in TEXTURE_SLOTS:
            path = source_dir / material.texture_filename(slot, extension="png")
            path.write_bytes(b"placeholder")
            authored[material.name][slot] = AuthoredTexture(
                material_name=material.name,
                slot=slot,
                source_path=path,
                resolution_px=material.resolution_px,
                expected_sample_rgba=material_slot_color(material, slot),
            )

    gltf_path = write_source_gltf(scene, authored, tmp_path)
    payload = json.loads(gltf_path.read_text(encoding="utf-8"))

    assert "KHR_materials_pbrSpecularGlossiness" not in json.dumps(payload)
    assert all("pbrMetallicRoughness" in material for material in payload["materials"])
    assert all("lod" in node["extras"] for node in payload["nodes"])
    assert payload["extras"]["lod_summary"] == scene.lod_summary
    assert all("TANGENT" in mesh["primitives"][0]["attributes"] for mesh in payload["meshes"])
    uv_accessors = [
        accessor
        for accessor in payload["accessors"]
        if accessor.get("type") == "VEC2" and accessor.get("min") == [0.0, 0.0]
    ]
    assert uv_accessors
    assert all(accessor["max"] == [1.0, 1.0] for accessor in uv_accessors)


def test_ktx_glb_embeds_basisu_textures_without_spec_gloss(tmp_path) -> None:
    scene = build_scene_from_project(build_golden_townhouse())
    textures_dir = tmp_path / "textures"
    textures_dir.mkdir()
    for material in scene.materials:
        for slot in TEXTURE_SLOTS:
            (textures_dir / material.texture_filename(slot, extension="ktx2")).write_bytes(b"\xabKTX 20\xbb\r\n\x1a\n")

    glb_path = write_ktx_glb(scene, textures_dir, tmp_path / "model.glb")
    payload = read_glb_json(glb_path)

    assert "KHR_texture_basisu" in payload["extensionsUsed"]
    assert "KHR_materials_pbrSpecularGlossiness" not in json.dumps(payload)
    assert payload["images"][0]["mimeType"] == "image/ktx2"
    assert "bufferView" in payload["images"][0]
    assert all(view["buffer"] == 0 for view in payload["bufferViews"])
