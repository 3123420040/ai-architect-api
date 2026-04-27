from __future__ import annotations

from pathlib import Path
from typing import Any

from app.db import SessionLocal
from app.models import DesignVersion, ProfessionalDeliverableBundle, ProfessionalDeliverableJob, Project
from app.services.professional_deliverables.demo import generate_golden_bundle, generate_project_2d_bundle
from app.services.professional_deliverables.geometry_adapter import geometry_to_drawing_project
from app.services.professional_deliverables.manifest_builder import build_manifest
from app.services.professional_deliverables.orchestrator import (
    mark_job_failed,
    mark_job_stage,
    mark_job_succeeded,
    output_root_for,
    register_file_artifact,
)
from app.services.professional_deliverables.sprint3_demo import generate_golden_ar_video_bundle, generate_project_ar_video_bundle
from app.services.professional_deliverables.sprint2_demo import generate_golden_3d_bundle, generate_project_3d_bundle
from app.services.professional_deliverables.sprint4_validators import run_sprint4_gates
from app.services.professional_deliverables.video_derivatives import derive_sprint4_video_outputs
from app.tasks.worker import celery_app


REQUIRED_PRODUCT_ARTIFACTS = (
    Path("2d/bundle.pdf"),
    Path("3d/model.glb"),
    Path("3d/model.fbx"),
    Path("3d/model.usdz"),
    Path("video/master_4k.mp4"),
    Path("video/reel_9x16_1080p.mp4"),
    Path("derivatives/hero_still_4k.png"),
    Path("derivatives/preview.gif"),
    Path("manifest.json"),
    Path("sprint3_gate_summary.json"),
    Path("sprint3_gate_summary.md"),
    Path("sprint4_gate_summary.json"),
    Path("sprint4_gate_summary.md"),
)


def _gate_status(gate: Any) -> str:
    return str(getattr(gate, "status", "")).lower()


def _gate_name(gate: Any) -> str:
    return str(getattr(gate, "name", ""))


def _gate_detail(gate: Any) -> str:
    return str(getattr(gate, "detail", ""))


def _is_dwg_oda_skip(gate: Any) -> bool:
    text = f"{_gate_name(gate)} {_gate_detail(gate)}".lower()
    return "dwg" in text and ("oda" in text or "opendesign" in text or "converter" in text)


def _validate_product_outputs(root: Path, sprint1: Any, sprint2: Any, sprint3: Any, sprint4_gates: list[Any]) -> tuple[str, list[str]]:
    missing = [str(relative) for relative in REQUIRED_PRODUCT_ARTIFACTS if not (root / relative).exists()]
    dxf_paths = list(getattr(sprint1, "dxf_paths", []) or [])
    if not any(path.exists() for path in dxf_paths):
        missing.append("2d/*.dxf")
    if missing:
        raise RuntimeError("Missing required professional deliverable artifacts: " + ", ".join(missing))

    degraded_reasons: list[str] = []
    for gate in getattr(sprint1, "gate_results", ()):
        status = _gate_status(gate)
        if status == "fail":
            raise RuntimeError(f"Sprint 1 gate failed: {_gate_name(gate)} - {_gate_detail(gate)}")
        if status == "skipped":
            if _is_dwg_oda_skip(gate):
                degraded_reasons.append(f"DWG clean-open skipped because ODA/DWG converter is unavailable: {_gate_detail(gate)}")
            else:
                raise RuntimeError(f"Sprint 1 gate skipped: {_gate_name(gate)} - {_gate_detail(gate)}")

    for sprint_name, result in (("Sprint 2", sprint2), ("Sprint 3", sprint3)):
        for gate in getattr(result, "gate_results", ()):
            status = _gate_status(gate)
            if status == "fail":
                raise RuntimeError(f"{sprint_name} gate failed: {_gate_name(gate)} - {_gate_detail(gate)}")
            if status == "skipped":
                if sprint_name == "Sprint 2" and _gate_name(gate) == "USDZ size budget":
                    continue
                raise RuntimeError(f"{sprint_name} gate skipped: {_gate_name(gate)} - {_gate_detail(gate)}")

    for gate in sprint4_gates:
        status = _gate_status(gate)
        if status == "fail":
            raise RuntimeError(f"Sprint 4 gate failed: {_gate_name(gate)} - {_gate_detail(gate)}")
        if status == "skipped":
            raise RuntimeError(f"Sprint 4 gate skipped: {_gate_name(gate)} - {_gate_detail(gate)}")

    return ("partial", degraded_reasons) if degraded_reasons else ("pass", [])


