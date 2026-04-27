from __future__ import annotations

import pytest

from app.services.professional_deliverables.drawing_contract import DeliverableValidationError
from app.services.professional_deliverables.material_registry import GOLDEN_MATERIALS
from app.services.professional_deliverables.scene_contract import (
    BoxMeshElement,
    SceneContract,
    TEXTURE_SLOTS,
    validate_scene_contract,
)
from app.services.professional_deliverables.texture_authoring import read_png_dimensions, sample_png_pixel, write_solid_rgba_png
from app.services.professional_deliverables.usdz_budget import (
    AR_QUICK_LOOK_LITE_TEXTURE_PX,
    AR_QUICK_LOOK_MAX_BYTES,
    AR_QUICK_LOOK_MAX_TEXTURE_PX,
    AR_QUICK_LOOK_MAX_TRIANGLES,
    USDZBudgetReport,
)
from app.services.professional_deliverables.usdz_converter import _apply_usd_preview_materials, _package_usdz
from app.services.professional_deliverables.usdz_materials import USD_PREVIEW_INPUTS, build_usdz_material_payloads
from app.services.professional_deliverables import usdz_texture_payload
from app.services.professional_deliverables.usdz_validators import validate_usdz_structural_integrity


class DummyKTXTool:
    style = "ktx"
    path = "ktx"
    version = "test"


def test_usdz_material_payloads_include_preview_surface_channels() -> None:
    payloads = build_usdz_material_payloads(GOLDEN_MATERIALS)

    assert len(payloads) == len(GOLDEN_MATERIALS)
    assert set(payloads[0].textures) == set(USD_PREVIEW_INPUTS)
    assert payloads[0].textures["metallic"].endswith("_metallic.png")
    assert payloads[0].textures["roughness"].endswith("_roughness.png")


def test_usdz_texture_payload_splits_metallic_roughness_channels(tmp_path, monkeypatch) -> None:
    material = GOLDEN_MATERIALS[0]
    textures_dir = tmp_path / "ktx"
    textures_dir.mkdir()
    for slot in TEXTURE_SLOTS:
        (textures_dir / material.texture_filename(slot, extension="ktx2")).write_bytes(b"ktx")

    def fake_validate(_tool, _path):
        return None

    def fake_sample(_tool, ktx_path, _raw_path):
        if "metallicRoughness" in ktx_path.name:
            return (0, 184, 17, 255)
        return (10, 20, 30, 255)

    monkeypatch.setattr(usdz_texture_payload, "validate_ktx", fake_validate)
    monkeypatch.setattr(usdz_texture_payload, "extract_ktx_rgba8_sample", fake_sample)

    payloads = usdz_texture_payload.build_usdz_texture_payload(
        (material,),
        textures_dir,
        tmp_path / "payload" / "textures",
        tmp_path / "samples",
        ktx_tool=DummyKTXTool(),  # type: ignore[arg-type]
        max_resolution_px=AR_QUICK_LOOK_LITE_TEXTURE_PX,
    )

    payload = payloads[0]
    assert read_png_dimensions(payload.files["metallic"]) == (1024, 1024)
    assert sample_png_pixel(payload.files["metallic"]) == (17, 17, 17, 255)
    assert sample_png_pixel(payload.files["roughness"]) == (184, 184, 184, 255)


def test_usdz_budget_report_enforces_apple_ar_limits() -> None:
    report = USDZBudgetReport(
        size_bytes=AR_QUICK_LOOK_MAX_BYTES,
        triangle_count=AR_QUICK_LOOK_MAX_TRIANGLES,
        max_texture_px=AR_QUICK_LOOK_MAX_TEXTURE_PX,
    )

    assert report.within_budget is True


def test_usdz_structural_integrity_accepts_openusd_localized_textures(tmp_path) -> None:
    pxr = pytest.importorskip("pxr")
    Usd = pytest.importorskip("pxr.Usd")
    UsdGeom = pytest.importorskip("pxr.UsdGeom")
    Gf = pytest.importorskip("pxr.Gf")
    UsdLux = pytest.importorskip("pxr.UsdLux")
    assert pxr
    material = GOLDEN_MATERIALS[0]
    scene = SceneContract(
        project_id="usdz-smoke",
        project_name="USDZ Smoke",
        elements=(
            BoxMeshElement(
                id="wall",
                name="Wall",
                category="wall",
                lod=300,
                material_name=material.name,
                center_m=(0.0, 0.0, 1.0),
                size_m=(1.0, 1.0, 2.0),
            ),
        ),
        materials=(material,),
    )
    package_root = tmp_path / "package"
    texture_dir = package_root / "textures"
    texture_dir.mkdir(parents=True)
    for texture_path in build_usdz_material_payloads((material,))[0].textures.values():
        write_solid_rgba_png(package_root / texture_path, size_px=4, color=(128, 128, 128, 255))

    stage_path = package_root / "model_lite.usda"
    stage = Usd.Stage.CreateNew(str(stage_path))
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.z)
    UsdGeom.SetStageMetersPerUnit(stage, 1.0)
    world = UsdGeom.Xform.Define(stage, "/World")
    stage.SetDefaultPrim(world.GetPrim())
    UsdLux.DomeLight.Define(stage, "/World/env_light")
    mesh = UsdGeom.Mesh.Define(stage, "/World/Wall")
    mesh.CreatePointsAttr([Gf.Vec3f(0, 0, 0), Gf.Vec3f(1, 0, 0), Gf.Vec3f(0, 1, 0)])
    mesh.CreateFaceVertexCountsAttr([3])
    mesh.CreateFaceVertexIndicesAttr([0, 1, 2])
    stage.GetRootLayer().Save()

    _apply_usd_preview_materials(stage_path, scene, texture_dir, tmp_path / "material-report.json")
    usdz_path = tmp_path / "model.usdz"
    _package_usdz(stage_path, usdz_path)

    gate = validate_usdz_structural_integrity(usdz_path, tmp_path / "structural-report.json", require_binary=True)

    assert gate.status == "pass"


def test_empty_sprint3_scene_is_rejected_before_delivery() -> None:
    scene = SceneContract(project_id="empty", project_name="Empty", elements=(), materials=GOLDEN_MATERIALS)

    with pytest.raises(DeliverableValidationError):
        validate_scene_contract(scene)
