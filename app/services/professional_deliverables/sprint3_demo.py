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
from app.services.professional_deliverables.camera_path import build_camera_path
from app.services.professional_deliverables.golden_fixture import build_golden_townhouse
from app.services.professional_deliverables.ktx2_encoder import ExternalToolError, discover_ktx_tool
from app.services.professional_deliverables.scene_builder import build_scene_from_project
from app.services.professional_deliverables.sprint2_demo import generate_golden_3d_bundle, generate_project_3d_bundle
from app.services.professional_deliverables.usdz_converter import USDZConversionError, export_usdz_from_glb
from app.services.professional_deliverables.usdz_validators import (
    validate_usdz_material_parity,
    validate_usdz_size_budget,
    validate_usdz_structural_integrity,
    validate_usdz_texture_payload,
)
from app.services.professional_deliverables.validators import GateResult, build_file_inventory, write_gate_outputs
from app.services.professional_deliverables.video_renderer import VideoRenderError, render_master_video
from app.services.professional_deliverables.video_validators import (
    validate_camera_path_determinism,
    validate_master_video_format,
    validate_master_video_integrity,
)


@dataclass(frozen=True)
class Sprint3BundleResult:
    project_dir: Path
    three_d_dir: Path
    video_dir: Path
    usdz_path: Path
    master_video_path: Path
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
            "video_dir": str(self.video_dir),
            "usdz_path": str(self.usdz_path),
            "master_video_path": str(self.master_video_path),
            "passed": self.passed,
            "gates": [result.as_dict() for result in self.gate_results],
            "gate_summary_json": str(self.gate_summary_json),
            "gate_summary_md": str(self.gate_summary_md),
        }


