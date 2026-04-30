from __future__ import annotations

import json
import re
from collections.abc import Iterable
from typing import Any

import httpx

from app.core.config import settings
from app.services.briefing import (
    analyze_message_to_brief,
    build_assistant_payload,
    build_clarification_state,
    merge_brief,
    missing_brief_fields,
    render_assistant_response,
)

LLM_SOURCE = "llm_openai_compat"
DETERMINISTIC_SOURCE = "deterministic"
FALLBACK_SOURCE = "deterministic_fallback"
MAX_HISTORY_MESSAGES = 8
MAX_MESSAGE_CHARS = 1600
LLM_GATEWAY_ATTEMPTS = 2

ALLOWED_BRIEF_KEYS = {
    "project_type",
    "project_mode",
    "location",
    "lot",
    "floors",
    "rooms",
    "style",
    "material_direction",
    "color_direction",
    "budget_vnd",
    "timeline_months",
    "special_requests",
    "lifestyle_priorities",
    "must_haves",
    "must_not_haves",
    "occupant_count",
    "household_profile",
    "renovation_scope",
    "design_goals",
    "space_requests",
    "spatial_preferences",
    "notes",
}

ALLOWED_LOT_KEYS = {"width_m", "depth_m", "area_m2", "buildable_area_m2", "orientation", "frontage_m", "access"}
ALLOWED_ROOM_KEYS = {"bedrooms", "bathrooms", "wc", "parking", "workspaces"}
ALLOWED_SCALAR_KEYS = {
    "project_type",
    "project_mode",
    "location",
    "style",
    "material_direction",
    "color_direction",
    "household_profile",
    "renovation_scope",
}
ALLOWED_NUMBER_KEYS = {"floors", "budget_vnd", "timeline_months", "occupant_count"}
ALLOWED_LIST_KEYS = {
    "special_requests",
    "lifestyle_priorities",
    "must_haves",
    "must_not_haves",
    "design_goals",
    "space_requests",
    "spatial_preferences",
    "notes",
}
UNSAFE_PATCH_KEYS = {
    "construction_ready",
    "permit_ready",
    "code_compliant",
    "legal_compliant",
    "structural_verified",
    "mep_verified",
    "geotech_verified",
}


def llm_is_configured() -> bool:
    return bool(
        str(settings.openai_compat_base_url or "").strip()
        and str(settings.openai_compat_api_key or "").strip()
        and str(settings.openai_compat_model or "").strip()
    )


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


