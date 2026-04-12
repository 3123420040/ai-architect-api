from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user, require_roles
from app.models import Project, User
from app.schemas import BriefPayload
from app.services.audit import log_action
from app.services.briefing import build_clarification_state, merge_brief


router = APIRouter(
    prefix="/projects/{project_id}/brief",
    tags=["brief"],
    dependencies=[Depends(require_roles("architect", "admin"))],
)


@router.get("")
def get_brief(project_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> dict:
    project = db.get(Project, project_id)
    if not project or project.organization_id != current_user.organization_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return {
        "project_id": project.id,
        "status": project.brief_status,
        "brief_json": project.brief_json or {},
        "clarification_state": build_clarification_state(project.brief_json or {}),
        "created_at": project.created_at,
        "updated_at": project.updated_at,
    }


@router.put("")
def update_brief(
    project_id: str,
    payload: BriefPayload,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    project = db.get(Project, project_id)
    if not project or project.organization_id != current_user.organization_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    project.brief_json = merge_brief(project.brief_json, payload.brief_json)
    project.brief_status = payload.status
    log_action(db, "brief.update", user_id=current_user.id, project_id=project.id, details={"status": payload.status})
    db.commit()
    db.refresh(project)
    return {
        "project_id": project.id,
        "status": project.brief_status,
        "brief_json": project.brief_json,
        "clarification_state": build_clarification_state(project.brief_json or {}),
        "updated_at": project.updated_at,
    }
