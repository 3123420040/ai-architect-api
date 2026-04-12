from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user
from app.models import DesignVersion, Feedback, Project, ShareLink, User
from app.schemas import FeedbackCreate, ReviewAction
from app.services.audit import create_notification, log_action
from app.services.revision import create_revision


router = APIRouter(tags=["feedback"])


@router.post("/share/{token}/feedback", status_code=status.HTTP_201_CREATED)
def create_feedback(token: str, payload: FeedbackCreate, db: Session = Depends(get_db)) -> dict:
    link = db.scalar(select(ShareLink).where(ShareLink.token == token, ShareLink.is_active.is_(True)))
    if not link:
        raise HTTPException(status_code=404, detail="Share link not found")
    project = db.get(Project, link.project_id)
    if not project or not project.versions:
        raise HTTPException(status_code=404, detail="Project not found")
    version = max(project.versions, key=lambda item: item.version_number)
    feedback = Feedback(version_id=version.id, user_id=None, content=payload.content, structured_json={"summary": payload.content})
    db.add(feedback)
    if project.kts_user_id:
        create_notification(
            db,
            user_id=project.kts_user_id,
            notification_type="feedback_received",
            message=f"Co feedback moi cho {project.name}",
            project_id=project.id,
            version_id=version.id,
        )
    log_action(db, "feedback.create", project_id=project.id, version_id=version.id, details={"content": payload.content})
    db.commit()
    db.refresh(feedback)
    return {"id": feedback.id, "version_id": version.id, "status": "submitted"}


@router.post("/reviews/{version_id}/revise")
def create_revision_from_review(
    version_id: str,
    payload: ReviewAction,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    target_version = db.get(DesignVersion, version_id)
    if not target_version:
        raise HTTPException(status_code=404, detail="Version not found")
    project = db.get(Project, target_version.project_id)
    if not project or project.organization_id != current_user.organization_id:
        raise HTTPException(status_code=404, detail="Project not found")
    feedback = Feedback(
        version_id=target_version.id,
        user_id=current_user.id,
        content=payload.reason or payload.comment or "Revision requested",
        structured_json={"source": "architect"},
    )
    db.add(feedback)
    db.flush()
    revision = create_revision(db, project=project, parent_version=target_version, feedback=feedback)
    log_action(db, "review.revise", user_id=current_user.id, project_id=project.id, version_id=revision.id, details={"parent_version_id": target_version.id})
    db.commit()
    return {"id": revision.id, "parent_version_id": target_version.id, "status": revision.status}
