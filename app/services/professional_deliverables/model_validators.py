from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from app.core.config import ROOT_DIR
from app.services.professional_deliverables.blender_runner import BlenderToolError, run_blender_script
from app.services.professional_deliverables.gltf_authoring import GLTFAuthoringError, read_glb_json
from app.services.professional_deliverables.ktx2_encoder import ExternalToolError, KTXTool, extract_ktx_rgba8_sample, validate_ktx
from app.services.professional_deliverables.scene_contract import SceneContract, TEXTURE_SLOTS
from app.services.professional_deliverables.texture_authoring import AuthoredTexture
from app.services.professional_deliverables.validators import GateResult

FBX_IMPORT_CHECK_SCRIPT = Path(__file__).resolve().parent / "blender_scripts" / "import_fbx_check.py"


def _run(command: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=cwd, text=True, capture_output=True, check=False)


def _node_validator_ready() -> bool:
    script = ROOT_DIR / "tools" / "sprint2" / "validate-gltf.mjs"
    dependency = ROOT_DIR / "tools" / "sprint2" / "node_modules" / "gltf-validator"
    return bool(shutil.which("node") and script.exists() and dependency.exists())


def validate_gltf_validator(glb_path: Path, report_path: Path, *, require_binary: bool) -> GateResult:
    if not glb_path.exists():
        return GateResult("glTF Validator", "fail" if require_binary else "skipped", f"{glb_path.name} was not produced")
    if not _node_validator_ready():
        if require_binary:
            return GateResult("glTF Validator", "fail", "Node gltf-validator dependencies are not installed")
        return GateResult("glTF Validator", "skipped", "Node gltf-validator dependencies unavailable locally; CI runs this gate")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    command = ["node", str(ROOT_DIR / "tools" / "sprint2" / "validate-gltf.mjs"), str(glb_path), str(report_path)]
    result = _run(command, cwd=ROOT_DIR)
    if result.returncode != 0:
        detail = "\n".join(line for line in (result.stdout + result.stderr).splitlines() if line.strip())
        return GateResult("glTF Validator", "fail", detail[:700])
    report = json.loads(report_path.read_text(encoding="utf-8"))
    issues = report.get("issues", {})
    return GateResult(
        "glTF Validator",
        "pass",
        f"errors={issues.get('numErrors', 0)}, warnings={issues.get('numWarnings', 0)}, infos={issues.get('numInfos', 0)}",
    )


def validate_glb_material_workflow(glb_path: Path, scene: SceneContract) -> GateResult:
    if not glb_path.exists():
        return GateResult("glTF material workflow", "fail", f"{glb_path.name} was not produced")
    try:
        payload = read_glb_json(glb_path)
    except (GLTFAuthoringError, json.JSONDecodeError) as exc:
        return GateResult("glTF material workflow", "fail", str(exc))
    forbidden = "KHR_materials_pbrSpecularGlossiness"
    if forbidden in payload.get("extensionsUsed", []) or forbidden in json.dumps(payload):
        return GateResult("glTF material workflow", "fail", f"{forbidden} must not be present")
    materials = payload.get("materials", [])
    if len(materials) != len(scene.materials):
        return GateResult("glTF material workflow", "fail", f"material count {len(materials)} != expected {len(scene.materials)}")
    missing_pbr = [material.get("name", "<unnamed>") for material in materials if "pbrMetallicRoughness" not in material]
    if missing_pbr:
        return GateResult("glTF material workflow", "fail", f"materials missing pbrMetallicRoughness: {missing_pbr}")
    return GateResult("glTF material workflow", "pass", f"{len(materials)} materials use pbrMetallicRoughness only")


