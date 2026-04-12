from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import AuditLog, Notification


def log_action(
    db: Session,
    action: str,
    *,
    user_id: str | None = None,
    project_id: str | None = None,
    version_id: str | None = None,
    details: dict | None = None,
) -> AuditLog:
    record = AuditLog(
        user_id=user_id,
        action=action,
        project_id=project_id,
        version_id=version_id,
        details=details or {},
    )
    db.add(record)
    db.flush()
    return record


def create_notification(
    db: Session,
    *,
    user_id: str,
    notification_type: str,
    message: str,
    project_id: str | None = None,
    version_id: str | None = None,
) -> Notification:
    notification = Notification(
        user_id=user_id,
        type=notification_type,
        message=message,
        project_id=project_id,
        version_id=version_id,
    )
    db.add(notification)
    db.flush()
    return notification
