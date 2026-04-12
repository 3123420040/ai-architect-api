from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user, require_roles
from app.models import Annotation, DesignVersion, Project, User
from app.schemas import AnnotationCreate, AnnotationUpdate
from app.services.audit import log_action


router = APIRouter(
    prefix="/versions/{version_id}/annotations",
    tags=["annotations"],
    dependencies=[Depends(require_roles("architect", "admin"))],
)


def _validate_access(db: Session, version_id: str, user: User) -> DesignVersion:
    version = db.get(DesignVersion, version_id)
    if not version:
        raise HTTPException(status_code=404, detail="Version not found")
    project = db.get(Project, version.project_id)
    if not project or project.organization_id != user.organization_id:
        raise HTTPException(status_code=404, detail="Project not found")
    return version


def _serialize_annotation(item: Annotation) -> dict:
    return {
        "id": item.id,
        "version_id": item.version_id,
        "user_id": item.user_id,
        "x": item.x,
        "y": item.y,
        "floor_index": item.floor_index,
        "comment": item.comment,
        "is_resolved": item.is_resolved,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
    }


@router.get("")
def list_annotations(version_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> dict:
    _validate_access(db, version_id, current_user)
    items = db.scalars(select(Annotation).where(Annotation.version_id == version_id).order_by(Annotation.created_at)).all()
    return {"data": [_serialize_annotation(item) for item in items]}


@router.post("", status_code=status.HTTP_201_CREATED)
def create_annotation(
    version_id: str,
    payload: AnnotationCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    version = _validate_access(db, version_id, current_user)
    item = Annotation(version_id=version.id, user_id=current_user.id, **payload.model_dump())
    db.add(item)
    log_action(db, "annotation.create", user_id=current_user.id, project_id=version.project_id, version_id=version.id)
    db.commit()
    db.refresh(item)
    return _serialize_annotation(item)


@router.patch("/{annotation_id}")
def update_annotation(
    version_id: str,
    annotation_id: str,
    payload: AnnotationUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    version = _validate_access(db, version_id, current_user)
    item = db.get(Annotation, annotation_id)
    if not item or item.version_id != version.id:
        raise HTTPException(status_code=404, detail="Annotation not found")
    for key, value in payload.model_dump(exclude_none=True).items():
        setattr(item, key, value)
    log_action(db, "annotation.update", user_id=current_user.id, project_id=version.project_id, version_id=version.id)
    db.commit()
    db.refresh(item)
    return _serialize_annotation(item)


@router.delete("/{annotation_id}")
def delete_annotation(
    version_id: str,
    annotation_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    version = _validate_access(db, version_id, current_user)
    item = db.get(Annotation, annotation_id)
    if not item or item.version_id != version.id:
        raise HTTPException(status_code=404, detail="Annotation not found")
    db.delete(item)
    log_action(db, "annotation.delete", user_id=current_user.id, project_id=version.project_id, version_id=version.id)
    db.commit()
    return {"status": "deleted"}
