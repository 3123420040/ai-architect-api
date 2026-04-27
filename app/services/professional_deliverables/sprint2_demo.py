from __future__ import annotations

import argparse
import json
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.services.professional_deliverables.drawing_contract import DrawingProject
from app.services.professional_deliverables.fbx_exporter import FBXExportResult, export_fbx
from app.services.professional_deliverables.gltf_authoring import (
    GLTFAuthoringError,
    embed_ktx_textures_in_glb,
    write_geometry_glb,
    write_source_gltf,
)
from app.services.professional_deliverables.gltf_exporter import GLTFExportError, export_glb_with_gltf_transform
from app.services.professional_deliverables.golden_fixture import build_golden_townhouse
from app.services.professional_deliverables.ktx2_encoder import ExternalToolError, encode_material_textures
from app.services.professional_deliverables.model_validators import (
    validate_fbx_import,
    validate_glb_material_workflow,
    validate_gltf_validator,
    validate_metallic_roughness_packing,
    validate_texture_resolution_policy,
    validate_usdz_size_budget_skipped,
)
from app.services.professional_deliverables.scene_builder import build_scene_from_project
from app.services.professional_deliverables.texture_authoring import write_source_textures
from app.services.professional_deliverables.validators import GateResult, build_file_inventory, write_gate_outputs


@dataclass(frozen=True)
class Sprint2BundleResult:
    project_dir: Path
    three_d_dir: Path
    textures_dir: Path
    glb_path: Path
    fbx_path: Path
    metadata_path: Path
    texture_paths: tuple[Path, ...]
    gate_results: tuple[GateResult, ...]
    gate_summary_json: Path
    gate_summary_md: Path

    @property
    def passed(self) -> bool:
        return all(result.status in {"pass", "skipped"} for result in self.gate_results)

    def as_dict(self) -> dict[str, Any]:
        return {
            "project_dir": str(self.project_dir),
            "three_d_dir": str(self.three_d_dir),
            "textures_dir": str(self.textures_dir),
            "glb_path": str(self.glb_path),
            "fbx_path": str(self.fbx_path),
            "metadata_path": str(self.metadata_path),
            "texture_paths": [str(path) for path in self.texture_paths],
            "passed": self.passed,
            "gates": [result.as_dict() for result in self.gate_results],
            "gate_summary_json": str(self.gate_summary_json),
            "gate_summary_md": str(self.gate_summary_md),
        }


