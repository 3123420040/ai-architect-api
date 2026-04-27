from __future__ import annotations

from app.services.professional_deliverables.material_registry import GOLDEN_MATERIALS
from app.services.professional_deliverables.model_validators import validate_texture_resolution_policy
from app.services.professional_deliverables.scene_contract import SceneContract, TEXTURE_SLOTS
from app.services.professional_deliverables.texture_authoring import sample_png_pixel, write_solid_rgba_png


def test_metallic_roughness_source_map_uses_g_for_roughness_and_b_for_metal(tmp_path) -> None:
    path = tmp_path / "mr.png"
    write_solid_rgba_png(path, size_px=4, color=(0, 184, 0, 255))

    assert sample_png_pixel(path, x=2, y=2) == (0, 184, 0, 255)


def test_texture_resolution_policy_requires_ktx2_only(tmp_path) -> None:
    scene = SceneContract(
        project_id="golden-townhouse",
        project_name="Golden",
        elements=(),
        materials=GOLDEN_MATERIALS,
    )
    for material in scene.materials:
        for slot in TEXTURE_SLOTS:
            (tmp_path / material.texture_filename(slot, extension="ktx2")).write_bytes(b"ktx2-placeholder")

    result = validate_texture_resolution_policy(scene, tmp_path)

    assert result.status == "pass"


def test_texture_resolution_policy_rejects_raw_final_images(tmp_path) -> None:
    scene = SceneContract(
        project_id="golden-townhouse",
        project_name="Golden",
        elements=(),
        materials=GOLDEN_MATERIALS,
    )
    for material in scene.materials:
        for slot in TEXTURE_SLOTS:
            (tmp_path / material.texture_filename(slot, extension="ktx2")).write_bytes(b"ktx2-placeholder")
    (tmp_path / "leaked-source.png").write_bytes(b"raw")

    result = validate_texture_resolution_policy(scene, tmp_path)

    assert result.status == "fail"
    assert "raw images" in result.detail
