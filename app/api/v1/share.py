from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db import get_db
from app.deps import get_current_user, require_roles
from app.models import DesignVersion, Project, ShareLink, User
from app.schemas import ShareLinkResponse
from app.services.audit import log_action
from app.services.storage import resolve_browser_asset_url


router = APIRouter(tags=["share"])


def _utc_or_assume_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


@router.post("/projects/{project_id}/share-links", response_model=ShareLinkResponse, status_code=status.HTTP_201_CREATED)
def create_share_link(
    project_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("architect", "admin")),
) -> ShareLinkResponse:
    project = db.get(Project, project_id)
    if not project or project.organization_id != current_user.organization_id:
        raise HTTPException(status_code=404, detail="Project not found")
    token = secrets.token_urlsafe(18)
    expires_at = datetime.now(timezone.utc) + timedelta(days=7)
    link = ShareLink(project_id=project.id, token=token, created_by=current_user.id, expires_at=expires_at)
    db.add(link)
    log_action(db, "share.create", user_id=current_user.id, project_id=project.id, details={"token": token})
    db.commit()
    return ShareLinkResponse(token=token, url=f"{settings.public_base_url}/share/{token}", expires_at=expires_at)


@router.get("/share/{token}")
def get_shared_project(token: str, db: Session = Depends(get_db)) -> dict:
    link = db.scalar(select(ShareLink).where(ShareLink.token == token, ShareLink.is_active.is_(True)))
    if not link or _utc_or_assume_utc(link.expires_at) < datetime.now(timezone.utc):
        raise HTTPException(status_code=404, detail="Share link not found")
    project = db.get(Project, link.project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    versions = [
        {
            "id": version.id,
            "version_number": version.version_number,
            "status": version.status,
            "thumbnail_url": resolve_browser_asset_url(version.floor_plan_urls[0]) if version.floor_plan_urls else None,
            "floor_plan_urls": [
                resolved
                for url in (version.floor_plan_urls or [])
                if (resolved := resolve_browser_asset_url(str(url)))
            ],
        }
        for version in sorted(project.versions, key=lambda item: item.version_number)
    ]
    return {
        "project": {
            "id": project.id,
            "name": project.name,
            "client_name": project.client_name,
            "brief_json": project.brief_json,
            "versions": versions,
        }
    }
