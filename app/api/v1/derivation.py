from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user, require_roles
from app.models import DesignVersion, Project, User
from app.schemas import DerivationResponse
from app.services.audit import log_action
from app.services.gpu_client import derive_3d_assets
from app.services.storage import save_json, save_svg


router = APIRouter(
    tags=["derivation"],
    dependencies=[Depends(require_roles("architect", "admin"))],
)


@router.post("/versions/{version_id}/derive-3d", response_model=DerivationResponse)
def derive_3d(
    version_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DerivationResponse:
    version = db.get(DesignVersion, version_id)
    if not version:
        raise HTTPException(status_code=404, detail="Version not found")
    project = db.get(Project, version.project_id)
    if not project or project.organization_id != current_user.organization_id:
        raise HTTPException(status_code=404, detail="Project not found")
    if version.status not in {"locked", "handoff_ready", "delivered"}:
        raise HTTPException(status_code=403, detail="Only locked versions can derive 3D")

    payload = derive_3d_assets(version.id, version.brief_json or {}, version.floor_plan_urls[0] if version.floor_plan_urls else None)
    model_url = save_json(f"projects/{project.id}/models", payload["model_gltf"])
    render_urls = [save_svg(f"projects/{project.id}/renders", item) for item in payload.get("renders", [])]
    version.model_url = model_url
    version.render_urls = render_urls
    log_action(db, "derivation.create", user_id=current_user.id, project_id=project.id, version_id=version.id)
    db.commit()
    return DerivationResponse(model_url=model_url, render_urls=render_urls)
