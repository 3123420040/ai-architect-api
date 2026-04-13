from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user, require_roles
from app.models import DesignVersion, Project, User
from app.schemas import (
    Presentation3DActionRequest,
    Presentation3DBundleOut,
    Presentation3DJobCreateRequest,
    Presentation3DJobOut,
)
from app.services.audit import log_action
from app.services.presentation_3d.eligibility import assert_presentation_3d_eligible
from app.services.presentation_3d.orchestrator import (
    approve_bundle,
    create_bundle_job,
    get_bundle_or_404,
    get_job_or_404,
    get_latest_bundle_for_version,
    queue_bundle_job,
    reject_bundle,
    serialize_bundle,
    serialize_job,
)


router = APIRouter(
    tags=["presentation_3d"],
    dependencies=[Depends(require_roles("architect", "admin"))],
)


def _get_version_project(db: Session, version_id: str, current_user: User) -> tuple[Project, DesignVersion]:
    version = db.get(DesignVersion, version_id)
    if not version:
        raise HTTPException(status_code=404, detail="Version not found")
    project = db.get(Project, version.project_id)
    if not project or project.organization_id != current_user.organization_id:
        raise HTTPException(status_code=404, detail="Project not found")
    return project, version


@router.post(
    "/versions/{version_id}/presentation-3d/jobs",
    response_model=Presentation3DJobOut,
    status_code=status.HTTP_202_ACCEPTED,
)
def create_presentation_3d_job(
    version_id: str,
    payload: Presentation3DJobCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Presentation3DJobOut:
    project, version = _get_version_project(db, version_id, current_user)
    assert_presentation_3d_eligible(db, project, version)
    bundle, job = create_bundle_job(
        db,
        project=project,
        version=version,
        current_user=current_user,
        payload=payload.model_dump(),
    )
    log_action(db, "presentation_3d.job_create", user_id=current_user.id, project_id=project.id, version_id=version.id, details={"bundle_id": bundle.id, "job_id": job.id})
    db.commit()
    queue_bundle_job(job.id)
    return Presentation3DJobOut(
        job_id=job.id,
        bundle_id=bundle.id,
        status=job.status,
        stage=job.stage,
        progress_percent=job.progress_percent,
        attempt_count=job.attempt_count,
        error_code=job.error_code,
        error_message=job.error_message,
    )


@router.get("/versions/{version_id}/presentation-3d", response_model=Presentation3DBundleOut)
def get_latest_presentation_3d_bundle(
    version_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Presentation3DBundleOut:
    project, version = _get_version_project(db, version_id, current_user)
    bundle = get_latest_bundle_for_version(db, version.id)
    if not bundle:
        raise HTTPException(status_code=404, detail="3D bundle not found")
    payload = serialize_bundle(bundle)
    return Presentation3DBundleOut(**payload)


@router.get("/presentation-3d/bundles/{bundle_id}", response_model=Presentation3DBundleOut)
def get_presentation_3d_bundle(
    bundle_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Presentation3DBundleOut:
    bundle = get_bundle_or_404(db, bundle_id)
    project = db.get(Project, bundle.project_id)
    if not project or project.organization_id != current_user.organization_id:
        raise HTTPException(status_code=404, detail="Project not found")
    return Presentation3DBundleOut(**serialize_bundle(bundle))


@router.get("/presentation-3d/jobs/{job_id}", response_model=Presentation3DJobOut)
def get_presentation_3d_job(
    job_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Presentation3DJobOut:
    job = get_job_or_404(db, job_id)
    bundle = get_bundle_or_404(db, job.bundle_id)
    project = db.get(Project, bundle.project_id)
    if not project or project.organization_id != current_user.organization_id:
        raise HTTPException(status_code=404, detail="Project not found")
    return Presentation3DJobOut(**serialize_job(job))


@router.post("/presentation-3d/jobs/{job_id}/retry", response_model=Presentation3DJobOut)
def retry_presentation_3d_job(
    job_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Presentation3DJobOut:
    job = get_job_or_404(db, job_id)
    bundle = get_bundle_or_404(db, job.bundle_id)
    project = db.get(Project, bundle.project_id)
    if not project or project.organization_id != current_user.organization_id:
        raise HTTPException(status_code=404, detail="Project not found")
    if job.status != "failed":
        raise HTTPException(status_code=409, detail="Only failed 3D jobs can be retried")
    if bundle.approval_status == "approved":
        raise HTTPException(status_code=409, detail="Approved bundles cannot be retried in place")

    job.status = "queued"
    job.stage = "scene_spec"
    job.progress_percent = 0
    job.error_code = None
    job.error_message = None
    bundle.status = "queued"
    bundle.delivery_status = "preview_only"
    db.commit()
    queue_bundle_job(job.id)
    return Presentation3DJobOut(**serialize_job(job))


@router.post("/presentation-3d/bundles/{bundle_id}/approve", response_model=Presentation3DBundleOut)
def approve_presentation_3d_bundle(
    bundle_id: str,
    payload: Presentation3DActionRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Presentation3DBundleOut:
    bundle = get_bundle_or_404(db, bundle_id)
    project = db.get(Project, bundle.project_id)
    if not project or project.organization_id != current_user.organization_id:
        raise HTTPException(status_code=404, detail="Project not found")
    approve_bundle(db, bundle=bundle, current_user=current_user, notes=payload.notes)
    db.commit()
    return Presentation3DBundleOut(**serialize_bundle(bundle))


@router.post("/presentation-3d/bundles/{bundle_id}/reject", response_model=Presentation3DBundleOut)
def reject_presentation_3d_bundle(
    bundle_id: str,
    payload: Presentation3DActionRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Presentation3DBundleOut:
    bundle = get_bundle_or_404(db, bundle_id)
    project = db.get(Project, bundle.project_id)
    if not project or project.organization_id != current_user.organization_id:
        raise HTTPException(status_code=404, detail="Project not found")
    reject_bundle(db, bundle=bundle, current_user=current_user, notes=payload.notes)
    db.commit()
    return Presentation3DBundleOut(**serialize_bundle(bundle))