@celery_app.task(name="professional_deliverables.sprint1_golden_bundle")
def run_sprint1_golden_bundle_task(output_root: str | None = None, require_dwg: bool = True) -> dict:
    result = generate_golden_bundle(Path(output_root) if output_root else None, require_dwg=require_dwg)
    return result.as_dict()


@celery_app.task(name="professional_deliverables.sprint2_golden_3d_bundle")
def run_sprint2_golden_3d_bundle_task(output_root: str | None = None, require_external_tools: bool = True) -> dict:
    result = generate_golden_3d_bundle(
        Path(output_root) if output_root else None,
        require_external_tools=require_external_tools,
    )
    return result.as_dict()


@celery_app.task(name="professional_deliverables.sprint3_golden_ar_video_bundle")
def run_sprint3_golden_ar_video_bundle_task(output_root: str | None = None, require_external_tools: bool = True) -> dict:
    result = generate_golden_ar_video_bundle(
        Path(output_root) if output_root else None,
        require_external_tools=require_external_tools,
    )
    return result.as_dict()


@celery_app.task(name="professional_deliverables.run_project_bundle")
def run_professional_deliverable_bundle_task(job_id: str) -> dict:
    db = SessionLocal()
    try:
        job = db.get(ProfessionalDeliverableJob, job_id)
        if not job:
            raise RuntimeError("Professional deliverable job not found")
        bundle = db.get(ProfessionalDeliverableBundle, job.bundle_id)
        if not bundle:
            raise RuntimeError("Professional deliverable bundle not found")

        try:
            version = db.get(DesignVersion, bundle.version_id)
            if not version:
                raise RuntimeError("Source version not found")
            project = db.get(Project, bundle.project_id)
            if not project:
                raise RuntimeError("Project not found")

            job.attempt_count += 1
            root = output_root_for(project.id, version.id)
            root.mkdir(parents=True, exist_ok=True)

            mark_job_stage(db, job, stage="adapter", progress=10, bundle=bundle)
            db.commit()

            drawing_project = geometry_to_drawing_project(
                project_id=project.id,
                project_name=project.name,
                brief_json=project.brief_json,
                geometry_json=version.geometry_json,
            )

            mark_job_stage(db, job, stage="export_2d", progress=25, bundle=bundle)
            db.commit()

            sprint1 = generate_project_2d_bundle(
                drawing_project,
                root.parent.parent.parent,
                require_dwg=False,
                project_dir=root,
            )

            mark_job_stage(db, job, stage="export_3d", progress=50, bundle=bundle)
            db.commit()

            sprint2 = generate_project_3d_bundle(
                drawing_project,
                root.parent.parent.parent,
                require_external_tools=True,
                project_dir=root,
            )

            mark_job_stage(db, job, stage="export_usdz", progress=65, bundle=bundle)
            db.commit()

            mark_job_stage(db, job, stage="render_video", progress=85, bundle=bundle)
            db.commit()

            sprint3 = generate_project_ar_video_bundle(
                drawing_project,
                root.parent.parent.parent,
                require_external_tools=True,
                project_dir=root,
            )

            mark_job_stage(db, job, stage="derive_reel", progress=90, bundle=bundle)
            db.commit()

            sprint4_outputs = derive_sprint4_video_outputs(root)

            mark_job_stage(db, job, stage="build_manifest", progress=97, bundle=bundle)
            db.commit()

            manifest_path = build_manifest(
                root,
                project_id=project.id,
                source_brief=project.brief_json,
            )
            sprint4_gates, sprint4_summary_json, sprint4_summary_md = run_sprint4_gates(root)

            mark_job_stage(db, job, stage="validate", progress=99, bundle=bundle)
            db.commit()

            quality_status, degraded_reasons = _validate_product_outputs(root, sprint1, sprint2, sprint3, sprint4_gates)
            if degraded_reasons:
                manifest_path = build_manifest(
                    root,
                    project_id=project.id,
                    source_brief=project.brief_json,
                    degraded_reasons=degraded_reasons,
                )
                sprint4_gates, sprint4_summary_json, sprint4_summary_md = run_sprint4_gates(root)
                quality_status, degraded_reasons = _validate_product_outputs(root, sprint1, sprint2, sprint3, sprint4_gates)

            artifact_mappings = [
                (sprint1.pdf_path, "2d", "pdf", "application/pdf"),
                (sprint1.gate_summary_json, "gate_summary", "sprint1_gate_summary_json", "application/json"),
                (sprint1.gate_summary_md, "gate_summary", "sprint1_gate_summary_md", "text/markdown"),
                (sprint3.gate_summary_json, "gate_summary", "gate_summary_json", "application/json"),
                (sprint3.gate_summary_md, "gate_summary", "gate_summary_md", "text/markdown"),
                (sprint4_outputs["reel"], "video", "marketing_reel", "video/mp4"),
                (sprint4_outputs["hero_still"], "derivative", "hero_still", "image/png"),
                (sprint4_outputs["gif_preview"], "derivative", "gif_preview", "image/gif"),
                (manifest_path, "manifest", "manifest", "application/json"),
                (sprint4_summary_json, "gate_summary", "sprint4_gate_summary_json", "application/json"),
                (sprint4_summary_md, "gate_summary", "sprint4_gate_summary_md", "text/markdown"),
            ]
            for dxf_path in sprint1.dxf_paths:
                artifact_mappings.append((dxf_path, "2d", "dxf", "application/dxf"))
            for dwg_path in sprint1.dwg_paths:
                artifact_mappings.append((dwg_path, "2d", "dwg", "application/dwg"))

            two_d_dir = root / "2d"
            three_d_dir = root / "3d"
            video_dir = root / "video"

            for candidate, asset_type, asset_role, content_type in [
                (three_d_dir / "model.glb", "3d", "glb", "model/gltf-binary"),
                (three_d_dir / "model.fbx", "3d", "fbx", "application/octet-stream"),
                (three_d_dir / "model.usdz", "3d", "usdz", "model/vnd.usdz+zip"),
                (video_dir / "master_4k.mp4", "video", "mp4", "video/mp4"),
            ]:
                if candidate.exists():
                    artifact_mappings.append((candidate, asset_type, asset_role, content_type))

            for file_path, asset_type, asset_role, content_type in artifact_mappings:
                if file_path.exists():
                    register_file_artifact(
                        db,
                        bundle=bundle,
                        file_path=file_path,
                        output_root=root,
                        asset_type=asset_type,
                        asset_role=asset_role,
                        content_type=content_type,
                    )

            mark_job_succeeded(job, bundle=bundle, quality_status=quality_status, degraded_reasons=degraded_reasons)
            db.commit()

        except Exception as exc:
            db.rollback()
            job = db.get(ProfessionalDeliverableJob, job_id)
            bundle = db.get(ProfessionalDeliverableBundle, job.bundle_id) if job else None
            if job and bundle:
                mark_job_failed(job, error_code="runtime_error", error_message=str(exc), bundle=bundle)
                db.commit()
            raise

        return {"status": "completed", "job_id": job_id, "bundle_id": bundle.id}
    finally:
        db.close()
