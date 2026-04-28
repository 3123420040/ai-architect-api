from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import (
    DesignVersion,
    ProfessionalDeliverableAsset,
    ProfessionalDeliverableBundle,
    ProfessionalDeliverableJob,
    Project,
    User,
)
from app.services.storage import file_checksum, resolve_browser_asset_url


def create_professional_bundle_job(
    db: Session,
    *,
    project: Project,
    version: DesignVersion,
    current_user: User,
) -> tuple[ProfessionalDeliverableBundle, ProfessionalDeliverableJob]:
    bundle = ProfessionalDeliverableBundle(
        project_id=project.id,
        version_id=version.id,
        status="queued",
        quality_status="pending",
        created_by=current_user.id,
    )
    db.add(bundle)
    db.flush()

    job = ProfessionalDeliverableJob(
        bundle_id=bundle.id,
        job_type="generate_professional_bundle",
        status="queued",
        stage="queued",
        progress_percent=0,
    )
    db.add(job)
    db.flush()

    version.current_professional_deliverable_bundle_id = bundle.id
    return bundle, job


def queue_professional_bundle_job(job_id: str):
    from app.tasks.professional_deliverables import run_professional_deliverable_bundle_task

    return run_professional_deliverable_bundle_task.apply_async(
        args=[job_id],
        queue="professional_deliverables",
    )


def get_latest_bundle_for_version(db: Session, version_id: str) -> ProfessionalDeliverableBundle | None:
    return db.scalar(
        select(ProfessionalDeliverableBundle)
        .where(ProfessionalDeliverableBundle.version_id == version_id)
        .order_by(ProfessionalDeliverableBundle.created_at.desc())
    )


def get_bundle_or_404(db: Session, bundle_id: str) -> ProfessionalDeliverableBundle:
    bundle = db.get(ProfessionalDeliverableBundle, bundle_id)
    if not bundle:
        raise HTTPException(status_code=404, detail="Professional deliverable bundle not found")
    return bundle


