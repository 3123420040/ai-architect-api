from __future__ import annotations

import asyncio
import uuid

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import SessionLocal, get_db
from app.deps import get_user_from_access_token, require_roles
from app.models import ChatMessage, Project, User
from app.schemas import ChatRequest, ChatResponse
from app.services.audit import log_action
from app.services.briefing import build_clarification_state
from app.services.brief_contract import build_brief_contract_payload, next_brief_status_after_chat
from app.services.design_harness import DesignIntakeHarnessLoop
from app.services.design_harness.trace_store import DesignHarnessTraceStore
from app.services.llm import chunk_response_text


router = APIRouter(
    prefix="/projects/{project_id}/chat",
    tags=["chat"],
)


def _get_project_for_user(db: Session, project_id: str, current_user: User) -> Project:
    project = db.get(Project, project_id)
    if not project or project.organization_id != current_user.organization_id:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


def _history_for_project(db: Session, project_id: str) -> list[ChatMessage]:
    return db.scalars(
        select(ChatMessage).where(ChatMessage.project_id == project_id).order_by(ChatMessage.created_at)
    ).all()


def _persist_turn(
    db: Session,
    *,
    project: Project,
    current_user: User,
    message: str,
) -> tuple[Project, dict]:
    history = _history_for_project(db, project.id)
    db.add(ChatMessage(project_id=project.id, role="user", content=message, message_metadata=None))

    turn_result = DesignIntakeHarnessLoop().run(message, project.brief_json or {}, history)
    turn = turn_result.as_legacy_turn()
    project.brief_json = turn["brief_json"]
    project.brief_status = next_brief_status_after_chat(project.brief_status)
    project.status = "intake"
    clarification_state = turn.get("clarification_state") or build_clarification_state(project.brief_json)
    brief_contract = build_brief_contract_payload(project.brief_status, clarification_state)
    db.add(
        ChatMessage(
            project_id=project.id,
            role="ai",
            content=turn["assistant_response"],
            message_metadata=DesignHarnessTraceStore().build_message_metadata(
                turn=turn,
                clarification_state=clarification_state,
                brief_contract=brief_contract,
            ),
        )
    )
    log_action(
        db,
        "chat.message",
        user_id=current_user.id,
        project_id=project.id,
        details={
            "source": turn["source"],
            "needs_follow_up": turn["needs_follow_up"],
            "follow_up_topics": turn["follow_up_topics"],
            "conflicts": turn.get("conflicts", []),
            "clarification_state": clarification_state,
            "brief_contract": brief_contract,
        },
    )
    db.commit()
    db.refresh(project)
    turn["clarification_state"] = clarification_state
    turn.update(brief_contract)
    return project, turn


@router.post("", response_model=ChatResponse)
def send_chat_message(
    project_id: str,
    payload: ChatRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("architect", "admin")),
) -> ChatResponse:
    project = _get_project_for_user(db, project_id, current_user)
    project, turn = _persist_turn(db, project=project, current_user=current_user, message=payload.message)

    return ChatResponse(
        session_id=str(uuid.uuid4()),
        status="processed",
        response=turn["assistant_response"],
        brief_json=project.brief_json,
        needs_follow_up=turn["needs_follow_up"],
        follow_up_topics=turn["follow_up_topics"],
        source=turn["source"],
        assistant_payload=turn.get("assistant_payload", {}),
        conflicts=turn.get("conflicts", []),
        clarification_state=turn["clarification_state"],
        brief_contract_state=turn["brief_contract_state"],
        brief_contract_label=turn["brief_contract_label"],
        brief_can_lock=turn["brief_can_lock"],
        harness=turn.get("harness"),
    )


@router.get("/history")
def get_chat_history(
    project_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("architect", "admin")),
) -> dict:
    _get_project_for_user(db, project_id, current_user)
    messages = _history_for_project(db, project_id)
    return {
        "messages": [
            {
                "id": message.id,
                "role": message.role,
                "content": message.content,
                "metadata": message.message_metadata,
                "timestamp": message.created_at,
            }
            for message in messages
        ]
    }


@router.websocket("/stream")
async def websocket_stream(websocket: WebSocket, project_id: str) -> None:
    await websocket.accept()
    token = websocket.query_params.get("token")
    if not token:
        await websocket.send_json({"event": "chat:error", "detail": "Missing token"})
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    try:
        with SessionLocal() as db:
            current_user = get_user_from_access_token(token, db)
            _get_project_for_user(db, project_id, current_user)
    except HTTPException as exc:
        await websocket.send_json({"event": "chat:error", "detail": exc.detail})
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await websocket.send_json({"event": "chat:ready", "project_id": project_id})

    try:
        while True:
            payload = await websocket.receive_json()
            message = str(payload.get("message", "")).strip()
            if not message:
                await websocket.send_json({"event": "chat:error", "detail": "Message is required"})
                continue

            with SessionLocal() as db:
                current_user = get_user_from_access_token(token, db)
                project = _get_project_for_user(db, project_id, current_user)
                project, turn = _persist_turn(db, project=project, current_user=current_user, message=message)

            chunks = chunk_response_text(turn["assistant_response"]) or [turn["assistant_response"]]
            for chunk in chunks:
                await websocket.send_json(
                    {
                        "event": "chat:chunk",
                        "project_id": project_id,
                        "content": chunk,
                        "done": False,
                    }
                )
                await asyncio.sleep(0.02)

            await websocket.send_json(
                {
                    "event": "chat:done",
                    "project_id": project_id,
                    "done": True,
                    "response": turn["assistant_response"],
                    "brief_json": project.brief_json,
                    "needs_follow_up": turn["needs_follow_up"],
                    "follow_up_topics": turn["follow_up_topics"],
                    "source": turn["source"],
                    "assistant_payload": turn.get("assistant_payload", {}),
                    "conflicts": turn.get("conflicts", []),
                    "clarification_state": turn["clarification_state"],
                    "brief_contract_state": turn["brief_contract_state"],
                    "brief_contract_label": turn["brief_contract_label"],
                    "brief_can_lock": turn["brief_can_lock"],
                    "harness": turn.get("harness"),
                }
            )
    except WebSocketDisconnect:
        return
