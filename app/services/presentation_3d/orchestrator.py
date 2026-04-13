from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    DesignVersion,
    Presentation3DApproval,
    Presentation3DAsset,
    Presentation3DBundle,
    Presentation3DJob,
    Project,
    User,
)
from app.tasks.presentation_3d import run_presentation_3d_bundle_task


def create_bundle_job(
    db: Session,
    *,
    project: Project,
    version: DesignVersion,
    current_user: User,
    payload: dict[str, Any],
) -> tuple[Presentation3DBundle, Presentation3DJob]:
    bundle = Presentation3DBundle(
        project_id=project.id,
        version_id=version.id,
        scene_spec_revision="v1",
        status="queued",
        qa_status="pending",
        approval_status="not_requested",
        delivery_status="preview_only",
        created_by=current_user.id,
        runtime_metadata_json={
            "presentation_mode": payload.get("presentation_mode", "client_presentation"),
            "requested_outputs": payload.get("requested_outputs") or {},
            "priority": payload.get("priority", "standard"),
        },
    )
    db.add(bundle)
    db.flush()

    job = Presentation3DJob(
        bundle_id=bundle.id,
        job_type="generate_bundle",
        status="queued",
        stage="scene_spec",
        progress_percent=0,
    )
    db.add(job)
    db.flush()

    version.current_presentation_3d_bundle_id = bundle.id
    return bundle, job


def queue_bundle_job(job_id: str):
    return run_presentation_3d_bundle_task.delay(job_id)


def get_latest_bundle_for_version(db: Session, version_id: str) -> Presentation3DBundle | None:
    return db.scalar(
        select(Presentation3DBundle)
        .where(Presentation3DBundle.version_id == version_id)
        .order_by(Presentation3DBundle.created_at.desc())
    )


def get_bundle_or_404(db: Session, bundle_id: str) -> Presentation3DBundle:
    bundle = db.get(Presentation3DBundle, bundle_id)
    if not bundle:
        raise HTTPException(status_code=404, detail="3D bundle not found")
    return bundle


def get_job_or_404(db: Session, job_id: str) -> Presentation3DJob:
    job = db.get(Presentation3DJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="3D job not found")
    return job


def _group_assets(assets: list[Presentation3DAsset]) -> dict[str, Any]:
    scene_glb = next((asset for asset in assets if asset.asset_role == "scene_glb"), None)
    video = next((asset for asset in assets if asset.asset_role == "walkthrough_video"), None)
    manifest = next((asset for asset in assets if asset.asset_role == "presentation_manifest"), None)
    qa_report = next((asset for asset in assets if asset.asset_role == "qa_report"), None)

    def _summary(asset: Presentation3DAsset | None) -> dict[str, Any] | None:
        if not asset:
            return None
        return {
            "url": asset.public_url,
            "checksum": asset.checksum,
            "asset_role": asset.asset_role,
            "width": asset.width,
            "height": asset.height,
            "duration_seconds": float(asset.duration_seconds) if asset.duration_seconds is not None else None,
            "content_type": asset.content_type,
            "shot_id": (asset.metadata_json or {}).get("shot_id"),
        }

    stills = sorted(
        [
            {
                "url": asset.public_url,
                "checksum": asset.checksum,
                "asset_role": asset.asset_role,
                "width": asset.width,
                "height": asset.height,
                "shot_id": (asset.metadata_json or {}).get("shot_id"),
                "content_type": asset.content_type,
            }
            for asset in assets
            if asset.asset_type == "render"
        ],
        key=lambda item: item.get("shot_id") or "",
    )

    return {
        "scene_glb": _summary(scene_glb),
        "stills": stills,
        "walkthrough_video": _summary(video),
        "manifest": _summary(manifest),
        "qa_report": _summary(qa_report),
    }


def serialize_job(job: Presentation3DJob) -> dict[str, Any]:
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


def serialize_bundle(bundle: Presentation3DBundle) -> dict[str, Any]:
    latest_job = max(bundle.jobs, key=lambda item: item.created_at, default=None)
    return {
        "bundle_id": bundle.id,
        "version_id": bundle.version_id,
        "status": bundle.status,
        "qa_status": bundle.qa_status,
        "approval_status": bundle.approval_status,
        "delivery_status": bundle.delivery_status,
        "is_degraded": bundle.is_degraded,
        "degraded_reasons": bundle.degraded_reasons_json or [],
        "scene_spec_revision": bundle.scene_spec_revision,
        "assets": _group_assets(list(bundle.assets)),
        "current_job": serialize_job(latest_job) if latest_job else None,
        "updated_at": bundle.updated_at,
    }


def approve_bundle(db: Session, *, bundle: Presentation3DBundle, current_user: User, notes: str | None) -> Presentation3DBundle:
    if bundle.qa_status == "fail":
        raise HTTPException(status_code=409, detail="3D bundle quality gate failed. Approval is blocked.")
    if bundle.status in {"queued", "running"}:
        raise HTTPException(status_code=409, detail="3D bundle is still running.")
    if not any(asset.asset_role == "presentation_manifest" for asset in bundle.assets):
        raise HTTPException(status_code=409, detail="3D bundle manifest is missing.")

    bundle.approval_status = "approved"
    bundle.delivery_status = "released"
    bundle.status = "released"
    bundle.approved_by = current_user.id
    bundle.approved_at = datetime.now(timezone.utc)
    db.add(
        Presentation3DApproval(
            bundle_id=bundle.id,
            decision="approved",
            notes=notes,
            reviewed_by=current_user.id,
        )
    )
    return bundle


def reject_bundle(db: Session, *, bundle: Presentation3DBundle, current_user: User, notes: str | None) -> Presentation3DBundle:
    bundle.approval_status = "rejected"
    bundle.delivery_status = "blocked"
    if bundle.status != "failed":
        bundle.status = "awaiting_approval"
    db.add(
        Presentation3DApproval(
            bundle_id=bundle.id,
            decision="rejected",
            notes=notes,
            reviewed_by=current_user.id,
        )
    )
    return bundle