def _clean_dir(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def generate_project_ar_video_bundle(
    project: DrawingProject,
    output_root: Path,
    *,
    require_external_tools: bool | None = None,
    project_dir: Path | None = None,
) -> Sprint3BundleResult:
    if require_external_tools is None:
        require_external_tools = bool(os.environ.get("CI"))
    sprint2 = generate_project_3d_bundle(
        project,
        output_root,
        require_external_tools=require_external_tools,
        project_dir=project_dir,
    )
    scene = build_scene_from_project(project)
    project_dir = sprint2.project_dir
    three_d_dir = sprint2.three_d_dir
    textures_dir = sprint2.textures_dir
    video_dir = project_dir / "video"
    _clean_dir(video_dir)

    gate_overrides: list[GateResult] = []
    usdz_path = three_d_dir / "model.usdz"
    master_video_path = video_dir / "master_4k.mp4"
    camera_path = build_camera_path(scene)
    if camera_path.collision_warnings:
        gate_overrides.append(
            GateResult(
                "Camera collision sanity",
                "fail",
                "; ".join(camera_path.collision_warnings[:8]),
            )
        )
    else:
        gate_overrides.append(GateResult("Camera collision sanity", "pass", "0 camera keyframes intersect wall bounding boxes"))

    try:
        ktx_tool = discover_ktx_tool(require_binary=require_external_tools)
    except ExternalToolError as exc:
        ktx_tool = None
        gate_overrides.append(GateResult("USDZ texture payload build", "fail" if require_external_tools else "skipped", str(exc)))

    if ktx_tool is not None and sprint2.glb_path.exists():
        try:
            export_usdz_from_glb(
                scene,
                sprint2.glb_path,
                textures_dir,
                three_d_dir,
                ktx_tool=ktx_tool,
                require_external_tools=require_external_tools,
            )
        except USDZConversionError as exc:
            gate_overrides.append(GateResult("USDZ export", "fail" if require_external_tools else "skipped", str(exc)[:700]))
    else:
        gate_overrides.append(
            GateResult(
                "USDZ export",
                "fail" if require_external_tools else "skipped",
                "Sprint 2 GLB and KTX2 textures are required before USDZ export",
            )
        )

    with tempfile.TemporaryDirectory(prefix="sprint3-video-") as temp_name:
        temp_dir = Path(temp_name)
        second_video: Path | None = None
        try:
            rendered = render_master_video(
                sprint2.glb_path,
                scene,
                camera_path,
                video_dir,
                temp_dir / "first",
                require_external_tools=require_external_tools,
            )
            if rendered is None:
                gate_overrides.append(
                    GateResult("Master video render", "skipped", "Blender/ffmpeg unavailable locally; CI renders video")
                )
            else:
                second_video_dir = temp_dir / "second-video"
                second_video = render_master_video(
                    sprint2.glb_path,
                    scene,
                    camera_path,
                    second_video_dir,
                    temp_dir / "second",
                    require_external_tools=require_external_tools,
                )
        except VideoRenderError as exc:
            rendered = None
            second_video = None
            gate_overrides.append(GateResult("Master video render", "fail" if require_external_tools else "skipped", str(exc)[:700]))

        gate_results = [
            *gate_overrides,
            validate_usdz_size_budget(usdz_path, three_d_dir / "usdz-budget-report.json", require_binary=require_external_tools),
            validate_usdz_structural_integrity(
                usdz_path,
                three_d_dir / "usdz-structural-report.json",
                require_binary=require_external_tools,
            ),
            validate_usdz_material_parity(
                sprint2.glb_path,
                usdz_path,
                scene,
                three_d_dir / "usdz-material-parity-report.json",
                require_binary=require_external_tools,
            ),
            validate_usdz_texture_payload(
                usdz_path,
                three_d_dir / "usdz-texture-report.json",
                require_binary=require_external_tools,
            ),
            validate_master_video_format(
                master_video_path,
                video_dir / "ffprobe-master-report.json",
                require_binary=require_external_tools,
            ),
            validate_master_video_integrity(
                master_video_path,
                video_dir / "video-integrity-report.json",
                require_binary=require_external_tools,
            ),
            validate_camera_path_determinism(
                master_video_path,
                second_video if second_video is not None else temp_dir / "missing-second.mp4",
                video_dir / "video-determinism-report.json",
                require_binary=require_external_tools,
            ),
        ]

    inventory_paths = [
        three_d_dir / "model.glb",
        three_d_dir / "model.fbx",
        usdz_path,
        three_d_dir / "model_lite.usdz",
        three_d_dir / "model_lite.usd",
        three_d_dir / "usdz-budget-report.json",
        three_d_dir / "usdz-structural-report.json",
        three_d_dir / "usdz-material-parity-report.json",
        three_d_dir / "usdz-texture-report.json",
        master_video_path,
        video_dir / "camera_path.json",
        video_dir / "ffprobe-master-report.json",
        video_dir / "video-integrity-report.json",
        video_dir / "video-determinism-report.json",
    ]
    inventory = build_file_inventory(inventory_paths, project_dir)
    summary_json, summary_md = write_gate_outputs(
        project_dir,
        gate_results,
        inventory,
        basename="sprint3_gate_summary",
        title="Sprint 3 Gate Summary",
        skipped_is_partial=True,
    )
    return Sprint3BundleResult(
        project_dir=project_dir,
        three_d_dir=three_d_dir,
        video_dir=video_dir,
        usdz_path=usdz_path,
        master_video_path=master_video_path,
        gate_results=tuple(gate_results),
        gate_summary_json=summary_json,
        gate_summary_md=summary_md,
    )


def generate_golden_ar_video_bundle(
    output_root: Path | None = None,
    *,
    require_external_tools: bool | None = None,
) -> Sprint3BundleResult:
    if require_external_tools is None:
        require_external_tools = bool(os.environ.get("CI"))
    output_root = output_root or (settings.storage_dir / "professional-deliverables")
    project = build_golden_townhouse()
    return generate_project_ar_video_bundle(project, output_root, require_external_tools=require_external_tools)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate the Sprint 3 golden AR/video deliverable bundle.")
    parser.add_argument("--output-root", type=Path, default=settings.storage_dir / "professional-deliverables")
    parser.add_argument("--require-external-tools", action="store_true", help="Fail if Blender/KTX/USD/ffmpeg tooling is unavailable.")
    parser.add_argument("--allow-missing-external-tools", action="store_true", help="Allow local metadata-only generation.")
    args = parser.parse_args()
    if args.require_external_tools and args.allow_missing_external_tools:
        parser.error("--require-external-tools and --allow-missing-external-tools are mutually exclusive")
    require_external_tools = True if args.require_external_tools else False if args.allow_missing_external_tools else None
    result = generate_golden_ar_video_bundle(args.output_root, require_external_tools=require_external_tools)
    print(f"Sprint 3 golden AR/video bundle: {result.project_dir}")
    print(f"3D output: {result.three_d_dir}")
    print(f"Video output: {result.video_dir}")
    for gate in result.gate_results:
        print(f"{gate.status.upper():7} {gate.name}: {gate.detail}")
    if not result.passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
