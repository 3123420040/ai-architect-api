from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import require_roles
from app.models import AuditLog, User
from app.tasks.worker import queue_ping


router = APIRouter(
    prefix="/admin",
    tags=["admin"],
    dependencies=[Depends(require_roles("admin"))],
)


@router.get("/audit-logs")
def list_audit_logs(
    limit: int = Query(default=20, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("admin")),
) -> dict:
    logs = db.scalars(
        select(AuditLog)
        .where((AuditLog.user_id == current_user.id) | (AuditLog.user_id.is_(None)))
        .order_by(AuditLog.created_at.desc())
        .limit(limit)
    ).all()
    return {
        "data": [
            {
                "id": log.id,
                "action": log.action,
                "project_id": log.project_id,
                "version_id": log.version_id,
                "details": log.details,
                "created_at": log.created_at,
            }
            for log in logs
        ]
    }


@router.post("/tasks/ping")
def trigger_ping_task(current_user: User = Depends(require_roles("admin"))) -> dict:
    result = queue_ping({"requested_by": current_user.id})
    return {"task_id": result.id, "status": "queued"}
