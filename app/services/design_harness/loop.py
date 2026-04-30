from __future__ import annotations

import copy
from collections.abc import Iterable
from typing import Any

from app.services.design_harness.context_builder import DesignHarnessContextBuilder, build_turn_request
from app.services.design_harness.model_client import ExistingIntakeModelClient
from app.services.design_harness.schemas import DesignHarnessTurnResult
from app.services.design_harness.tools import DesignHarnessStyleTools
from app.services.design_harness.validators import DesignHarnessValidator


ASSUMPTION_LABELS = {
    "project_mode": "Phạm vi dự án",
    "floors": "Số tầng dự kiến",
    "program.bedrooms": "Số phòng ngủ",
    "program.bathrooms": "Số WC",
    "renovation_scope": "Phạm vi cải tạo",
    "style": "Hướng phong cách",
}


class DesignIntakeHarnessLoop:
    def __init__(
        self,
        *,
        context_builder: DesignHarnessContextBuilder | None = None,
        model_client: ExistingIntakeModelClient | None = None,
        validator: DesignHarnessValidator | None = None,
        style_tools: DesignHarnessStyleTools | None = None,
    ) -> None:
        self.context_builder = context_builder or DesignHarnessContextBuilder()
        self.model_client = model_client or ExistingIntakeModelClient()
        self.validator = validator or DesignHarnessValidator()
        self.style_tools = style_tools or DesignHarnessStyleTools()

    def run(
        self,
        message: str,
        brief_json: dict | None = None,
        history: Iterable[Any] | None = None,
    ) -> DesignHarnessTurnResult:
        request = build_turn_request(message, brief_json, history or [])
        context = self.context_builder.build(request)
        turn = self.model_client.generate_turn(context)
        validated_turn = self.validator.validate_turn(turn)

        style_tool_output = self.style_tools.run(
            str(context.get("message") or ""),
            brief_json=context.get("brief_json") or {},
        ).as_dict()
        harness_trace = dict(validated_turn.get("harness_trace") or {})
        validation_gates = list(harness_trace.get("validation_gates") or [])
        validation_gates.append({"name": "style_pattern_tools", "status": "pass"})
        harness_trace["validation_gates"] = validation_gates
        assistant_payload = dict(validated_turn.get("assistant_payload") or {})
        source_metadata = dict(assistant_payload.get("source_metadata") or {})
        if source_metadata:
            source_metadata["trace_summary"] = harness_trace
            assistant_payload["source_metadata"] = source_metadata
        validated_turn = {**validated_turn, "assistant_payload": assistant_payload, "harness_trace": harness_trace}

        readiness, assumptions = self.validator.compute_readiness(validated_turn, latest_message=request.message)
        enriched_turn = _attach_readiness_to_turn(validated_turn, readiness, assumptions)
        return DesignHarnessTurnResult.from_legacy_turn(
            enriched_turn,
            readiness=readiness,
            assumptions=assumptions,
            style_tools=style_tool_output,
            terminal_reason=_terminal_reason(readiness),
        )


def _terminal_reason(readiness: dict[str, Any]) -> str:
    status = readiness.get("status")
    if status == "blocked_by_safety_scope":
        return "blocked"
    if status in {"missing_critical", "partial_with_assumptions", "conflicting"}:
        return "needs_user_input"
    return "turn_completed"


def _attach_readiness_to_turn(
    turn: dict[str, Any],
    readiness: dict[str, Any],
    assumptions: list[dict[str, Any]],
) -> dict[str, Any]:
    enriched = copy.deepcopy(turn)
    assistant_payload = dict(enriched.get("assistant_payload") or {})
    assistant_payload["design_harness_readiness"] = {
        "status": readiness.get("status"),
        "confidence": readiness.get("confidence"),
        "safe_to_emit_concept_input": readiness.get("safe_to_emit_concept_input"),
        "critical_missing": list(readiness.get("critical_missing") or []),
    }
    assistant_payload["design_assumptions"] = assumptions

    if readiness.get("status") == "blocked_by_safety_scope":
        enriched["assistant_response"] = _append_safety_scope_note(enriched.get("assistant_response", ""))
    elif assumptions:
        next_prompts = list(assistant_payload.get("next_prompts") or [])
        if len(next_prompts) > 2:
            assistant_payload["next_prompts"] = next_prompts[:2]
        enriched["assistant_response"] = _append_assumptions(enriched.get("assistant_response", ""), assumptions)

    enriched["assistant_payload"] = assistant_payload
    return enriched


def _append_assumptions(assistant_response: str, assumptions: list[dict[str, Any]]) -> str:
    proposed = [item for item in assumptions if item.get("needs_confirmation")][:4]
    if not proposed:
        return assistant_response
    lines = ["", "Tạm giả định để anh/chị xác nhận nhanh:"]
    for item in proposed:
        value = item.get("value")
        label = ASSUMPTION_LABELS.get(str(item.get("field_path") or ""), item.get("field_path"))
        lines.append(f"- {label}: {value} ({item.get('source')}, cần xác nhận)")
    return f"{assistant_response.rstrip()}\n" + "\n".join(lines)


def _append_safety_scope_note(assistant_response: str) -> str:
    note = (
        "Lưu ý: harness chỉ đánh giá brief ở mức concept design; các nội dung xin phép, pháp lý, "
        "kết cấu, MEP, địa chất, quy chuẩn hoặc thi công cần chuyên gia có thẩm quyền xác nhận riêng."
    )
    return f"{assistant_response.rstrip()}\n\n{note}"
