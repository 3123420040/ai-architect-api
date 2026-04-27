from __future__ import annotations

import json
import zipfile
from pathlib import Path

from app.services.professional_deliverables.gltf_authoring import GLTFAuthoringError, read_glb_json
from app.services.professional_deliverables.scene_contract import SceneContract
from app.services.professional_deliverables.texture_authoring import read_png_dimensions
from app.services.professional_deliverables.usdz_budget import (
    AR_QUICK_LOOK_MAX_BYTES,
    AR_QUICK_LOOK_MAX_TEXTURE_PX,
    AR_QUICK_LOOK_MAX_TRIANGLES,
    USDZBudgetReport,
)
from app.services.professional_deliverables.usdz_materials import USD_PREVIEW_INPUTS
from app.services.professional_deliverables.validators import GateResult


def _import_pxr(require_binary: bool):
    try:
        from pxr import Usd, UsdGeom, UsdShade, UsdUtils
    except ImportError:
        if require_binary:
            raise
        return None
    return Usd, UsdGeom, UsdShade, UsdUtils


def _stage_triangles(stage, UsdGeom) -> int:
    triangles = 0
    for prim in stage.Traverse():
        if not prim.IsA(UsdGeom.Mesh):
            continue
        mesh = UsdGeom.Mesh(prim)
        counts = mesh.GetFaceVertexCountsAttr().Get() or []
        triangles += sum(max(0, int(count) - 2) for count in counts)
    return triangles


def _package_texture_names(usdz_path: Path) -> list[str]:
    with zipfile.ZipFile(usdz_path) as archive:
        return sorted(name for name in archive.namelist() if name.lower().endswith((".png", ".jpg", ".jpeg")))


def _shader_input_names(stage, UsdShade) -> dict[str, set[str]]:
    materials: dict[str, set[str]] = {}
    for prim in stage.Traverse():
        if not prim.IsA(UsdShade.Material):
            continue
        names: set[str] = set()
        for child in prim.GetChildren():
            if not child.IsA(UsdShade.Shader):
                continue
            shader = UsdShade.Shader(child)
            shader_id = shader.GetIdAttr().Get()
            if shader_id == "UsdPreviewSurface":
                names.update(input_.GetBaseName() for input_ in shader.GetInputs())
        materials[prim.GetName()] = names
    return materials


def _shader_texture_asset_paths(stage, UsdShade) -> list[str]:
    paths: list[str] = []
    for prim in stage.Traverse():
        if not prim.IsA(UsdShade.Shader):
            continue
        shader = UsdShade.Shader(prim)
        if shader.GetIdAttr().Get() != "UsdUVTexture":
            continue
        file_input = shader.GetInput("file")
        if not file_input:
            continue
        asset = file_input.Get()
        if asset is None:
            continue
        path = getattr(asset, "path", str(asset))
        if path:
            paths.append(path.lstrip("./"))
    return sorted(set(paths))


