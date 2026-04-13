from __future__ import annotations

from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import DesignVersion, Presentation3DBundle, Presentation3DJob, Project
from app.services.gpu_client import render_presentation_bundle
from app.services.presentation_3d.asset_registry import register_artifact
from app.services.presentation_3d.eligibility import get_current_issued_package
from app.services.presentation_3d.job_tracker import mark_job_failed, mark_job_stage, mark_job_succeeded
from app.services.presentation_3d.manifest import build_presentation_manifest
from app.services.presentation_3d.qa import build_qa_report
from app.services.presentation_3d.scene_spec_builder import build_presentation_scene_spec
from app.tasks.worker import celery_app


def _run(db: Session, job: Presentation3DJob, bundle: Presentation3DBundle) -> None:
    version = db.get(DesignVersion, bundle.version_id)
    if not version:
        raise RuntimeError("Source version not found")
    project = db.get(Project, bundle.project_id)
    if not project:
        raise RuntimeError("Project not found")

    job.attempt_count += 1
    issued_package = get_current_issued_package(db, version.id)

    mark_job_stage(job, stage="scene_spec", progress_percent=10, bundle=bundle)
    db.commit()

    scene_spec = build_presentation_scene_spec(
        project=project,
        version=version,
        issued_package=issued_package,
        presentation_mode=(bundle.runtime_metadata_json or {}).get("presentation_mode", "client_presentation"),
    )
    scene_spec_asset = register_artifact(
        db,
        bundle=bundle,
        artifact={
            "asset_type": "scene_spec",
            "asset_role": "scene_spec",
            "filename": "scene_spec.json",
            "content_type": "application/json",
            "json_payload": scene_spec,
        },
    )
    bundle.scene_spec_url = scene_spec_asset.public_url
    db.commit()

    mark_job_stage(job, stage="runtime_dispatch", progress_percent=30, bundle=bundle)
    db.commit()
    runtime_payload = render_presentation_bundle(
        bundle_id=bundle.id,
        scene_spec=scene_spec,
        render_preset=(bundle.runtime_metadata_json or {}).get("presentation_mode", "client_presentation"),
    )

    mark_job_stage(job, stage="output_ingest", progress_percent=70, bundle=bundle)
    db.commit()
    for artifact in runtime_payload.get("artifacts", []):
        register_artifact(db, bundle=bundle, artifact=artifact)
    bundle.runtime_metadata_json = {
        **(bundle.runtime_metadata_json or {}),
        **(runtime_payload.get("runtime_metadata") or {}),
    }
    db.commit()

    version_assets = list(bundle.assets)
    glb_asset = next((asset for asset in version_assets if asset.asset_role == "scene_glb"), None)
    if glb_asset:
        version.model_url = glb_asset.public_url
    version.render_urls = [asset.public_url for asset in version_assets if asset.asset_type == "render"]
    db.commit()

    mark_job_stage(job, stage="qa", progress_percent=85, bundle=bundle)
    db.commit()
    qa_report = build_qa_report(bundle, list(bundle.assets), scene_spec)
    qa_asset = register_artifact(
        db,
        bundle=bundle,
        artifact={
            "asset_type": "qa",
            "asset_role": "qa_report",
            "filename": "qa_report.json",
            "content_type": "application/json",
            "json_payload": qa_report,
        },
    )
    bundle.qa_report_url = qa_asset.public_url
    bundle.qa_status = qa_report["status"]
    bundle.is_degraded = qa_report["status"] == "fail"
    bundle.degraded_reasons_json = qa_report.get("blocking_issues", [])
    bundle.approval_status = "awaiting_approval" if qa_report["status"] in {"pass", "warning"} else "not_requested"
    bundle.delivery_status = "preview_only" if qa_report["status"] in {"pass", "warning"} else "blocked"
    db.commit()

    mark_job_stage(job, stage="manifest", progress_percent=95, bundle=bundle)
    db.commit()
    manifest = build_presentation_manifest(
        project=project,
        version=version,
        bundle=bundle,
        assets=list(bundle.assets),
        qa_report=qa_report,
    )
    manifest_asset = register_artifact(
        db,
        bundle=bundle,
        artifact={
            "asset_type": "manifest",
            "asset_role": "presentation_manifest",
            "filename": "presentation_manifest.json",
            "content_type": "application/json",
            "json_payload": manifest,
        },
    )
    bundle.manifest_url = manifest_asset.public_url
    db.commit()

    if bundle.qa_status == "fail":
        bundle.status = "failed"
        job.status = "succeeded"
        job.stage = "manifest"
        job.progress_percent = 100
        db.commit()
        return

    bundle.approval_status = "awaiting_approval"
    mark_job_succeeded(job, bundle=bundle)
    db.commit()


@celery_app.task(name="presentation_3d.run_bundle")
def run_presentation_3d_bundle_task(job_id: str) -> dict:
    db = SessionLocal()
    try:
        job = db.get(Presentation3DJob, job_id)
        if not job:
            raise RuntimeError("3D job not found")
        bundle = db.get(Presentation3DBundle, job.bundle_id)
        if not bundle:
            raise RuntimeError("3D bundle not found")

        try:
            _run(db, job, bundle)
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            job = db.get(Presentation3DJob, job_id)
            bundle = db.get(Presentation3DBundle, job.bundle_id) if job else None
            if job and bundle:
                mark_job_failed(job, error_code="runtime_error", error_message=str(exc), bundle=bundle)
                db.commit()
            raise

        return {"status": "completed", "job_id": job_id, "bundle_id": bundle.id}
    finally:
        db.close()
