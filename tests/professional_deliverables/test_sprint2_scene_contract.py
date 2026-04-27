from __future__ import annotations

from app.services.geometry import build_geometry_v2
from app.services.professional_deliverables.geometry_adapter import geometry_to_drawing_project
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


def test_generated_scene_fbx_validation_metadata_is_dynamic() -> None:
    brief = {
        "project_type": "townhouse",
        "project_mode": "new_build",
        "lot": {"width_m": 5, "depth_m": 20, "orientation": "south"},
        "floors": 4,
        "rooms": {"bedrooms": 4, "bathrooms": 4},
        "style": "modern_minimalist",
        "design_goals": ["Hien dai am, nhieu anh sang va thong gio tot"],
        "household_profile": "Gia dinh 3 the he",
        "occupant_count": 6,
        "budget_vnd": 4_500_000_000,
        "timeline_months": 8,
        "special_requests": ["garage", "balcony", "prayer_room"],
        "must_haves": ["gara o to", "phong tho", "lay sang tu nhien"],
    }
    drawing = geometry_to_drawing_project(
        project_id="generated-4-storey",
        project_name="Generated 4 Storey",
        brief_json=brief,
        geometry_json=build_geometry_v2(brief),
    )
    scene = build_scene_from_project(drawing)
    metadata = scene.as_metadata_stub()
    fbx_validation = metadata["fbx_validation"]
    referenced_materials = {element.material_name for element in scene.elements}

    assert set(fbx_validation["expected_material_names"]) == referenced_materials
    assert "MAT_site_vegetation" not in fbx_validation["expected_material_names"]
    assert fbx_validation["expected_extents_cm"] != [620.0, 1620.0, 679.0]
    assert fbx_validation["expected_extents_cm"][2] > 1200
    assert all(value >= 5 for value in fbx_validation["extents_tolerance_cm"])