def _build_deterministic_turn(
    message: str,
    brief_json: dict | None,
    *,
    source: str = DETERMINISTIC_SOURCE,
    source_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    analysis = analyze_message_to_brief(message, brief_json)
    return _build_turn_from_analysis(message, analysis, source=source, source_metadata=source_metadata)


def _build_turn_from_analysis(
    message: str,
    analysis: dict[str, Any],
    *,
    source: str,
    source_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    updated_brief = analysis["brief_json"]
    clarification_state = build_clarification_state(updated_brief, analysis["conflicts"])
    assistant_payload = build_assistant_payload(message, analysis, clarification_state)
    if source_metadata:
        assistant_payload["source_metadata"] = source_metadata
    assistant_response = render_assistant_response(assistant_payload)

    return {
        "assistant_response": assistant_response,
        "assistant_payload": assistant_payload,
        "brief_json": updated_brief,
        "needs_follow_up": clarification_state["readiness_label"] != "ready_for_confirmation",
        "source": source,
        "follow_up_topics": missing_brief_fields(updated_brief, analysis["conflicts"]),
        "conflicts": analysis["conflicts"],
        "clarification_state": clarification_state,
    }


def generate_intake_turn(message: str, brief_json: dict | None, history: Iterable[Any]) -> dict[str, Any]:
    deterministic_analysis = analyze_message_to_brief(message, brief_json)
    if not llm_is_configured():
        return _build_turn_from_analysis(message, deterministic_analysis, source=DETERMINISTIC_SOURCE)

    try:
        llm_payload = _call_intake_llm(
            message=message,
            brief_json=brief_json or {},
            history=history,
            deterministic_analysis=deterministic_analysis,
        )
        analysis = _analysis_from_llm_payload(deterministic_analysis, llm_payload)
        return _build_turn_from_analysis(
            message,
            analysis,
            source=LLM_SOURCE,
            source_metadata={
                "provider": "openai_compat",
                "model": settings.openai_compat_model,
                "prompt": "intake_structured_extraction_v1",
                "confidence": llm_payload.get("confidence"),
            },
        )
    except Exception as exc:
        return _build_turn_from_analysis(
            message,
            deterministic_analysis,
            source=FALLBACK_SOURCE,
            source_metadata={
                "provider": "openai_compat",
                "model": settings.openai_compat_model,
                "fallback_reason": _safe_error_message(exc),
            },
        )


def _call_intake_llm(
    *,
    message: str,
    brief_json: dict[str, Any],
    history: Iterable[Any],
    deterministic_analysis: dict[str, Any],
) -> dict[str, Any]:
    messages = _build_intake_prompt_messages(
        message=message,
        brief_json=brief_json,
        history=history,
        deterministic_analysis=deterministic_analysis,
    )
    response = _post_openai_compat(messages)
    content = _extract_chat_content(response)
    try:
        payload = _extract_json_object(content)
    except Exception:
        retry_messages = [
            *messages,
            {"role": "assistant", "content": _truncate(content, 1000) or "<empty response>"},
            {
                "role": "user",
                "content": (
                    "The previous response was not valid JSON. Return ONLY the JSON object for the same "
                    "schema now, with no prose, no markdown fences, and no explanation."
                ),
            },
        ]
        retry_response = _post_openai_compat(retry_messages)
        payload = _extract_json_object(_extract_chat_content(retry_response))
    if not isinstance(payload, dict):
        raise ValueError("LLM response was not a JSON object")
    return payload


def _post_openai_compat(messages: list[dict[str, str]]) -> dict[str, Any]:
    base_url = str(settings.openai_compat_base_url or "").strip().rstrip("/")
    api_key = str(settings.openai_compat_api_key or "").strip()
    if not base_url or not api_key:
        raise ValueError("OpenAI-compatible LLM is not configured")

    payload = {
        "model": str(settings.openai_compat_model or "").strip(),
        "messages": messages,
        "temperature": 0.1,
        "max_tokens": 1800,
    }
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    timeout = max(float(settings.llm_request_timeout_seconds or 15.0), 1.0)
    last_error: Exception | None = None
    with httpx.Client(timeout=timeout) as client:
        for _attempt in range(LLM_GATEWAY_ATTEMPTS):
            try:
                response = client.post(f"{base_url}/chat/completions", headers=headers, json=payload)
                response.raise_for_status()
                try:
                    return response.json()
                except ValueError as exc:
                    last_error = ValueError(
                        f"LLM gateway returned non-JSON response body: status={response.status_code}, bytes={len(response.content)}"
                    )
                    continue
            except httpx.HTTPError as exc:
                last_error = exc
                continue
    raise last_error or ValueError("LLM gateway request failed")


def _build_intake_prompt_messages(
    *,
    message: str,
    brief_json: dict[str, Any],
    history: Iterable[Any],
    deterministic_analysis: dict[str, Any],
) -> list[dict[str, str]]:
    system_prompt = """
You are the structured intake extraction module for AI Architect.

Goal:
- Extract homeowner intent from natural Vietnamese/English chat into a concept-design brief.
- This is for early concept review only, not construction documents.
- Return only valid JSON. Do not wrap it in Markdown.

Allowed top-level brief_patch fields:
- project_type: townhouse | villa | apartment_reno | shophouse | home_office
- project_mode: new_build | renovation
- location: short free text
- lot: {width_m, depth_m, area_m2, buildable_area_m2, orientation, frontage_m, access}
- floors: number
- rooms: {bedrooms, bathrooms, wc, parking, workspaces}
- style, material_direction, color_direction
- budget_vnd, timeline_months, occupant_count
- household_profile, renovation_scope
- special_requests, lifestyle_priorities, must_haves, must_not_haves
- design_goals, space_requests, spatial_preferences, notes

Extraction rules:
- Preserve the current brief unless the latest user message clearly changes it.
- Use brief_patch only for facts or careful design-intent inferences grounded in the conversation.
- Interpret "nhà vườn" as villa unless the user says apartment/shophouse/townhouse.
- Distinguish total land/site area from buildable/construction footprint. For "diện tích xây dựng 110m2", use lot.buildable_area_m2.
- Capture WC/nhà vệ sinh/phòng tắm as rooms.bathrooms.
- Capture phòng đọc, thư viện, phòng làm việc, WFH as space_requests or rooms.workspaces.
- Capture elders/children/daylight/ventilation/garden/nature as lifestyle/design priorities.
- If unsure, leave the field out and add a concise note or follow-up need through captured_facts/conflicts.
- Never claim permit, legal, structural, MEP, geotechnical, code, or construction readiness.
- Do not output keys outside the schema.

Return JSON exactly shaped like:
{
  "brief_patch": {},
  "captured_facts": [{"key": "string", "label": "Vietnamese label", "value": "short customer-readable value"}],
  "conflicts": [{"title": "short Vietnamese title", "detail": "short Vietnamese detail"}],
  "confidence": 0.0
}
""".strip()

    user_payload = {
        "current_brief_json": brief_json,
        "recent_history": _serialize_history(history),
        "latest_user_message": _truncate(message, MAX_MESSAGE_CHARS),
        "deterministic_draft": {
            "brief_json": deterministic_analysis.get("brief_json", {}),
            "captured_facts": deterministic_analysis.get("captured_facts", []),
            "conflicts": deterministic_analysis.get("conflicts", []),
        },
    }
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False, sort_keys=True)},
    ]


