from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.db import get_db
from app.deps import get_current_user, require_roles
from app.models import ChatMessage, Project, User
from app.services.audit import log_action
from app.services.design_harness.compiler import build_concept_input_snapshot, compile_concept_design_input
from app.services.design_harness.readiness import compute_design_harness_readiness
from app.services.design_harness.tools import DesignHarnessStyleTools


router = APIRouter(
    prefix="/projects/{project_id}/ai-harness",
    tags=["ai-harness"],
    dependencies=[Depends(require_roles("architect", "admin"))],
)


@router.get("/state")
def get_ai_harness_state(
    project_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    project = _get_project_for_user(db, project_id, current_user)
    return _current_state(db, project)


@router.post("/emit-concept-input")
def emit_concept_input(
    project_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    project = _get_project_for_user(db, project_id, current_user)
    state = _current_state(db, project)
    validation = state["concept_input_validation"]
    if validation.get("status") != "valid":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "CONCEPT_INPUT_BLOCKED",
                "validation": validation,
            },
        )

    snapshot = build_concept_input_snapshot(state["concept_design_input"], validation)
    persisted = _persist_snapshot_to_latest_harness_message(db, project.id, snapshot)
    log_action(
        db,
        "ai_harness.emit_concept_input",
        user_id=current_user.id,
        project_id=project.id,
        details={
            "persisted": persisted,
            "validation_status": validation.get("status"),
            "schema_version": snapshot["schema_version"],
        },
    )
    db.commit()
    return {
        "project_id": project.id,
        "concept_design_input": state["concept_design_input"],
        "concept_input_validation": validation,
        "latest_concept_input_snapshot": snapshot,
        "persisted": persisted,
    }


def _get_project_for_user(db: Session, project_id: str, current_user: User) -> Project:
    project = db.get(Project, project_id)
    if not project or project.organization_id != current_user.organization_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return project


def _current_state(db: Session, project: Project) -> dict[str, Any]:
    latest_user_message = _latest_message(db, project.id, "user")
    latest_ai_message = _latest_message(db, project.id, "ai")
    latest_metadata = latest_ai_message.message_metadata if latest_ai_message and latest_ai_message.message_metadata else {}
    machine_output = latest_metadata.get("harness_machine_output") if isinstance(latest_metadata, dict) else {}
    machine_output = machine_output if isinstance(machine_output, dict) else {}

    readiness = machine_output.get("readiness")
    assumptions = machine_output.get("assumptions")
    style_tools = machine_output.get("style_tools")
    if not isinstance(readiness, dict) or not isinstance(assumptions, list):
        readiness, assumptions = compute_design_harness_readiness(brief=project.brief_json or {})
    if not isinstance(style_tools, dict) or not style_tools:
        style_message = latest_user_message.content if latest_user_message else _brief_style_text(project.brief_json or {})
        style_tools = DesignHarnessStyleTools().run(style_message, brief_json=project.brief_json or {}).as_dict()

    compilation = compile_concept_design_input(
        project_id=project.id,
        project_name=project.name,
        brief=project.brief_json or {},
        readiness=readiness,
        assumptions=assumptions,
        style_tools=style_tools,
    )
    latest_snapshot = _latest_snapshot(latest_metadata)
    return {
        "project_id": project.id,
        "state": _state_from_validation(compilation.validation),
        "readiness": readiness,
        "assumptions": assumptions,
        "style_tools": style_tools,
        "concept_input_available": compilation.concept_design_input is not None,
        "concept_design_input": compilation.concept_design_input,
        "concept_input_validation": compilation.validation,
        "latest_concept_input_snapshot": latest_snapshot,
    }


def _latest_message(db: Session, project_id: str, role: str) -> ChatMessage | None:
    return db.scalars(
        select(ChatMessage)
        .where(ChatMessage.project_id == project_id, ChatMessage.role == role)
        .order_by(ChatMessage.created_at.desc())
        .limit(1)
    ).first()


def _persist_snapshot_to_latest_harness_message(db: Session, project_id: str, snapshot: dict[str, Any]) -> bool:
    message = _latest_message(db, project_id, "ai")
    if not message:
        return False
    metadata = dict(message.message_metadata or {})
    harness = dict(metadata.get("harness") or {})
    machine_output = dict(metadata.get("harness_machine_output") or {})
    harness["latest_concept_input_snapshot"] = snapshot
    harness["concept_input_available"] = True
    harness["concept_input_status"] = snapshot["validation"].get("status")
    machine_output["concept_design_input"] = snapshot["payload"]
    machine_output["concept_input_validation"] = snapshot["validation"]
    machine_output["latest_concept_input_snapshot"] = snapshot
    metadata["harness"] = harness
    metadata["harness_machine_output"] = machine_output
    message.message_metadata = metadata
    flag_modified(message, "message_metadata")
    return True


def _latest_snapshot(metadata: dict[str, Any]) -> dict[str, Any] | None:
    harness = metadata.get("harness") if isinstance(metadata, dict) else {}
    machine_output = metadata.get("harness_machine_output") if isinstance(metadata, dict) else {}
    if isinstance(harness, dict) and isinstance(harness.get("latest_concept_input_snapshot"), dict):
        return harness["latest_concept_input_snapshot"]
    if isinstance(machine_output, dict) and isinstance(machine_output.get("latest_concept_input_snapshot"), dict):
        return machine_output["latest_concept_input_snapshot"]
    return None


def _state_from_validation(validation: dict[str, Any]) -> str:
    if validation.get("status") == "valid":
        return "concept_input_ready"
    if validation.get("readiness_status") == "blocked_by_safety_scope":
        return "blocked_by_safety_scope"
    return "concept_input_blocked"


def _brief_style_text(brief: dict[str, Any]) -> str:
    parts = [
        brief.get("project_type"),
        brief.get("style"),
        brief.get("material_direction"),
        brief.get("color_direction"),
        *list(brief.get("design_goals") or []),
        *list(brief.get("lifestyle_priorities") or []),
        *list(brief.get("must_haves") or []),
        *list(brief.get("must_not_haves") or []),
    ]
    return " ".join(str(part) for part in parts if part)
