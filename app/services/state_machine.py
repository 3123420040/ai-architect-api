from __future__ import annotations

from datetime import datetime, timezone

from fastapi import HTTPException, status

from app.models import DesignVersion


ALLOWED_TRANSITIONS = {
    "draft": {"generated"},
    "generated": {"under_review", "superseded"},
    "under_review": {"approved", "rejected"},
    "approved": {"locked"},
    "rejected": {"generated", "superseded"},
    "locked": {"handoff_ready"},
    "handoff_ready": {"delivered"},
    "delivered": set(),
    "superseded": set(),
}


def transition_version(version: DesignVersion, target_status: str) -> DesignVersion:
    allowed = ALLOWED_TRANSITIONS.get(version.status, set())
    if target_status not in allowed:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Invalid transition from {version.status} to {target_status}",
        )
    version.status = target_status
    if target_status == "locked":
        version.locked_at = datetime.now(timezone.utc)
    return version