def _analysis_from_llm_payload(
    deterministic_analysis: dict[str, Any],
    llm_payload: dict[str, Any],
) -> dict[str, Any]:
    patch = _sanitize_brief_patch(llm_payload.get("brief_patch"))
    merged_brief = merge_brief(deterministic_analysis["brief_json"], patch)
    captured_facts = _dedupe_facts(
        [*list(deterministic_analysis.get("captured_facts") or []), *_sanitize_facts(llm_payload.get("captured_facts"))]
    )
    conflicts = _dedupe_conflicts(
        [*list(deterministic_analysis.get("conflicts") or []), *_sanitize_conflicts(llm_payload.get("conflicts"))]
    )
    return {
        "brief_json": merged_brief,
        "captured_facts": captured_facts,
        "conflicts": conflicts,
        "project_switched": deterministic_analysis.get("project_switched", False),
    }


def _sanitize_brief_patch(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    patch: dict[str, Any] = {}
    for key, raw in value.items():
        if key not in ALLOWED_BRIEF_KEYS or key in UNSAFE_PATCH_KEYS:
            continue
        if key == "lot":
            lot = _sanitize_nested_mapping(raw, ALLOWED_LOT_KEYS)
            if lot:
                patch[key] = lot
            continue
        if key == "rooms":
            rooms = _sanitize_nested_mapping(raw, ALLOWED_ROOM_KEYS)
            if rooms:
                patch[key] = rooms
            continue
        if key in ALLOWED_NUMBER_KEYS:
            number = _coerce_positive_number(raw)
            if number is not None:
                patch[key] = int(number)
            continue
        if key in ALLOWED_SCALAR_KEYS:
            scalar = _coerce_short_string(raw)
            if scalar:
                patch[key] = scalar
            continue
        if key in ALLOWED_LIST_KEYS:
            items = _coerce_string_list(raw)
            if items:
                patch[key] = items
    return patch


def _sanitize_nested_mapping(value: Any, allowed_keys: set[str]) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    nested: dict[str, Any] = {}
    for key, raw in value.items():
        if key not in allowed_keys or key in UNSAFE_PATCH_KEYS:
            continue
        if key.endswith("_m") or key.endswith("_m2") or key in {"bedrooms", "bathrooms", "wc", "parking", "workspaces"}:
            number = _coerce_positive_number(raw)
            if number is not None:
                nested[key] = int(number) if float(number).is_integer() else number
            continue
        scalar = _coerce_short_string(raw)
        if scalar:
            nested[key] = scalar
    return nested


def _coerce_positive_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        number = float(value)
    elif isinstance(value, str):
        match = re.search(r"\d+(?:[.,]\d+)?", value)
        if not match:
            return None
        number = float(match.group(0).replace(",", "."))
    else:
        return None
    if number <= 0:
        return None
    return round(number, 2)


def _coerce_short_string(value: Any, max_length: int = 160) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = re.sub(r"\s+", " ", value).strip()
    return cleaned[:max_length] if cleaned else None


def _coerce_string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return []
    items: list[str] = []
    for item in value:
        cleaned = _coerce_short_string(item)
        if cleaned and cleaned not in items:
            items.append(cleaned)
    return items[:12]


def _sanitize_facts(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    facts: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        key = _coerce_short_string(item.get("key"), max_length=80)
        label = _coerce_short_string(item.get("label"), max_length=80)
        fact_value = _coerce_short_string(item.get("value"), max_length=180)
        if key and label and fact_value:
            facts.append({"key": key, "label": label, "value": fact_value})
    return facts[:12]


def _sanitize_conflicts(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    conflicts: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        title = _coerce_short_string(item.get("title"), max_length=120)
        detail = _coerce_short_string(item.get("detail"), max_length=300)
        if title and detail:
            conflicts.append({"title": title, "detail": detail})
    return conflicts[:6]


def _dedupe_facts(facts: list[dict[str, str]]) -> list[dict[str, str]]:
    deduped: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for fact in facts:
        marker = (fact.get("key", ""), fact.get("value", ""))
        if marker in seen:
            continue
        seen.add(marker)
        deduped.append(fact)
    return deduped[:12]


def _dedupe_conflicts(conflicts: list[dict[str, str]]) -> list[dict[str, str]]:
    deduped: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for conflict in conflicts:
        marker = (conflict.get("title", ""), conflict.get("detail", ""))
        if marker in seen:
            continue
        seen.add(marker)
        deduped.append(conflict)
    return deduped[:6]


def _extract_chat_content(response: dict[str, Any]) -> str:
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ValueError("LLM response did not include choices")
    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    content = message.get("content") if isinstance(message, dict) else None
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, dict) and isinstance(part.get("text"), str):
                parts.append(part["text"])
        if parts:
            return "\n".join(parts)
    raise ValueError("LLM response did not include text content")


def _extract_json_object(content: str) -> dict[str, Any]:
    cleaned = content.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        loaded = json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise
        loaded = json.loads(cleaned[start : end + 1])
    if not isinstance(loaded, dict):
        raise ValueError("LLM JSON payload must be an object")
    return loaded


def _serialize_history(history: Iterable[Any]) -> list[dict[str, str]]:
    items = list(history or [])[-MAX_HISTORY_MESSAGES:]
    serialized: list[dict[str, str]] = []
    for item in items:
        role = getattr(item, "role", None)
        content = getattr(item, "content", None)
        if isinstance(item, dict):
            role = item.get("role", role)
            content = item.get("content", content)
        if not role or not content:
            continue
        serialized.append({"role": str(role), "content": _truncate(str(content), MAX_MESSAGE_CHARS)})
    return serialized


def _truncate(value: str, max_chars: int) -> str:
    return value if len(value) <= max_chars else f"{value[:max_chars]}..."


def _safe_error_message(exc: Exception) -> str:
    text = str(exc).strip() or exc.__class__.__name__
    text = re.sub(r"sk-[A-Za-z0-9_-]+", "sk-***", text)
    return _truncate(text, 240)
