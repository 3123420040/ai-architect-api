from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any

import httpx

from app.core.config import settings
from app.services.briefing import generate_ai_follow_up, missing_brief_fields, parse_message_to_brief


SYSTEM_PROMPT = """
Ban la AI intake assistant cho KTC KTS.
Nhiem vu cua ban:
- noi chuyen bang tieng Viet tu nhien, ngan gon, ro rang
- giup thu thap thong tin design brief cho nha pho/nha o
- neu thieu thong tin quan trong thi hoi toi da 3 cau hoi ngan
- neu du thong tin thi tom tat va moi nguoi dung xac nhan de generate phuong an
- khong duoc tu tao ra chi tiet ky thuat khong co trong hoi thoai
""".strip()


def llm_is_configured() -> bool:
    return bool(settings.openai_compat_base_url and settings.openai_compat_api_key and settings.openai_compat_model)


def _client() -> httpx.Client:
    return httpx.Client(
        timeout=settings.llm_request_timeout_seconds,
        headers={
            "Authorization": f"Bearer {settings.openai_compat_api_key}",
            "Content-Type": "application/json",
        },
    )


def _chat_endpoint() -> str:
    base_url = (settings.openai_compat_base_url or "").rstrip("/")
    return f"{base_url}/chat/completions"


def _extract_text_content(payload: dict[str, Any]) -> str:
    choices = payload.get("choices") or []
    if not choices:
        return ""
    message = choices[0].get("message") or {}
    content = message.get("content", "")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(str(item.get("text", "")))
        return "".join(parts).strip()
    return str(content).strip()


def _history_messages(history: Iterable[Any]) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = []
    for item in list(history)[-10:]:
        role = "assistant" if getattr(item, "role", "") == "ai" else "user"
        content = getattr(item, "content", "") or ""
        if content.strip():
            messages.append({"role": role, "content": content})
    return messages


def _complete_text(messages: list[dict[str, str]]) -> str:
    if not llm_is_configured():
        return ""

    payload = {
        "model": settings.openai_compat_model,
        "messages": messages,
        "temperature": 0.2,
    }
    try:
        with _client() as client:
            response = client.post(_chat_endpoint(), json=payload)
            response.raise_for_status()
            return _extract_text_content(response.json())
    except httpx.HTTPError:
        return ""


def chunk_response_text(text: str, chunk_size: int = 28) -> list[str]:
    normalized = " ".join(text.split())
    if not normalized:
        return []

    chunks: list[str] = []
    buffer = ""
    for word in normalized.split(" "):
        candidate = word if not buffer else f"{buffer} {word}"
        if len(candidate) <= chunk_size:
            buffer = candidate
            continue
        if buffer:
            chunks.append(buffer)
        buffer = word
    if buffer:
        chunks.append(buffer)
    return chunks


def _fallback_turn(message: str, brief_json: dict | None) -> dict[str, Any]:
    updated_brief = parse_message_to_brief(message, brief_json)
    response_text, needs_follow_up = generate_ai_follow_up(updated_brief)
    return {
        "assistant_response": response_text,
        "brief_json": updated_brief,
        "needs_follow_up": needs_follow_up,
        "source": "heuristic",
        "follow_up_topics": missing_brief_fields(updated_brief),
    }


def generate_intake_turn(message: str, brief_json: dict | None, history: Iterable[Any]) -> dict[str, Any]:
    heuristic_brief = parse_message_to_brief(message, brief_json)
    if not llm_is_configured():
        return _fallback_turn(message, brief_json)

    conversation_messages: list[dict[str, str]] = [{"role": "system", "content": SYSTEM_PROMPT}]
    conversation_messages.extend(_history_messages(history))
    conversation_messages.append(
        {
            "role": "user",
            "content": "\n".join(
                [
                    f"Current brief JSON: {json.dumps(brief_json or {}, ensure_ascii=False)}",
                    f"Latest user message: {message}",
                    "Hay tra loi tu nhien bang tieng Viet. Neu thieu thong tin quan trong thi hoi tiep. Neu da du thong tin thi tom tat va moi xac nhan.",
                ]
            ),
        }
    )

    assistant_response = _complete_text(conversation_messages)
    if not assistant_response:
        return _fallback_turn(message, brief_json)

    # Keep intake chat production-safe: one LLM round trip for natural language,
    # then derive readiness from the deterministic heuristic brief.
    updated_brief = heuristic_brief
    follow_up_topics = missing_brief_fields(updated_brief)
    needs_follow_up = bool(follow_up_topics)

    return {
        "assistant_response": assistant_response,
        "brief_json": updated_brief,
        "needs_follow_up": needs_follow_up,
        "source": "llm",
        "follow_up_topics": follow_up_topics,
    }
