from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user
from app.models import Notification, User


router = APIRouter(prefix="/notifications", tags=["notifications"])


def _serialize_notification(item: Notification) -> dict:
    return {
        "id": item.id,
        "type": item.type,
        "message": item.message,
        "project_id": item.project_id,
        "version_id": item.version_id,
        "is_read": item.is_read,
        "created_at": item.created_at,
    }


@router.get("")
def list_notifications(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> dict:
    items = db.scalars(select(Notification).where(Notification.user_id == current_user.id).order_by(Notification.created_at.desc())).all()
    return {"data": [_serialize_notification(item) for item in items]}


@router.post("/{notification_id}/read")
def mark_notification_read(notification_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> dict:
    item = db.get(Notification, notification_id)
    if item and item.user_id == current_user.id:
        item.is_read = True
        db.commit()
    return {"status": "ok"}
