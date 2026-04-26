from __future__ import annotations

from app.services.professional_deliverables.golden_fixture import build_golden_townhouse
from app.services.professional_deliverables.scene_builder import build_scene_from_project
from app.services.professional_deliverables.scene_contract import METAL_ROUGH_WORKFLOW, validate_scene_contract


def test_golden_scene_has_required_lod_and_material_contract() -> None:
    scene = build_scene_from_project(build_golden_townhouse())

    validate_scene_contract(scene)

    assert scene.lod_summary["lod_300"] > 0
    assert scene.lod_summary["lod_200"] > 0
    assert scene.lod_summary["lod_100"] > 0
    assert len(scene.materials) == 9
    assert all(material.name.startswith("MAT_") for material in scene.materials)
    assert all(material.workflow == METAL_ROUGH_WORKFLOW for material in scene.materials)
    assert all(element.lod == 300 for element in scene.elements if element.category in {"wall", "door", "window"})
    assert all(element.lod == 200 for element in scene.elements if element.category in {"furniture", "plumbing", "light", "plant"})


def test_texture_resolution_policy_is_encoded_in_material_registry() -> None:
    scene = build_scene_from_project(build_golden_townhouse())

    hero = [material for material in scene.materials if material.tier == "hero"]
    mobile = [material for material in scene.materials if material.tier == "mobile"]

    assert hero
    assert mobile
    assert all(material.resolution_px >= 2048 for material in hero)
    assert all(material.resolution_px <= 1024 for material in mobile)
    assert max(material.resolution_px for material in scene.materials) == 4096
