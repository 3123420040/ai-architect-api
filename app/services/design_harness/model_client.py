from __future__ import annotations

from typing import Any

from app.services import llm
from app.services.briefing import analyze_message_to_brief


class ExistingIntakeModelClient:
    """Adapter around the current deterministic plus OpenAI-compatible intake path."""

    def generate_turn(self, context: dict[str, Any]) -> dict[str, Any]:
        message = str(context.get("message") or "")
        brief_json = context.get("brief_json") or {}
        history_items = list(context.get("history") or [])
        deterministic_analysis = analyze_message_to_brief(message, brief_json)

        if not llm.llm_is_configured():
            harness_trace = llm._build_harness_trace(
                source=llm.DETERMINISTIC_SOURCE,
                message=message,
                brief_json=brief_json,
                history=history_items,
                deterministic_analysis=deterministic_analysis,
                merged_brief=deterministic_analysis["brief_json"],
                validation_gates=[
                    llm._trace_gate("deterministic_analysis", "pass"),
                    llm._trace_gate("llm_configured", "skipped", "missing_base_url_or_key_or_model"),
                    llm._trace_gate("deterministic_merge", "pass"),
                ],
            )
            return llm._build_turn_from_analysis(
                message,
                deterministic_analysis,
                source=llm.DETERMINISTIC_SOURCE,
                source_metadata={
                    "provider": "none",
                    "provider_family": "none",
                    "model": None,
                    "prompt": llm.INTAKE_PROMPT_ID,
                    "prompt_id": llm.INTAKE_PROMPT_ID,
                },
                harness_trace=harness_trace,
            )

        try:
            llm_payload, llm_trace_updates = llm._call_intake_llm(
                message=message,
                brief_json=brief_json,
                history=history_items,
                deterministic_analysis=deterministic_analysis,
            )
            analysis = llm._analysis_from_llm_payload(deterministic_analysis, llm_payload)
            sanitized_patch = llm._sanitize_brief_patch(llm_payload.get("brief_patch"))
            harness_trace = llm._build_harness_trace(
                source=llm.LLM_SOURCE,
                message=message,
                brief_json=brief_json,
                history=history_items,
                deterministic_analysis=deterministic_analysis,
                merged_brief=analysis["brief_json"],
                llm_response_byte_count=llm_trace_updates.get("llm_response_byte_count"),
                parsed_payload_summary=llm._summarize_llm_payload(llm_payload),
                validation_gates=[
                    llm._trace_gate("deterministic_analysis", "pass"),
                    llm._trace_gate("llm_configured", "pass"),
                    *llm._trace_gates_from_updates(llm_trace_updates),
                    llm._trace_gate(
                        "brief_patch_sanitized",
                        "pass",
                        f"accepted={len(llm._flatten_keys(sanitized_patch))}",
                    ),
                    llm._trace_gate("brief_merge", "pass"),
                ],
            )
            return llm._build_turn_from_analysis(
                message,
                analysis,
                source=llm.LLM_SOURCE,
                source_metadata={
                    "provider": "openai_compat",
                    "provider_family": "openai_compat",
                    "model": llm.settings.openai_compat_model,
                    "prompt": llm.INTAKE_PROMPT_ID,
                    "prompt_id": llm.INTAKE_PROMPT_ID,
                    "confidence": llm_payload.get("confidence"),
                },
                harness_trace=harness_trace,
            )
        except Exception as exc:
            fallback_reason = llm._safe_error_message(exc)
            trace_updates = exc.trace_updates if isinstance(exc, llm.LLMIntakeError) else {}
            harness_trace = llm._build_harness_trace(
                source=llm.FALLBACK_SOURCE,
                message=message,
                brief_json=brief_json,
                history=history_items,
                deterministic_analysis=deterministic_analysis,
                merged_brief=deterministic_analysis["brief_json"],
                llm_response_byte_count=trace_updates.get("llm_response_byte_count"),
                parsed_payload_summary=trace_updates.get("parsed_payload_summary", {}),
                validation_gates=[
                    llm._trace_gate("deterministic_analysis", "pass"),
                    llm._trace_gate("llm_configured", "pass"),
                    *llm._trace_gates_from_updates(trace_updates),
                    llm._trace_gate("deterministic_fallback", "pass", fallback_reason),
                ],
                fallback_reason=fallback_reason,
            )
            return llm._build_turn_from_analysis(
                message,
                deterministic_analysis,
                source=llm.FALLBACK_SOURCE,
                source_metadata={
                    "provider": "openai_compat",
                    "provider_family": "openai_compat",
                    "model": llm.settings.openai_compat_model,
                    "prompt": llm.INTAKE_PROMPT_ID,
                    "prompt_id": llm.INTAKE_PROMPT_ID,
                    "fallback_reason": fallback_reason,
                },
                harness_trace=harness_trace,
            )
