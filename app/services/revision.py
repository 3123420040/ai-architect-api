from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import DesignVersion, Feedback, Project


def next_version_number(db: Session, project_id: str) -> int:
    stmt = select(func.max(DesignVersion.version_number)).where(DesignVersion.project_id == project_id)
    current = db.scalar(stmt) or 0
    return current + 1


def create_revision(
    db: Session,
    *,
    project: Project,
    parent_version: DesignVersion,
    feedback: Feedback,
) -> DesignVersion:
    version = DesignVersion(
        project_id=project.id,
        parent_version_id=parent_version.id,
        version_number=next_version_number(db, project.id),
        status="generated",
        option_label=f"Revision V{parent_version.version_number + 1}",
        option_description=f"Revision tu feedback: {feedback.content[:120]}",
        brief_json=parent_version.brief_json,
        floor_plan_urls=parent_version.floor_plan_urls,
        render_urls=parent_version.render_urls,
        generation_metadata={
            "revision_from": parent_version.id,
            "feedback_id": feedback.id,
            "note": feedback.content,
        },
    )
    db.add(version)
    db.flush()
    return version
