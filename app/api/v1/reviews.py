from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user, require_roles
from app.models import DesignVersion, Project, User
from app.schemas import ReviewAction
from app.services.audit import create_notification, log_action
from app.services.state_machine import transition_version


router = APIRouter(
    prefix="/reviews",
    tags=["reviews"],
    dependencies=[Depends(require_roles("architect", "admin"))],
)


def _get_version(db: Session, version_id: str, user: User) -> tuple[Project, DesignVersion]:
    version = db.get(DesignVersion, version_id)
    if not version:
        raise HTTPException(status_code=404, detail="Version not found")
    project = db.get(Project, version.project_id)
    if not project or project.organization_id != user.organization_id:
        raise HTTPException(status_code=404, detail="Project not found")
    return project, version


@router.post("/{version_id}/approve")
def approve_version(
    version_id: str,
    payload: ReviewAction,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    project, version = _get_version(db, version_id, current_user)
    transition_version(version, "approved")
    transition_version(version, "locked")
    project.status = "locked"
    version.reviewed_by = current_user.id
    version.reviewed_at = datetime.now(timezone.utc)
    version.approval_status = "approved"
    log_action(db, "review.approve", user_id=current_user.id, project_id=project.id, version_id=version.id, details={"comment": payload.comment})
    create_notification(
        db,
        user_id=current_user.id,
        notification_type="version_approved",
        message=f"Version V{version.version_number} da duoc khoa",
        project_id=project.id,
        version_id=version.id,
    )
    db.commit()
    return {"id": version.id, "status": version.status}


@router.post("/{version_id}/reject")
def reject_version(
    version_id: str,
    payload: ReviewAction,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    if not payload.reason:
        raise HTTPException(status_code=400, detail="Reject reason is required")
    project, version = _get_version(db, version_id, current_user)
    transition_version(version, "rejected")
    project.status = "rejected"
    version.reviewed_by = current_user.id
    version.reviewed_at = datetime.now(timezone.utc)
    version.approval_status = "rejected"
    version.rejection_reason = payload.reason
    log_action(db, "review.reject", user_id=current_user.id, project_id=project.id, version_id=version.id, details={"reason": payload.reason})
    db.commit()
    return {"id": version.id, "status": version.status}