def get_job_or_404(db: Session, job_id: str) -> ProfessionalDeliverableJob:
    job = db.get(ProfessionalDeliverableJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Professional deliverable job not found")
    return job


def serialize_job(job: ProfessionalDeliverableJob) -> dict[str, Any]:
    return {
        "job_id": job.id,
        "bundle_id": job.bundle_id,
        "status": job.status,
        "stage": job.stage,
        "progress_percent": job.progress_percent,
        "attempt_count": job.attempt_count,
        "error_code": job.error_code,
        "error_message": job.error_message,
    }


def serialize_bundle(bundle: ProfessionalDeliverableBundle) -> dict[str, Any]:
    latest_job = max(bundle.jobs, key=lambda item: item.created_at, default=None)
    assets = list(bundle.assets)
    retryable = bool(latest_job and latest_job.status == "failed")
    return {
        "bundle_id": bundle.id,
        "version_id": bundle.version_id,
        "status": bundle.status,
        "quality_status": bundle.quality_status,
        "is_degraded": bundle.is_degraded,
        "degraded_reasons": bundle.degraded_reasons_json or [],
        "failed_gates": bundle.failed_gates_json or [],
        "warnings": bundle.warnings_json or [],
        "missing_artifacts": bundle.missing_artifacts_json or [],
        "retryable": retryable,
        "user_message": bundle.user_message,
        "technical_details": bundle.technical_details_json or {},
        "assets": [
            {
                "url": resolve_browser_asset_url(asset.public_url) or asset.public_url,
                "asset_type": asset.asset_type,
                "asset_role": asset.asset_role,
                "content_type": asset.content_type,
                "byte_size": asset.byte_size,
                "status": asset.status,
                "skip_reason": asset.skip_reason,
                "validation_error": asset.validation_error,
            }
            for asset in assets
        ],
        "current_job": serialize_job(latest_job) if latest_job else None,
        "updated_at": bundle.updated_at,
    }


STAGE_PROGRESS = {
    "queued": 0,
    "adapter": 10,
    "export_2d": 25,
    "export_3d": 50,
    "export_usdz": 65,
    "render_video": 85,
    "validate": 95,
    "ready": 100,
}


def mark_job_stage(db: Session, job: ProfessionalDeliverableJob, *, stage: str, progress: int | None = None, bundle: ProfessionalDeliverableBundle | None = None) -> None:
    job.stage = stage
    job.progress_percent = progress if progress is not None else STAGE_PROGRESS.get(stage, 0)
    job.status = "running"
    if job.started_at is None:
        job.started_at = datetime.now(timezone.utc)
    if bundle is not None:
        bundle.status = "running"


def mark_job_succeeded(
    job: ProfessionalDeliverableJob,
    *,
    bundle: ProfessionalDeliverableBundle,
    quality_status: str = "pass",
    degraded_reasons: list[str] | None = None,
) -> None:
    job.status = "succeeded"
    job.stage = "ready"
    job.progress_percent = 100
    job.finished_at = datetime.now(timezone.utc)
    bundle.status = "ready"
    bundle.quality_status = quality_status
    bundle.is_degraded = quality_status == "partial"
    bundle.degraded_reasons_json = degraded_reasons or []
    bundle.user_message = "Professional deliverables are ready." if quality_status == "pass" else "Professional deliverables are ready with warnings."


def mark_job_failed(
    job: ProfessionalDeliverableJob,
    *,
    error_code: str,
    error_message: str,
    bundle: ProfessionalDeliverableBundle,
    failed_gates: list[str] | None = None,
    missing_artifacts: list[str] | None = None,
    technical_details: dict[str, Any] | None = None,
    user_message: str | None = None,
) -> None:
    job.status = "failed"
    job.error_code = error_code
    job.error_message = error_message[:4000] if error_message else None
    job.finished_at = datetime.now(timezone.utc)
    bundle.status = "failed"
    bundle.quality_status = "partial" if bundle.assets else "fail"
    bundle.is_degraded = bool(bundle.assets)
    bundle.failed_gates_json = failed_gates or bundle.failed_gates_json or []
    bundle.missing_artifacts_json = missing_artifacts or bundle.missing_artifacts_json or []
    bundle.technical_details_json = technical_details or bundle.technical_details_json or {}
    bundle.user_message = user_message or "Professional deliverables failed before the final bundle was ready."
    if job.progress_percent < 10:
        job.progress_percent = 0


def output_root_for(project_id: str, version_id: str) -> Path:
    return settings.storage_dir / "professional-deliverables" / "projects" / project_id / "versions" / version_id


def register_file_artifact(
    db: Session,
    *,
    bundle: ProfessionalDeliverableBundle,
    file_path: Path,
    output_root: Path,
    asset_type: str,
    asset_role: str,
    content_type: str,
    status: str = "ready",
    validation_error: str | None = None,
) -> ProfessionalDeliverableAsset:
    if not file_path.exists() or not file_path.is_file() or file_path.stat().st_size <= 0:
        raise FileNotFoundError(str(file_path))
    try:
        relative = file_path.relative_to(settings.storage_dir)
    except ValueError:
        relative = file_path
    public_url = f"/media/{relative}" if not str(relative).startswith("/") else f"/media/{relative}"
    byte_size = file_path.stat().st_size if file_path.exists() else 0
    storage_key = str(file_path)
    existing = db.scalar(
        select(ProfessionalDeliverableAsset).where(
            ProfessionalDeliverableAsset.bundle_id == bundle.id,
            ProfessionalDeliverableAsset.asset_role == asset_role,
            ProfessionalDeliverableAsset.storage_key == storage_key,
        )
    )
    checksum = file_checksum(file_path.read_bytes())
    if existing:
        existing.asset_type = asset_type
        existing.public_url = public_url
        existing.content_type = content_type
        existing.byte_size = byte_size
        existing.status = status
        existing.validation_error = validation_error
        existing.checksum = checksum
        db.flush()
        return existing
    asset = ProfessionalDeliverableAsset(
        bundle_id=bundle.id,
        asset_type=asset_type,
        asset_role=asset_role,
        storage_key=storage_key,
        public_url=public_url,
        content_type=content_type,
        byte_size=byte_size,
        status=status,
        validation_error=validation_error,
        checksum=checksum,
    )
    db.add(asset)
    db.flush()
    return asset


def register_skipped_artifact(
    db: Session,
    *,
    bundle: ProfessionalDeliverableBundle,
    asset_type: str,
    asset_role: str,
    skip_reason: str,
) -> ProfessionalDeliverableAsset:
    existing = db.scalar(
        select(ProfessionalDeliverableAsset).where(
            ProfessionalDeliverableAsset.bundle_id == bundle.id,
            ProfessionalDeliverableAsset.asset_role == asset_role,
            ProfessionalDeliverableAsset.status == "skipped",
        )
    )
    if existing:
        existing.skip_reason = skip_reason
        db.flush()
        return existing
    asset = ProfessionalDeliverableAsset(
        bundle_id=bundle.id,
        asset_type=asset_type,
        asset_role=asset_role,
        storage_key="",
        public_url="",
        content_type="application/octet-stream",
        byte_size=0,
        status="skipped",
        skip_reason=skip_reason,
    )
    db.add(asset)
    db.flush()
    return asset
