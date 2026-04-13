from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import DesignVersion, ExportPackage, Project
from app.services.brief_contract import derive_brief_contract_state
from app.services.briefing import build_clarification_state


def get_current_issued_package(db: Session, version_id: str) -> ExportPackage | None:
    return db.scalar(
        select(ExportPackage).where(
            ExportPackage.version_id == version_id,
            ExportPackage.status == "issued",
        )
    )


def assert_presentation_3d_eligible(db: Session, project: Project, version: DesignVersion) -> ExportPackage | None:
    clarification_state = build_clarification_state(project.brief_json or {})
    brief_state = derive_brief_contract_state(project.brief_status, clarification_state)
    if brief_state != "locked":
        raise HTTPException(status_code=409, detail="Brief must be locked before creating a 3D presentation bundle")

    if version.approval_status != "approved":
        raise HTTPException(status_code=409, detail="Version must be approved before creating a 3D presentation bundle")

    issued_package = get_current_issued_package(db, version.id)
    if not issued_package and version.status not in {"handoff_ready", "delivered"}:
        raise HTTPException(status_code=409, detail="An issued 2D package is required before creating a 3D presentation bundle")

    if not (version.geometry_json or version.brief_json or project.brief_json):
        raise HTTPException(status_code=422, detail="Required geometry or brief inputs are missing for 3D presentation")

    return issued_package