def _clean_dir(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def generate_project_3d_bundle(
    project: DrawingProject,
    output_root: Path,
    *,
    require_external_tools: bool | None = None,
    project_dir: Path | None = None,
) -> Sprint2BundleResult:
    if require_external_tools is None:
        require_external_tools = bool(os.environ.get("CI"))
    scene = build_scene_from_project(project)
    project_dir = project_dir or (output_root / f"project-{project.project_id}")
    two_d_dir = project_dir / "2d"
    three_d_dir = project_dir / "3d"
    textures_dir = project_dir / "textures"
    two_d_dir.mkdir(parents=True, exist_ok=True)
    _clean_dir(three_d_dir)
    _clean_dir(textures_dir)

    glb_path = three_d_dir / "model.glb"
    fbx_path = three_d_dir / "model.fbx"
    metadata_path = three_d_dir / "sprint2_model_metadata.json"
    gate_overrides: list[GateResult] = []
    texture_paths: tuple[Path, ...] = ()
    ktx_tool = None

    with tempfile.TemporaryDirectory(prefix="sprint2-golden-") as temp_name:
        temp_dir = Path(temp_name)
        source_gltf_dir = temp_dir / "source-gltf"
        source_texture_dir = source_gltf_dir / "source-textures"
        authored = write_source_textures(scene.materials, source_texture_dir)
        source_gltf = write_source_gltf(scene, authored, source_gltf_dir)

        try:
            ktx_tool, texture_paths = encode_material_textures(
                scene.materials,
                authored,
                textures_dir,
                require_binary=require_external_tools,
            )
        except ExternalToolError as exc:
            gate_overrides.append(GateResult("KTX2 texture encoding", "fail", str(exc)[:700]))

        metadata = scene.as_metadata_stub(ktx_command=ktx_tool.command_label if ktx_tool else None)
        metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")

        if texture_paths:
            try:
                source_glb = write_geometry_glb(scene, temp_dir / "source-geometry.glb")
                draco_glb = temp_dir / "stage-draco-geometry.glb"
                gltf_tool = export_glb_with_gltf_transform(
                    source_glb,
                    draco_glb,
                    work_dir=temp_dir,
                    require_binary=require_external_tools,
                )
                if gltf_tool is not None:
                    embed_ktx_textures_in_glb(draco_glb, scene, textures_dir, glb_path)
                if gltf_tool is None:
                    gate_overrides.append(
                        GateResult(
                            "glTF export",
                            "skipped",
                            "glTF Transform unavailable locally; CI produces Draco-compressed GLB",
                        )
                    )
            except (GLTFExportError, GLTFAuthoringError) as exc:
                gate_overrides.append(GateResult("glTF export", "fail", str(exc)[:700]))
        else:
            gate_overrides.append(
                GateResult(
                    "glTF export",
                    "fail" if require_external_tools else "skipped",
                    "KTX2 textures are required before GLB assembly",
                )
            )

        fbx_result: FBXExportResult | None = None
        try:
            fbx_result = export_fbx(scene, authored, fbx_path, require_binary=require_external_tools)
            if fbx_result.blender_tool is None:
                gate_overrides.append(
                    GateResult("FBX export", "skipped", "Blender unavailable locally; CI produces Twinmotion FBX")
                )
        except Exception as exc:  # Blender wraps some FBX failures as RuntimeError.
            status = "fail" if require_external_tools else "skipped"
            gate_overrides.append(GateResult("FBX export", status, str(exc)[:700]))

        if glb_path.exists():
            material_gate = validate_glb_material_workflow(glb_path, scene)
        else:
            material_gate = GateResult(
                "glTF material workflow",
                "fail" if require_external_tools else "skipped",
                "model.glb was not produced",
            )
        if texture_paths:
            texture_policy_gate = validate_texture_resolution_policy(
                scene,
                textures_dir,
                ktx_tool=ktx_tool,
                require_binary=require_external_tools,
            )
        else:
            texture_policy_gate = GateResult(
                "Texture resolution policy",
                "fail" if require_external_tools else "skipped",
                "KTX2 textures were not produced",
            )

        gate_results = [
            *gate_overrides,
            validate_gltf_validator(glb_path, three_d_dir / "gltf-validator-report.json", require_binary=require_external_tools),
            material_gate,
            validate_metallic_roughness_packing(
                scene,
                authored,
                textures_dir,
                ktx_tool=ktx_tool,
                require_binary=require_external_tools,
            ),
            validate_fbx_import(
                fbx_path,
                metadata_path,
                three_d_dir / "fbx-import-report.json",
                require_binary=require_external_tools,
            ),
            validate_usdz_size_budget_skipped(),
            texture_policy_gate,
        ]

    inventory_paths = [
        glb_path,
        fbx_path,
        metadata_path,
        three_d_dir / "gltf-validator-report.json",
        three_d_dir / "fbx-import-report.json",
        *texture_paths,
    ]
    inventory = build_file_inventory(inventory_paths, project_dir)
    summary_json, summary_md = write_gate_outputs(
        three_d_dir,
        gate_results,
        inventory,
        basename="sprint2_gate_summary",
        title="Sprint 2 Gate Summary",
        skipped_is_partial=False,
    )
    return Sprint2BundleResult(
        project_dir=project_dir,
        three_d_dir=three_d_dir,
        textures_dir=textures_dir,
        glb_path=glb_path,
        fbx_path=fbx_path,
        metadata_path=metadata_path,
        texture_paths=texture_paths,
        gate_results=tuple(gate_results),
        gate_summary_json=summary_json,
        gate_summary_md=summary_md,
    )


def generate_golden_3d_bundle(
    output_root: Path | None = None,
    *,
    require_external_tools: bool | None = None,
) -> Sprint2BundleResult:
    if require_external_tools is None:
        require_external_tools = bool(os.environ.get("CI"))
    output_root = output_root or (settings.storage_dir / "professional-deliverables")
    project = build_golden_townhouse()
    return generate_project_3d_bundle(project, output_root, require_external_tools=require_external_tools)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate the Sprint 2 golden 3D deliverable bundle.")
    parser.add_argument("--output-root", type=Path, default=settings.storage_dir / "professional-deliverables")
    parser.add_argument("--require-external-tools", action="store_true", help="Fail if Blender/KTX/glTF tooling is unavailable.")
    parser.add_argument("--allow-missing-external-tools", action="store_true", help="Allow local metadata-only generation.")
    args = parser.parse_args()
    if args.require_external_tools and args.allow_missing_external_tools:
        parser.error("--require-external-tools and --allow-missing-external-tools are mutually exclusive")
    require_external_tools = (
        True if args.require_external_tools else False if args.allow_missing_external_tools else None
    )
    result = generate_golden_3d_bundle(args.output_root, require_external_tools=require_external_tools)
    print(f"Sprint 2 golden 3D bundle: {result.project_dir}")
    print(f"3D output: {result.three_d_dir}")
    print(f"Texture output: {result.textures_dir}")
    for gate in result.gate_results:
        print(f"{gate.status.upper():7} {gate.name}: {gate.detail}")
    if not result.passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
