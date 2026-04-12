from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from app.services.briefing import (
    analyze_message_to_brief,
    build_assistant_payload,
    build_clarification_state,
    missing_brief_fields,
    render_assistant_response,
)


def llm_is_configured() -> bool:
    return False


def chunk_response_text(text: str, chunk_size: int = 120) -> list[str]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return []

    chunks: list[str] = []
    buffer = ""
    for line in lines:
        candidate = line if not buffer else f"{buffer}\n{line}"
        if len(candidate) <= chunk_size:
            buffer = candidate
            continue
        if buffer:
            chunks.append(buffer)
        if len(line) <= chunk_size:
            buffer = line
            continue
        words = line.split(" ")
        current = ""
        for word in words:
            next_candidate = word if not current else f"{current} {word}"
            if len(next_candidate) <= chunk_size:
                current = next_candidate
                continue
            if current:
                chunks.append(current)
            current = word
        buffer = current
    if buffer:
        chunks.append(buffer)
    return chunks


def generate_intake_turn(message: str, brief_json: dict | None, history: Iterable[Any]) -> dict[str, Any]:
    del history
    analysis = analyze_message_to_brief(message, brief_json)
    updated_brief = analysis["brief_json"]
    clarification_state = build_clarification_state(updated_brief, analysis["conflicts"])
    assistant_payload = build_assistant_payload(message, analysis, clarification_state)
    assistant_response = render_assistant_response(assistant_payload)

    return {
        "assistant_response": assistant_response,
        "assistant_payload": assistant_payload,
        "brief_json": updated_brief,
        "needs_follow_up": clarification_state["readiness_label"] != "ready_for_confirmation",
        "source": "deterministic",
        "follow_up_topics": missing_brief_fields(updated_brief, analysis["conflicts"]),
        "conflicts": analysis["conflicts"],
        "clarification_state": clarification_state,
    }
