from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from app.db import SessionLocal
from sqlalchemy import select

from app.models import DesignVersion, ProfessionalDeliverableAsset, ProfessionalDeliverableBundle, ProfessionalDeliverableJob, Project
from app.services.design_intelligence.product_concept_adapter import ProductConceptAdapterResult, adapt_live_design_version_to_concept_source
from app.services.professional_deliverables.concept_pdf_generator import concept_sheet_specs
from app.services.professional_deliverables.demo import generate_golden_bundle, generate_project_2d_bundle
from app.services.professional_deliverables.geometry_adapter import geometry_to_drawing_project
from app.services.professional_deliverables.orchestrator import (
    mark_job_failed,
    mark_job_stage,
    mark_job_succeeded,
    output_root_for,
    register_file_artifact,
    register_skipped_artifact,
)
from app.services.professional_deliverables.scene_builder import build_scene_from_project
from app.services.professional_deliverables.sprint2_demo import generate_golden_3d_bundle, generate_project_3d_bundle
from app.services.professional_deliverables.sprint3_demo import (
    export_project_usdz_stage,
    generate_golden_ar_video_bundle,
    render_project_video_stage,
    write_project_sprint3_summary,
)
from app.tasks.worker import celery_app


REQUIRED_PRODUCT_ARTIFACTS = (
    Path("2d/bundle.pdf"),
    Path("3d/model.glb"),
    Path("3d/model.fbx"),
    Path("3d/model.usdz"),
    Path("video/master_4k.mp4"),
    Path("sprint3_gate_summary.json"),
    Path("sprint3_gate_summary.md"),
)

STALE_SPRINT4_PRODUCT_OUTPUTS = (
    Path("manifest.json"),
    Path("sprint4_gate_summary.json"),
    Path("sprint4_gate_summary.md"),
    Path("derivatives/reel_1080p.mp4"),
    Path("derivatives/reel_social.mp4"),
    Path("derivatives/hero_still_4k.png"),
    Path("derivatives/preview.gif"),
)


