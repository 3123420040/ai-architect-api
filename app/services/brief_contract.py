from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fastapi import HTTPException, status


BRIEF_CONTRACT_LABELS = {
    "draft": "Đang làm rõ",
    "ready_to_lock": "Sẵn sàng chốt",
    "locked": "Brief đã chốt",
    "reopened": "Đã mở lại",
}

LOCKED_BRIEF_STATUSES = {"confirmed", "locked"}


def brief_can_lock(clarification_state: Mapping[str, Any] | None) -> bool:
    state = clarification_state or {}
    return (
        str(state.get("readiness_label") or "") == "ready_for_confirmation"
        and not list(state.get("conflicts") or [])
        and not list(state.get("blocking_missing") or [])
    )


def derive_brief_contract_state(
    brief_status: str | None,
    clarification_state: Mapping[str, Any] | None,
) -> str:
    normalized = str(brief_status or "draft")
    if normalized in LOCKED_BRIEF_STATUSES:
        return "locked"
    if normalized == "reopened":
        return "reopened"
    if brief_can_lock(clarification_state):
        return "ready_to_lock"
    return "draft"


def build_brief_contract_payload(
    brief_status: str | None,
    clarification_state: Mapping[str, Any] | None,
) -> dict[str, Any]:
    state = derive_brief_contract_state(brief_status, clarification_state)
    can_lock = brief_can_lock(clarification_state)
    return {
        "brief_contract_state": state,
        "brief_contract_label": BRIEF_CONTRACT_LABELS[state],
        "brief_can_lock": can_lock,
        "brief_is_locked": state == "locked",
    }


def next_brief_status_after_chat(current_status: str | None) -> str:
    if str(current_status or "") in LOCKED_BRIEF_STATUSES | {"reopened"}:
        return "reopened"
    return "draft"


def resolve_brief_status_on_update(
    current_status: str | None,
    requested_status: str | None,
    clarification_state: Mapping[str, Any] | None,
) -> str:
    requested = str(requested_status or "draft")
    if requested == "confirmed":
        if not brief_can_lock(clarification_state):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Brief is not ready to lock yet",
            )
        return "confirmed"

    if str(current_status or "") in LOCKED_BRIEF_STATUSES | {"reopened"}:
        return "reopened"
    return "draft"

