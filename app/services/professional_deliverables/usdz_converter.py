from __future__ import annotations

import json
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from app.services.professional_deliverables.blender_runner import BlenderToolError, run_blender_script
from app.services.professional_deliverables.gltf_authoring import read_glb_json, write_blender_preview_glb
from app.services.professional_deliverables.ktx2_encoder import ExternalToolError, KTXTool
from app.services.professional_deliverables.scene_contract import SceneContract
from app.services.professional_deliverables.usdz_budget import (
    AR_QUICK_LOOK_LITE_TEXTURE_PX,
    AR_QUICK_LOOK_MAX_TRIANGLES,
)
from app.services.professional_deliverables.usdz_materials import USD_PREVIEW_INPUTS, build_usdz_material_payloads
from app.services.professional_deliverables.usdz_texture_payload import build_usdz_texture_payload

EXPORT_USD_SCRIPT = Path(__file__).resolve().parent / "blender_scripts" / "export_usd_from_glb.py"


class USDZConversionError(RuntimeError):
    pass


@dataclass(frozen=True)
class USDZExportResult:
    usdz_path: Path
    lite_path: Path
    usd_stage_path: Path
    export_report_path: Path
    material_report_path: Path


def _import_pxr():
    try:
        from pxr import Gf, Sdf, Usd, UsdGeom, UsdShade, UsdUtils
    except ImportError as exc:
        raise USDZConversionError("usd-core/pxr is required for USDZ export") from exc
    return Gf, Sdf, Usd, UsdGeom, UsdShade, UsdUtils


def _normalize_name(value: str) -> str:
    return "".join(char.lower() for char in value if char.isalnum())


def _remove_existing_material_prims(stage, UsdShade) -> None:
    paths = [
        prim.GetPath()
        for prim in stage.Traverse()
        if prim.IsA(UsdShade.Material) or prim.IsA(UsdShade.Shader)
    ]
    for path in sorted(paths, key=lambda item: len(str(item)), reverse=True):
        stage.RemovePrim(path)


def _remove_unsupported_arkit_prims(stage) -> None:
    unsupported_type_names = {
        "Camera",
        "CylinderLight",
        "DiskLight",
        "DistantLight",
        "DomeLight",
        "RectLight",
        "SphereLight",
    }
    paths = [prim.GetPath() for prim in stage.Traverse() if prim.GetTypeName() in unsupported_type_names]
    for path in sorted(paths, key=lambda item: len(str(item)), reverse=True):
        stage.RemovePrim(path)


def _ensure_default_prim(stage, UsdGeom) -> None:
    # ARKit's USDZ compliance profile expects Y-up stage metadata even though
    # the source Sprint 2 scene contract is authored with Z as the vertical axis.
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.y)
    UsdGeom.SetStageMetersPerUnit(stage, 1.0)
    if stage.GetDefaultPrim():
        return
    roots = [prim for prim in stage.GetPseudoRoot().GetChildren() if prim.IsActive()]
    if roots:
        stage.SetDefaultPrim(roots[0])
        return
    world = UsdGeom.Xform.Define(stage, "/World").GetPrim()
    stage.SetDefaultPrim(world)


def _texture_shader(stage, Sdf, UsdShade, material_path: str, input_name: str, texture_path: str, *, scalar: bool, srgb: bool):
    shader = UsdShade.Shader.Define(stage, f"{material_path}/{input_name}Texture")
    shader.CreateIdAttr("UsdUVTexture")
    shader.CreateInput("file", Sdf.ValueTypeNames.Asset).Set(Sdf.AssetPath(texture_path))
    shader.CreateInput("sourceColorSpace", Sdf.ValueTypeNames.Token).Set("sRGB" if srgb else "raw")
    if scalar:
        return shader.CreateOutput("r", Sdf.ValueTypeNames.Float)
    return shader.CreateOutput("rgb", Sdf.ValueTypeNames.Float3)