class ProfessionalDeliverablesTaskError(RuntimeError):
    def __init__(
        self,
        error_code: str,
        user_message: str,
        *,
        technical_message: str | None = None,
        failed_gates: list[str] | None = None,
        missing_artifacts: list[str] | None = None,
        technical_details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(technical_message or user_message)
        self.error_code = error_code
        self.user_message = user_message
        self.failed_gates = failed_gates or []
        self.missing_artifacts = missing_artifacts or []
        self.technical_details = technical_details or {}


def _gate_status(gate: Any) -> str:
    return str(getattr(gate, "status", "")).lower()


def _gate_name(gate: Any) -> str:
    return str(getattr(gate, "name", ""))


def _gate_detail(gate: Any) -> str:
    return str(getattr(gate, "detail", ""))


def _gate_line(gate: Any) -> str:
    detail = _gate_detail(gate)
    return f"{_gate_name(gate)} - {detail}" if detail else _gate_name(gate)


def _is_dwg_oda_skip(gate: Any) -> bool:
    text = f"{_gate_name(gate)} {_gate_detail(gate)}".lower()
    return "dwg" in text and ("oda" in text or "opendesign" in text or "converter" in text)


def _dwg_skip_reason(sprint1: Any) -> str | None:
    for gate in getattr(sprint1, "gate_results", ()):
        if _gate_status(gate) == "skipped" and _is_dwg_oda_skip(gate):
            return f"DWG skipped because ODA/DWG converter is unavailable: {_gate_detail(gate)}"
    return None


def _failed_master_video_gates(sprint3: Any) -> list[str]:
    failed: list[str] = []
    for gate in getattr(sprint3, "gate_results", ()):
        name = _gate_name(gate).lower()
        if name in {"master video format", "master video integrity"} and _gate_status(gate) == "fail":
            failed.append(_gate_line(gate))
    return failed


def _master_video_is_valid(sprint3: Any, master_video: Path) -> bool:
    if not master_video.exists() or master_video.stat().st_size <= 0:
        return False
    relevant = [
        gate
        for gate in getattr(sprint3, "gate_results", ())
        if _gate_name(gate).lower() in {"master video format", "master video integrity"}
    ]
    if relevant:
        return all(_gate_status(gate) == "pass" for gate in relevant)
    return any(_gate_status(gate) == "pass" for gate in getattr(sprint3, "gate_results", ()))


def _validate_master_video_boundary(root: Path, sprint3: Any) -> None:
    master_video = root / "video" / "master_4k.mp4"
    failed_gates = _failed_master_video_gates(sprint3)
    if failed_gates or not master_video.exists() or master_video.stat().st_size <= 0:
        missing = [] if master_video.exists() else ["video/master_4k.mp4"]
        raise ProfessionalDeliverablesTaskError(
            "VIDEO_MASTER_INVALID",
            "Video master render failed.",
            technical_message="; ".join(failed_gates) or "master_4k.mp4 was not produced",
            failed_gates=failed_gates,
            missing_artifacts=missing,
            technical_details={
                "output_path": str(master_video),
                "gates": [getattr(gate, "as_dict", lambda: str(gate))() for gate in getattr(sprint3, "gate_results", ())],
            },
        )


def _validate_product_outputs(root: Path, sprint1: Any, sprint2: Any, sprint3: Any) -> tuple[str, list[str]]:
    missing = [str(relative) for relative in REQUIRED_PRODUCT_ARTIFACTS if not (root / relative).exists()]
    dxf_paths = list(getattr(sprint1, "dxf_paths", []) or [])
    if not any(path.exists() for path in dxf_paths):
        missing.append("2d/*.dxf")
    if missing:
        raise ProfessionalDeliverablesTaskError(
            "MISSING_ARTIFACTS",
            "Professional deliverables are missing required artifacts.",
            technical_message="Missing required professional deliverable artifacts: " + ", ".join(missing),
            missing_artifacts=missing,
        )

    degraded_reasons: list[str] = []
    failed_gates: list[str] = []
    for gate in getattr(sprint1, "gate_results", ()):
        status = _gate_status(gate)
        if status == "fail":
            failed_gates.append(f"Sprint 1: {_gate_line(gate)}")
        elif status == "skipped":
            if _is_dwg_oda_skip(gate):
                degraded_reasons.append(f"DWG clean-open skipped because ODA/DWG converter is unavailable: {_gate_detail(gate)}")
            else:
                failed_gates.append(f"Sprint 1 skipped: {_gate_line(gate)}")

    for sprint_name, result in (("Sprint 2", sprint2), ("Sprint 3", sprint3)):
        for gate in getattr(result, "gate_results", ()):
            status = _gate_status(gate)
            if status == "fail":
                failed_gates.append(f"{sprint_name}: {_gate_line(gate)}")
            elif status == "skipped":
                if sprint_name == "Sprint 2" and _gate_name(gate) == "USDZ size budget":
                    continue
                failed_gates.append(f"{sprint_name} skipped: {_gate_line(gate)}")

    if failed_gates:
        raise ProfessionalDeliverablesTaskError(
            "VALIDATION_FAILED",
            "Professional deliverables validation failed.",
            technical_message="; ".join(failed_gates[:8]),
            failed_gates=failed_gates,
        )

    return ("partial", degraded_reasons) if degraded_reasons else ("pass", [])


def _remove_stale_sprint4_product_outputs(root: Path) -> None:
    for relative in STALE_SPRINT4_PRODUCT_OUTPUTS:
        path = root / relative
        if path.exists() and path.is_file():
            path.unlink()


def _clean_stage_dir(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def _register_file_if_exists(
    db,
    *,
    bundle: ProfessionalDeliverableBundle,
    file_path: Path | None,
    root: Path,
    asset_type: str,
    asset_role: str,
    content_type: str,
    status: str = "partial",
    metadata: dict[str, Any] | None = None,
) -> None:
    if file_path and file_path.exists() and file_path.is_file() and file_path.stat().st_size > 0:
        register_file_artifact(
            db,
            bundle=bundle,
            file_path=file_path,
            output_root=root,
            asset_type=asset_type,
            asset_role=asset_role,
            content_type=content_type,
            status=status,
            metadata=metadata,
        )


def _register_sprint1_artifacts(
    db,
    *,
    bundle: ProfessionalDeliverableBundle,
    root: Path,
    sprint1: Any,
    concept_package_metadata: dict[str, Any] | None = None,
    fallback_reason: str | None = None,
) -> None:
    sheet_metadata = _sheet_metadata_by_filename(concept_package_metadata)
    pdf_metadata = _pdf_asset_metadata(concept_package_metadata, fallback_reason)
    _register_file_if_exists(
        db,
        bundle=bundle,
        file_path=getattr(sprint1, "pdf_path", None),
        root=root,
        asset_type="2d",
        asset_role="pdf",
        content_type="application/pdf",
        metadata=pdf_metadata,
    )
    _register_file_if_exists(db, bundle=bundle, file_path=getattr(sprint1, "gate_summary_json", None), root=root, asset_type="gate_summary", asset_role="sprint1_gate_summary_json", content_type="application/json")
    _register_file_if_exists(db, bundle=bundle, file_path=getattr(sprint1, "gate_summary_md", None), root=root, asset_type="gate_summary", asset_role="sprint1_gate_summary_md", content_type="text/markdown")
    _register_file_if_exists(db, bundle=bundle, file_path=getattr(sprint1, "artifact_quality_report_json", None), root=root, asset_type="quality_report", asset_role="artifact_quality_report_json", content_type="application/json")
    _register_file_if_exists(db, bundle=bundle, file_path=getattr(sprint1, "artifact_quality_report_md", None), root=root, asset_type="quality_report", asset_role="artifact_quality_report_md", content_type="text/markdown")
    for dxf_path in getattr(sprint1, "dxf_paths", []) or []:
        _register_file_if_exists(
            db,
            bundle=bundle,
            file_path=dxf_path,
            root=root,
            asset_type="2d",
            asset_role="dxf",
            content_type="application/dxf",
            metadata=sheet_metadata.get(Path(dxf_path).name, _fallback_asset_metadata(fallback_reason)),
        )
    for dwg_path in getattr(sprint1, "dwg_paths", []) or []:
        _register_file_if_exists(db, bundle=bundle, file_path=dwg_path, root=root, asset_type="2d", asset_role="dwg", content_type="application/dwg")
    if not getattr(sprint1, "dwg_paths", []) and (reason := _dwg_skip_reason(sprint1)):
        register_skipped_artifact(db, bundle=bundle, asset_type="2d", asset_role="dwg", skip_reason=reason)


def _concept_package_metadata(adapter_result: ProductConceptAdapterResult) -> dict[str, Any] | None:
    package = adapter_result.drawing_package
    if package is None:
        return None
    sheets = [
        {
            "sheet_number": sheet.number,
            "sheet_title": sheet.title,
            "sheet_kind": sheet.kind,
            "readiness": "ready",
            "state": "ready",
            "filename": spec.filename_stem + ".dxf",
        }
        for sheet, spec in zip(package.sheets, concept_sheet_specs(package), strict=True)
    ]
    return {
        "enabled": True,
        "readiness": "ready",
        "readiness_label": "Concept 2D technical-ready; market presentation depends on visual QA gates.",
        "technical_ready": True,
        "concept_review_ready": True,
        "market_presentation_ready": False,
        "construction_ready": False,
        "fallback_reason": None,
        "source": "product_concept_adapter",
        "sheet_count": len(sheets),
        "sheets": sheets,
        "qa_bounds": package.qa_bounds,
    }


def _adapter_fallback_reason(adapter_result: ProductConceptAdapterResult) -> str | None:
    if adapter_result.is_ready:
        return None
    if adapter_result.fallback_reason:
        return adapter_result.fallback_reason
    blockers = [blocker.as_dict() for blocker in adapter_result.blocker_reasons]
    if blockers:
        codes = ", ".join(str(blocker["code"]) for blocker in blockers)
        return f"Concept 2D adapter {adapter_result.status}: {codes}"
    return f"Concept 2D adapter {adapter_result.status}"


def _sheet_metadata_by_filename(concept_package_metadata: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    if not concept_package_metadata:
        return {}
    return {
        str(sheet["filename"]): {
            "concept_package": True,
            "sheet_number": sheet["sheet_number"],
            "sheet_title": sheet["sheet_title"],
            "sheet_kind": sheet["sheet_kind"],
            "readiness": sheet["readiness"],
            "state": sheet["state"],
        }
        for sheet in concept_package_metadata.get("sheets", [])
    }


def _pdf_asset_metadata(concept_package_metadata: dict[str, Any] | None, fallback_reason: str | None) -> dict[str, Any]:
    if concept_package_metadata:
        return {
            "concept_package": True,
            "readiness": "ready",
            "state": "ready",
            "sheet_count": concept_package_metadata["sheet_count"],
            "sheets": concept_package_metadata["sheets"],
        }
    return _fallback_asset_metadata(fallback_reason)


def _fallback_asset_metadata(fallback_reason: str | None) -> dict[str, Any]:
    return {
        "concept_package": False,
        "readiness": "fallback",
        "state": "ready",
        "fallback_reason": fallback_reason,
    }


def _register_sprint2_artifacts(db, *, bundle: ProfessionalDeliverableBundle, root: Path) -> None:
    three_d_dir = root / "3d"
    _register_file_if_exists(db, bundle=bundle, file_path=three_d_dir / "model.glb", root=root, asset_type="3d", asset_role="glb", content_type="model/gltf-binary")
    _register_file_if_exists(db, bundle=bundle, file_path=three_d_dir / "model.fbx", root=root, asset_type="3d", asset_role="fbx", content_type="application/octet-stream")


def _register_usdz_stage_artifacts(db, *, bundle: ProfessionalDeliverableBundle, root: Path) -> None:
    _register_file_if_exists(db, bundle=bundle, file_path=root / "3d" / "model.usdz", root=root, asset_type="3d", asset_role="usdz", content_type="model/vnd.usdz+zip")


def _register_video_stage_artifacts(
    db,
    *,
    bundle: ProfessionalDeliverableBundle,
    root: Path,
    include_mp4: bool,
) -> None:
    if include_mp4:
        _register_file_if_exists(db, bundle=bundle, file_path=root / "video" / "master_4k.mp4", root=root, asset_type="video", asset_role="mp4", content_type="video/mp4")


def _register_sprint3_summary_artifacts(
    db,
    *,
    bundle: ProfessionalDeliverableBundle,
    root: Path,
    sprint3: Any,
) -> None:
    _register_file_if_exists(db, bundle=bundle, file_path=getattr(sprint3, "gate_summary_json", None), root=root, asset_type="gate_summary", asset_role="gate_summary_json", content_type="application/json")
    _register_file_if_exists(db, bundle=bundle, file_path=getattr(sprint3, "gate_summary_md", None), root=root, asset_type="gate_summary", asset_role="gate_summary_md", content_type="text/markdown")


def _mark_registered_assets_ready(db, bundle: ProfessionalDeliverableBundle) -> None:
    assets = db.scalars(select(ProfessionalDeliverableAsset).where(ProfessionalDeliverableAsset.bundle_id == bundle.id)).all()
    for asset in assets:
        if asset.status == "partial":
            asset.status = "ready"


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
            _remove_stale_sprint4_product_outputs(root)

            mark_job_stage(db, job, stage="adapter", progress=10, bundle=bundle)
            db.commit()

            concept_adapter = adapt_live_design_version_to_concept_source(
                project_id=project.id,
                project_name=project.name,
                brief_json=project.brief_json,
                geometry_json=version.geometry_json,
                resolved_style_params=version.resolved_style_params,
                generation_metadata=version.generation_metadata,
                version_id=version.id,
            )
            concept_package_metadata = _concept_package_metadata(concept_adapter)
            concept_fallback_reason = _adapter_fallback_reason(concept_adapter)
            bundle.runtime_metadata_json = {
                **(bundle.runtime_metadata_json or {}),
                "concept_2d": concept_package_metadata
                or {
                    "enabled": False,
                    "readiness": "fallback",
                    "fallback_reason": concept_fallback_reason,
                    "adapter_status": concept_adapter.status,
                    "blockers": [blocker.as_dict() for blocker in concept_adapter.blocker_reasons],
                },
            }
            drawing_project = geometry_to_drawing_project(
                project_id=project.id,
                project_name=project.name,
                brief_json=project.brief_json,
                geometry_json=version.geometry_json,
                version_id=version.id,
            )
            scene = build_scene_from_project(drawing_project)

            mark_job_stage(db, job, stage="export_2d", progress=25, bundle=bundle)
            db.commit()
            if concept_adapter.is_ready and concept_adapter.drawing_package is not None and concept_adapter.drawing_project is not None:
                sprint1 = generate_project_2d_bundle(
                    concept_adapter.drawing_project,
                    root.parent.parent.parent,
                    require_dwg=False,
                    project_dir=root,
                    sheets=concept_sheet_specs(concept_adapter.drawing_package),
                    concept_package_metadata=concept_package_metadata,
                )
            else:
                sprint1 = generate_project_2d_bundle(
                    drawing_project,
                    root.parent.parent.parent,
                    require_dwg=False,
                    project_dir=root,
                    concept_fallback_reason=concept_fallback_reason,
                )
            _register_sprint1_artifacts(
                db,
                bundle=bundle,
                root=root,
                sprint1=sprint1,
                concept_package_metadata=concept_package_metadata,
                fallback_reason=concept_fallback_reason,
            )
            db.commit()

            mark_job_stage(db, job, stage="export_3d", progress=50, bundle=bundle)
            db.commit()
            sprint2 = generate_project_3d_bundle(
                drawing_project,
                root.parent.parent.parent,
                require_external_tools=True,
                project_dir=root,
                scene=scene,
            )
            _register_sprint2_artifacts(db, bundle=bundle, root=root)
            db.commit()

            mark_job_stage(db, job, stage="export_usdz", progress=65, bundle=bundle)
            db.commit()
            usdz_result = export_project_usdz_stage(
                scene=scene,
                glb_path=sprint2.glb_path,
                textures_dir=sprint2.textures_dir,
                three_d_dir=sprint2.three_d_dir,
                project_dir=root,
                require_external_tools=True,
            )
            _register_usdz_stage_artifacts(db, bundle=bundle, root=root)
            db.commit()

            mark_job_stage(db, job, stage="render_video", progress=85, bundle=bundle)
            db.commit()
            video_dir = root / "video"
            _clean_stage_dir(video_dir)
            video_result = render_project_video_stage(
                scene=scene,
                glb_path=sprint2.glb_path,
                project_dir=root,
                video_dir=video_dir,
                require_external_tools=True,
            )
            sprint3 = write_project_sprint3_summary(
                project_dir=root,
                three_d_dir=sprint2.three_d_dir,
                video_dir=video_result.video_dir,
                usdz_result=usdz_result,
                video_result=video_result,
            )
            _register_sprint3_summary_artifacts(
                db,
                bundle=bundle,
                root=root,
                sprint3=sprint3,
            )
            _register_video_stage_artifacts(
                db,
                bundle=bundle,
                root=root,
                include_mp4=_master_video_is_valid(sprint3, root / "video" / "master_4k.mp4"),
            )
            db.commit()

            _validate_master_video_boundary(root, sprint3)

            mark_job_stage(db, job, stage="validate", progress=95, bundle=bundle)
            db.commit()

            quality_status, degraded_reasons = _validate_product_outputs(root, sprint1, sprint2, sprint3)
            bundle.degraded_reasons_json = degraded_reasons
            bundle.warnings_json = degraded_reasons
            _mark_registered_assets_ready(db, bundle)
            mark_job_succeeded(job, bundle=bundle, quality_status=quality_status, degraded_reasons=degraded_reasons)
            db.commit()

        except ProfessionalDeliverablesTaskError as exc:
            db.rollback()
            job = db.get(ProfessionalDeliverableJob, job_id)
            bundle = db.get(ProfessionalDeliverableBundle, job.bundle_id) if job else None
            if job and bundle:
                mark_job_failed(
                    job,
                    error_code=exc.error_code,
                    error_message=str(exc),
                    bundle=bundle,
                    failed_gates=exc.failed_gates,
                    missing_artifacts=exc.missing_artifacts,
                    technical_details=exc.technical_details,
                    user_message=exc.user_message,
                )
                db.commit()
            raise
        except Exception as exc:
            db.rollback()
            job = db.get(ProfessionalDeliverableJob, job_id)
            bundle = db.get(ProfessionalDeliverableBundle, job.bundle_id) if job else None
            if job and bundle:
                message = str(exc)
                camera_path_unsafe = message.startswith("CAMERA_PATH_UNSAFE")
                mark_job_failed(
                    job,
                    error_code="CAMERA_PATH_UNSAFE" if camera_path_unsafe else "runtime_error",
                    error_message=message,
                    bundle=bundle,
                    failed_gates=[message] if camera_path_unsafe else None,
                    technical_details={"exception_type": type(exc).__name__},
                    user_message="Camera path is unsafe for this design version." if camera_path_unsafe else "Professional deliverables failed during generation.",
                )
                db.commit()
            raise

        return {"status": "completed", "job_id": job_id, "bundle_id": bundle.id}
    finally:
        db.close()