def validate_usdz_size_budget(usdz_path: Path, report_path: Path, *, require_binary: bool) -> GateResult:
    if not usdz_path.exists():
        return GateResult("USDZ size budget", "fail" if require_binary else "skipped", "model.usdz was not produced")
    pxr = _import_pxr(require_binary)
    if pxr is None:
        return GateResult("USDZ size budget", "skipped", "usd-core unavailable locally; CI runs this gate")
    Usd, UsdGeom, _UsdShade, _UsdUtils = pxr
    stage = Usd.Stage.Open(str(usdz_path))
    if stage is None:
        return GateResult("USDZ size budget", "fail", "model.usdz could not be opened as a USD stage")
    try:
        max_texture_px = 0
        with zipfile.ZipFile(usdz_path) as archive:
            texture_names = [name for name in archive.namelist() if name.lower().endswith(".png")]
            if not texture_names:
                raise ValueError("No PNG textures found")
            for name in texture_names:
                with archive.open(name) as handle:
                    temp_png = report_path.with_name(f"{Path(name).stem}.budget.png")
                    temp_png.write_bytes(handle.read())
                    max_texture_px = max(max_texture_px, *read_png_dimensions(temp_png))
                    temp_png.unlink(missing_ok=True)
    except (zipfile.BadZipFile, ValueError) as exc:
        return GateResult("USDZ size budget", "fail", f"Unable to inspect USDZ texture budget: {exc}")
    triangles = _stage_triangles(stage, UsdGeom)
    report = USDZBudgetReport(size_bytes=usdz_path.stat().st_size, triangle_count=triangles, max_texture_px=max_texture_px)
    report_path.write_text(json.dumps(report.as_dict(), indent=2), encoding="utf-8")
    failures: list[str] = []
    if report.size_bytes > AR_QUICK_LOOK_MAX_BYTES:
        failures.append(f"size {report.size_bytes} > {AR_QUICK_LOOK_MAX_BYTES}")
    if report.triangle_count > AR_QUICK_LOOK_MAX_TRIANGLES:
        failures.append(f"triangles {report.triangle_count} > {AR_QUICK_LOOK_MAX_TRIANGLES}")
    if report.max_texture_px > AR_QUICK_LOOK_MAX_TEXTURE_PX:
        failures.append(f"texture {report.max_texture_px}px > {AR_QUICK_LOOK_MAX_TEXTURE_PX}px")
    if failures:
        return GateResult("USDZ size budget", "fail", "; ".join(failures))
    return GateResult(
        "USDZ size budget",
        "pass",
        f"{report.size_bytes} bytes, {report.triangle_count} triangles, max texture {report.max_texture_px}px",
    )


