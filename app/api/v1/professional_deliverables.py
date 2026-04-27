from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user, require_roles
from app.models import DesignVersion, Project, User
from app.schemas import (
    ProfessionalDeliverableBundleOut,
    ProfessionalDeliverableJobCreateRequest,
    ProfessionalDeliverableJobOut,
)
from app.services.audit import log_action
from app.services.professional_deliverables.orchestrator import (
    create_professional_bundle_job,
    get_bundle_or_404,
    get_job_or_404,
    get_latest_bundle_for_version,
    queue_professional_bundle_job,
    serialize_bundle,
    serialize_job,
)


router = APIRouter(
    prefix="",
    tags=["professional_deliverables"],
    dependencies=[Depends(require_roles("architect", "admin"))],
)


ELIGIBLE_STATUSES = {"locked", "handoff_ready", "delivered"}


def _get_version_project(db: Session, version_id: str, current_user: User) -> tuple[Project, DesignVersion]:
    version = db.get(DesignVersion, version_id)
    if not version:
        raise HTTPException(status_code=404, detail="Version not found")
    project = db.get(Project, version.project_id)
    if not project or project.organization_id != current_user.organization_id:
        raise HTTPException(status_code=404, detail="Project not found")
    return project, version


@router.post(
    "/versions/{version_id}/professional-deliverables/jobs",
    response_model=ProfessionalDeliverableJobOut,
    status_code=status.HTTP_202_ACCEPTED,
)
def create_professional_deliverable_job(
    version_id: str,
    _payload: ProfessionalDeliverableJobCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ProfessionalDeliverableJobOut:
    project, version = _get_version_project(db, version_id, current_user)
    if version.status not in ELIGIBLE_STATUSES:
        raise HTTPException(status_code=409, detail=f"Version status '{version.status}' is not eligible for professional deliverables")
    if not version.geometry_json:
        raise HTTPException(status_code=422, detail="Version has no geometry_json; cannot generate professional deliverables")
    bundle, job = create_professional_bundle_job(db, project=project, version=version, current_user=current_user)
    log_action(db, "professional_deliverables.job_create", user_id=current_user.id, project_id=project.id, version_id=version.id, details={"bundle_id": bundle.id, "job_id": job.id})
    db.commit()
    queue_professional_bundle_job(job.id)
    return ProfessionalDeliverableJobOut(**serialize_job(job))


@router.get("/versions/{version_id}/professional-deliverables", response_model=ProfessionalDeliverableBundleOut)
def get_professional_deliverables_bundle(
    version_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ProfessionalDeliverableBundleOut:
    _project, _version = _get_version_project(db, version_id, current_user)
    bundle = get_latest_bundle_for_version(db, version_id)
    if not bundle:
        raise HTTPException(status_code=404, detail="Professional deliverable bundle not found")
    return ProfessionalDeliverableBundleOut(**serialize_bundle(bundle))


@router.get("/professional-deliverables/jobs/{job_id}", response_model=ProfessionalDeliverableJobOut)
def get_professional_deliverable_job(
    job_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ProfessionalDeliverableJobOut:
    job = get_job_or_404(db, job_id)
    bundle = get_bundle_or_404(db, job.bundle_id)
    _project, _version = _get_version_project(db, bundle.version_id, current_user)
    return ProfessionalDeliverableJobOut(**serialize_job(job))


@router.post("/professional-deliverables/jobs/{job_id}/retry", response_model=ProfessionalDeliverableJobOut)
def retry_professional_deliverable_job(
    job_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ProfessionalDeliverableJobOut:
    job = get_job_or_404(db, job_id)
    bundle = get_bundle_or_404(db, job.bundle_id)
    _project, _version = _get_version_project(db, bundle.version_id, current_user)
    if job.status != "failed":
        raise HTTPException(status_code=409, detail="Only failed professional deliverable jobs can be retried")

    job.status = "queued"
    job.stage = "queued"
    job.progress_percent = 0
    job.error_code = None
    job.error_message = None
    bundle.status = "queued"
    db.commit()
    queue_professional_bundle_job(job.id)
    return ProfessionalDeliverableJobOut(**serialize_job(job))