def _apply_usd_preview_materials(stage_path: Path, scene: SceneContract, texture_root: Path, report_path: Path) -> None:
    _Gf, Sdf, Usd, UsdGeom, UsdShade, _UsdUtils = _import_pxr()
    stage = Usd.Stage.Open(str(stage_path))
    if stage is None:
        raise USDZConversionError(f"Unable to open USD stage {stage_path}")
    _ensure_default_prim(stage, UsdGeom)
    _remove_unsupported_arkit_prims(stage)
    _remove_existing_material_prims(stage, UsdShade)

    material_payloads = build_usdz_material_payloads(scene.materials)
    material_by_name = {}
    for payload in material_payloads:
        material_path = f"/Materials/{payload.material.name}"
        material = UsdShade.Material.Define(stage, material_path)
        shader = UsdShade.Shader.Define(stage, f"{material_path}/PreviewSurface")
        shader.CreateIdAttr("UsdPreviewSurface")
        material.CreateSurfaceOutput().ConnectToSource(shader.CreateOutput("surface", Sdf.ValueTypeNames.Token))

        diffuse = _texture_shader(
            stage,
            Sdf,
            UsdShade,
            material_path,
            "diffuseColor",
            payload.textures["diffuseColor"],
            scalar=False,
            srgb=True,
        )
        shader.CreateInput("diffuseColor", Sdf.ValueTypeNames.Color3f).ConnectToSource(diffuse)
        for input_name in ("metallic", "roughness", "occlusion"):
            source = _texture_shader(
                stage,
                Sdf,
                UsdShade,
                material_path,
                input_name,
                payload.textures[input_name],
                scalar=True,
                srgb=False,
            )
            shader.CreateInput(input_name, Sdf.ValueTypeNames.Float).ConnectToSource(source)
        normal = _texture_shader(
            stage,
            Sdf,
            UsdShade,
            material_path,
            "normal",
            payload.textures["normal"],
            scalar=False,
            srgb=False,
        )
        shader.CreateInput("normal", Sdf.ValueTypeNames.Normal3f).ConnectToSource(normal)
        emissive = _texture_shader(
            stage,
            Sdf,
            UsdShade,
            material_path,
            "emissiveColor",
            payload.textures["emissiveColor"],
            scalar=False,
            srgb=True,
        )
        shader.CreateInput("emissiveColor", Sdf.ValueTypeNames.Color3f).ConnectToSource(emissive)
        material_by_name[payload.material.name] = material

    element_materials = {_normalize_name(element.name): element.material_name for element in scene.elements}
    fallback = material_by_name[scene.materials[0].name]
    for prim in stage.Traverse():
        if not prim.IsA(UsdGeom.Mesh):
            continue
        material_name = element_materials.get(_normalize_name(prim.GetName()))
        UsdShade.MaterialBindingAPI.Apply(prim).Bind(material_by_name.get(material_name, fallback))

    stage.GetRootLayer().Save()
    report_path.write_text(
        json.dumps(
            {
                "material_count": len(material_payloads),
                "inputs": list(USD_PREVIEW_INPUTS),
                "texture_root": str(texture_root),
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def _package_usdz(stage_path: Path, usdz_path: Path) -> None:
    _Gf, _Sdf, _Usd, _UsdGeom, _UsdShade, UsdUtils = _import_pxr()
    usdz_path.parent.mkdir(parents=True, exist_ok=True)
    if not UsdUtils.CreateNewARKitUsdzPackage(str(stage_path), str(usdz_path)):
        raise USDZConversionError(f"OpenUSD failed to package {usdz_path.name}")


def _assert_glb_source(glb_path: Path, scene: SceneContract) -> None:
    payload = read_glb_json(glb_path)
    glb_material_names = {material.get("name") for material in payload.get("materials", [])}
    scene_material_names = {material.name for material in scene.materials}
    if glb_material_names != scene_material_names:
        raise USDZConversionError(
            f"GLB material set does not match scene contract: {sorted(glb_material_names)} != {sorted(scene_material_names)}"
        )


def export_usdz_from_glb(
    scene: SceneContract,
    glb_path: Path,
    textures_dir: Path,
    three_d_dir: Path,
    *,
    ktx_tool: KTXTool,
    require_external_tools: bool,
) -> USDZExportResult:
    if not glb_path.exists():
        raise USDZConversionError(f"Source GLB not found: {glb_path}")
    _assert_glb_source(glb_path, scene)
    three_d_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="sprint3-usdz-") as temp_name:
        temp_dir = Path(temp_name)
        package_root = temp_dir / "package"
        payload_texture_dir = package_root / "textures"
        package_root.mkdir(parents=True, exist_ok=True)

        build_usdz_texture_payload(
            scene.materials,
            textures_dir,
            payload_texture_dir,
            temp_dir / "ktx-samples",
            ktx_tool=ktx_tool,
            max_resolution_px=AR_QUICK_LOOK_LITE_TEXTURE_PX,
        )

        blender_glb_path = temp_dir / "blender-readable-source.glb"
        write_blender_preview_glb(glb_path, scene, blender_glb_path)

        stage_path = package_root / "model_lite.usd"
        export_report_path = three_d_dir / "usdz-export-report.json"
        try:
            blender = run_blender_script(
                EXPORT_USD_SCRIPT,
                [
                    "--glb",
                    str(blender_glb_path),
                    "--usd",
                    str(stage_path),
                    "--report-json",
                    str(export_report_path),
                    "--target-triangles",
                    str(AR_QUICK_LOOK_MAX_TRIANGLES),
                ],
                require_binary=require_external_tools,
            )
        except BlenderToolError as exc:
            raise USDZConversionError(str(exc)) from exc
        if blender is None:
            raise USDZConversionError("Blender unavailable locally; CI runs USD export")

        material_report_path = three_d_dir / "usdz-material-report.json"
        try:
            _apply_usd_preview_materials(stage_path, scene, payload_texture_dir, material_report_path)
            lite_path = three_d_dir / "model_lite.usdz"
            _package_usdz(stage_path, lite_path)
        except (USDZConversionError, ExternalToolError) as exc:
            raise USDZConversionError(str(exc)) from exc

        stage_copy = three_d_dir / "model_lite.usd"
        shutil.copyfile(stage_path, stage_copy)
        usdz_path = three_d_dir / "model.usdz"
        shutil.copyfile(lite_path, usdz_path)
        return USDZExportResult(
            usdz_path=usdz_path,
            lite_path=lite_path,
            usd_stage_path=stage_copy,
            export_report_path=export_report_path,
            material_report_path=material_report_path,
        )