def validate_usdz_structural_integrity(usdz_path: Path, report_path: Path, *, require_binary: bool) -> GateResult:
    if not usdz_path.exists():
        return GateResult("USDZ structural integrity", "fail" if require_binary else "skipped", "model.usdz was not produced")
    pxr = _import_pxr(require_binary)
    if pxr is None:
        return GateResult("USDZ structural integrity", "skipped", "usd-core unavailable locally; CI runs this gate")
    Usd, _UsdGeom, UsdShade, UsdUtils = pxr
    try:
        with zipfile.ZipFile(usdz_path) as archive:
            names = archive.namelist()
            archive.testzip()
    except zipfile.BadZipFile as exc:
        return GateResult("USDZ structural integrity", "fail", f"USDZ zip cannot be read: {exc}")
    stage = Usd.Stage.Open(str(usdz_path))
    if stage is None:
        return GateResult("USDZ structural integrity", "fail", "USDZ default layer does not open")
    checker = UsdUtils.ComplianceChecker(arkit=True)
    checker.CheckCompliance(str(usdz_path))
    failed = checker.GetFailedChecks()
    material_inputs = _shader_input_names(stage, UsdShade)
    has_preview_surface = bool(material_inputs) and all(USD_PREVIEW_INPUTS[0] in inputs for inputs in material_inputs.values())
    textures = _package_texture_names(usdz_path)
    referenced_textures = _shader_texture_asset_paths(stage, UsdShade)
    missing_references = [path for path in referenced_textures if path not in names]
    report_path.write_text(
        json.dumps(
            {
                "file_count": len(names),
                "texture_count": len(textures),
                "texture_names": textures,
                "referenced_textures": referenced_textures,
                "missing_references": missing_references,
                "material_count": len(material_inputs),
                "failed_checks": failed,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    if failed:
        return GateResult("USDZ structural integrity", "fail", "; ".join(failed[:6]))
    if not textures:
        return GateResult("USDZ structural integrity", "fail", "No embedded textures found inside USDZ")
    if missing_references:
        return GateResult("USDZ structural integrity", "fail", f"Missing referenced textures: {missing_references[:6]}")
    if not has_preview_surface:
        return GateResult("USDZ structural integrity", "fail", "UsdPreviewSurface material inputs did not resolve")
    return GateResult(
        "USDZ structural integrity",
        "pass",
        f"opens as USDZ, {len(textures)} embedded textures, {len(material_inputs)} UsdPreviewSurface materials",
    )


def validate_usdz_material_parity(
    glb_path: Path,
    usdz_path: Path,
    scene: SceneContract,
    report_path: Path,
    *,
    require_binary: bool,
) -> GateResult:
    if not usdz_path.exists():
        return GateResult("USDZ material parity", "fail" if require_binary else "skipped", "model.usdz was not produced")
    pxr = _import_pxr(require_binary)
    if pxr is None:
        return GateResult("USDZ material parity", "skipped", "usd-core unavailable locally; CI runs this gate")
    Usd, _UsdGeom, UsdShade, _UsdUtils = pxr
    try:
        glb_payload = read_glb_json(glb_path)
    except (GLTFAuthoringError, json.JSONDecodeError) as exc:
        return GateResult("USDZ material parity", "fail", f"GLB material source cannot be read: {exc}")
    glb_materials = {material.get("name") for material in glb_payload.get("materials", [])}
    scene_materials = {material.name for material in scene.materials}
    stage = Usd.Stage.Open(str(usdz_path))
    if stage is None:
        return GateResult("USDZ material parity", "fail", "USDZ stage cannot be opened")
    usd_inputs = _shader_input_names(stage, UsdShade)
    usd_materials = set(usd_inputs)
    missing_inputs = {
        material_name: sorted(set(USD_PREVIEW_INPUTS) - inputs)
        for material_name, inputs in usd_inputs.items()
        if set(USD_PREVIEW_INPUTS) - inputs
    }
    report_path.write_text(
        json.dumps(
            {
                "glb_materials": sorted(glb_materials),
                "usd_materials": sorted(usd_materials),
                "expected_materials": sorted(scene_materials),
                "missing_inputs": missing_inputs,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    if glb_materials != usd_materials or scene_materials != usd_materials:
        return GateResult(
            "USDZ material parity",
            "fail",
            f"GLB/USD material mismatch: glb={sorted(glb_materials)}, usdz={sorted(usd_materials)}",
        )
    if missing_inputs:
        return GateResult("USDZ material parity", "fail", f"Missing UsdPreviewSurface inputs: {missing_inputs}")
    return GateResult(
        "USDZ material parity",
        "pass",
        f"{len(usd_materials)} materials match GLB with diffuse/metal/rough/normal/AO/emissive channels",
    )


def validate_usdz_texture_payload(usdz_path: Path, report_path: Path, *, require_binary: bool) -> GateResult:
    if not usdz_path.exists():
        return GateResult("USDZ texture payload", "fail" if require_binary else "skipped", "model.usdz was not produced")
    try:
        max_dimension = 0
        texture_count = 0
        with zipfile.ZipFile(usdz_path) as archive:
            for name in _package_texture_names(usdz_path):
                with archive.open(name) as handle:
                    temp_png = report_path.with_name(f"{Path(name).stem}.tmp.png")
                    temp_png.write_bytes(handle.read())
                    max_dimension = max(max_dimension, *read_png_dimensions(temp_png))
                    temp_png.unlink(missing_ok=True)
                    texture_count += 1
    except (zipfile.BadZipFile, ValueError) as exc:
        return GateResult("USDZ texture payload", "fail", str(exc))
    report_path.write_text(
        json.dumps({"texture_count": texture_count, "max_dimension": max_dimension}, indent=2),
        encoding="utf-8",
    )
    if texture_count == 0:
        return GateResult("USDZ texture payload", "fail", "No PNG textures embedded in USDZ")
    if max_dimension > AR_QUICK_LOOK_MAX_TEXTURE_PX:
        return GateResult("USDZ texture payload", "fail", f"Texture dimension {max_dimension}px > 2K")
    return GateResult("USDZ texture payload", "pass", f"{texture_count} embedded PNG textures, max dimension {max_dimension}px")
