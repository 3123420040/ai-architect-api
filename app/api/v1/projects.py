from __future__ import annotations

from math import ceil

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user, require_roles
from app.models import DesignVersion, ExportPackage, Project, User
from app.schemas import Pagination, PaginatedProjects, ProjectCreate, ProjectUpdate
from app.services.audit import log_action
from app.services.briefing import build_clarification_state
from app.services.brief_contract import build_brief_contract_payload


router = APIRouter(
    prefix="/projects",
    tags=["projects"],
    dependencies=[Depends(require_roles("architect", "admin"))],
)


def _pick_current_version(versions: list[DesignVersion]) -> DesignVersion | None:
    if not versions:
        return None

    active_versions = [item for item in versions if item.status != "superseded"]
    if active_versions:
        return max(active_versions, key=lambda item: item.version_number)

    return max(versions, key=lambda item: item.version_number)


def _serialize_package(package: ExportPackage, versions: dict[str, DesignVersion]) -> dict:
    version = versions.get(package.version_id)
    return {
        "id": package.id,
        "version_id": package.version_id,
        "version_number": version.version_number if version else None,
        "revision_label": package.revision_label,
        "status": package.status,
        "deliverable_preset": package.deliverable_preset,
        "quality_status": package.quality_status,
        "quality_report_json": package.quality_report_json or {},
        "manifest_url": package.manifest_url,
        "export_urls": package.export_urls or {},
        "files_manifest": package.files_manifest or [],
        "issue_date": package.issue_date,
        "issued_at": package.issued_at,
        "is_current": package.is_current,
        "created_at": package.created_at,
        "updated_at": package.updated_at,
    }


def _serialize_project(project: Project, versions: list[DesignVersion]) -> dict:
    current = _pick_current_version(versions)
    version_by_id = {version.id: version for version in versions}
    clarification_state = build_clarification_state(project.brief_json or {})
    brief_contract = build_brief_contract_payload(project.brief_status, clarification_state)
    return {
        "id": project.id,
        "name": project.name,
        "client_name": project.client_name,
        "client_phone": project.client_phone,
        "status": project.status,
        "brief": project.brief_json,
        "brief_status": project.brief_status,
        **brief_contract,
        "clarification_state": clarification_state,
        "current_version_number": current.version_number if current else None,
        "current_version_status": current.status if current else None,
        "thumbnail_url": current.floor_plan_urls[0] if current and current.floor_plan_urls else None,
        "versions": [
            {
                "id": version.id,
                "version_number": version.version_number,
                "status": version.status,
                "thumbnail_url": version.floor_plan_urls[0] if version.floor_plan_urls else None,
                "floor_plan_urls": version.floor_plan_urls,
                "model_url": version.model_url,
                "render_urls": version.render_urls,
                "option_label": version.option_label,
                "option_description": version.option_description,
                "option_title_vi": ((version.generation_metadata or {}).get("decision_metadata") or {}).get("option_title_vi") or version.option_label,
                "option_summary_vi": ((version.generation_metadata or {}).get("decision_metadata") or {}).get("option_summary_vi") or version.option_description,
                "option_strategy_key": ((version.generation_metadata or {}).get("option_strategy_profile") or {}).get("strategy_key"),
                "option_strategy_label_vi": ((version.generation_metadata or {}).get("option_strategy_profile") or {}).get("title_vi"),
                "fit_reasons": ((version.generation_metadata or {}).get("decision_metadata") or {}).get("fit_reasons") or [],
                "strengths": ((version.generation_metadata or {}).get("decision_metadata") or {}).get("strengths") or [],
                "caveats": ((version.generation_metadata or {}).get("decision_metadata") or {}).get("caveats") or [],
                "metrics": ((version.generation_metadata or {}).get("decision_metadata") or {}).get("metrics") or {},
                "compare_axes": ((version.generation_metadata or {}).get("decision_metadata") or {}).get("compare_axes") or [],
                "decision_metadata_degraded": bool((((version.generation_metadata or {}).get("decision_metadata") or {}).get("degraded"))),
                "decision_metadata_degraded_reasons": ((version.generation_metadata or {}).get("decision_metadata") or {}).get("degraded_reasons") or [],
                "generation_source": (version.generation_metadata or {}).get("generation_source"),
                "parent_version_id": version.parent_version_id,
                "export_urls": version.export_urls,
                "generation_metadata": version.generation_metadata,
                "created_at": version.created_at,
            }
            for version in sorted(versions, key=lambda item: item.version_number)
        ],
        "packages": [
            _serialize_package(package, version_by_id)
            for package in sorted(project.packages, key=lambda item: item.created_at)
        ],
        "created_at": project.created_at,
        "updated_at": project.updated_at,
    }


@router.get("", response_model=PaginatedProjects)
def list_projects(
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=20, ge=1, le=100),
    search: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PaginatedProjects:
    stmt = select(Project).where(Project.organization_id == current_user.organization_id)
    projects = db.scalars(stmt).all()
    if search:
        search_lower = search.lower()
        projects = [item for item in projects if search_lower in item.name.lower()]
    total = len(projects)
    start = (page - 1) * per_page
    items = projects[start : start + per_page]
    data = [_serialize_project(item, list(item.versions)) for item in items]
    return PaginatedProjects(
        data=data,
        pagination=Pagination(page=page, per_page=per_page, total=total, total_pages=max(1, ceil(total / per_page)) if total else 0),
    )


@router.post("", status_code=status.HTTP_201_CREATED)
def create_project(
    payload: ProjectCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    project = Project(
        organization_id=current_user.organization_id,
        name=payload.name,
        client_name=payload.client_name,
        client_phone=payload.client_phone,
        client_user_id=current_user.id,
        kts_user_id=payload.kts_user_id or current_user.id,
        status="intake",
        brief_json={},
        brief_status="draft",
    )
    db.add(project)
    db.flush()
    log_action(db, "project.create", user_id=current_user.id, project_id=project.id)
    db.commit()
    return _serialize_project(project, [])


@router.get("/{project_id}")
def get_project(
    project_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    project = db.get(Project, project_id)
    if not project or project.organization_id != current_user.organization_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return _serialize_project(project, list(project.versions))


@router.patch("/{project_id}")
def update_project(
    project_id: str,
    payload: ProjectUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    project = db.get(Project, project_id)
    if not project or project.organization_id != current_user.organization_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    for key, value in payload.model_dump(exclude_none=True).items():
        setattr(project, key, value)
    log_action(db, "project.update", user_id=current_user.id, project_id=project.id, details=payload.model_dump(exclude_none=True))
    db.commit()
    db.refresh(project)
    return _serialize_project(project, list(project.versions))