def validate_metallic_roughness_packing(
    scene: SceneContract,
    authored: dict[str, dict[str, AuthoredTexture]],
    textures_dir: Path,
    *,
    ktx_tool: KTXTool | None,
    require_binary: bool,
) -> GateResult:
    if ktx_tool is None or ktx_tool.style != "ktx":
        status = "fail" if require_binary else "skipped"
        return GateResult("MetallicRoughness packing", status, "Unified ktx CLI required to extract KTX2 pixels")
    failures: list[str] = []
    with tempfile.TemporaryDirectory(prefix="sprint2-mr-extract-") as temp_name:
        temp_dir = Path(temp_name)
        for material in scene.materials:
            ktx_path = textures_dir / material.texture_filename("metallicRoughness", extension="ktx2")
            if not ktx_path.exists():
                failures.append(f"{material.name}: missing {ktx_path.name}")
                continue
            try:
                validate_ktx(ktx_tool, ktx_path)
                sample = extract_ktx_rgba8_sample(ktx_tool, ktx_path, temp_dir / f"{material.name}_mr.rgba")
            except (ExternalToolError, ValueError) as exc:
                failures.append(f"{material.name}: {exc}")
                continue
            expected = authored[material.name]["metallicRoughness"].expected_sample_rgba
            if sample[0] > 12 or abs(sample[1] - expected[1]) > 16 or abs(sample[2] - expected[2]) > 16:
                failures.append(
                    f"{material.name}: expected R unused/G rough/B metal near {expected[:3]}, sampled {sample[:3]}"
                )
    if failures:
        return GateResult("MetallicRoughness packing", "fail", " | ".join(failures[:8]))
    return GateResult("MetallicRoughness packing", "pass", f"{len(scene.materials)} material MR textures sampled as R=unused, G=rough, B=metal")


def validate_texture_resolution_policy(
    scene: SceneContract,
    textures_dir: Path,
    *,
    ktx_tool: KTXTool | None = None,
    require_binary: bool = False,
) -> GateResult:
    failures: list[str] = []
    for material in scene.materials:
        if material.tier == "hero" and material.resolution_px < 2048:
            failures.append(f"{material.name}: hero material below 2K")
        if material.tier == "mobile" and material.resolution_px > 1024:
            failures.append(f"{material.name}: mobile material above 1K")
        if material.resolution_px > 4096:
            failures.append(f"{material.name}: texture exceeds 4K")
        for slot in TEXTURE_SLOTS:
            path = textures_dir / material.texture_filename(slot, extension="ktx2")
            if not path.exists():
                failures.append(f"{material.name}: missing {slot} KTX2")
                continue
            if ktx_tool is not None:
                try:
                    validate_ktx(ktx_tool, path)
                except ExternalToolError as exc:
                    failures.append(f"{material.name}/{slot}: {exc}")
            elif require_binary:
                failures.append("Unified ktx CLI required to validate KTX2 textures")
    raw_images = sorted(path.name for path in textures_dir.glob("*") if path.suffix.lower() in {".png", ".jpg", ".jpeg"})
    if raw_images:
        failures.append(f"raw images found in final textures folder: {raw_images}")
    if failures:
        return GateResult("Texture resolution policy", "fail", " | ".join(failures[:12]))
    return GateResult("Texture resolution policy", "pass", "hero>=2K, mobile<=1K, max<=4K, final textures are KTX2-only and ktx-validated")


def validate_fbx_import(fbx_path: Path, metadata_path: Path, report_path: Path, *, require_binary: bool) -> GateResult:
    if not fbx_path.exists():
        return GateResult("FBX Blender import", "fail" if require_binary else "skipped", f"{fbx_path.name} was not produced")
    try:
        blender = run_blender_script(
            FBX_IMPORT_CHECK_SCRIPT,
            ["--fbx", str(fbx_path), "--metadata-json", str(metadata_path), "--report-json", str(report_path)],
            require_binary=require_binary,
        )
    except BlenderToolError as exc:
        return GateResult("FBX Blender import", "fail" if require_binary else "skipped", str(exc)[:700])
    if blender is None:
        return GateResult("FBX Blender import", "skipped", "Blender unavailable locally; CI runs this gate")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if report.get("status") != "pass":
        return GateResult("FBX Blender import", "fail", "; ".join(report.get("issues", []))[:700])
    return GateResult(
        "FBX Blender import",
        "pass",
        f"{report['mesh_count']} meshes, {report['material_count']} materials, extents_cm={report['extents_cm']}, UV0 0-1",
    )


def validate_usdz_size_budget_skipped() -> GateResult:
    return GateResult("USDZ size budget", "skipped", "Sprint 3 owns USDZ export and size budget gate")
