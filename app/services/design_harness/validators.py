from __future__ import annotations

from typing import Any

from app.services.design_harness.compiler import compile_concept_design_input, validate_concept_design_input
from app.services.design_harness.readiness import compute_design_harness_readiness


class DesignHarnessValidator:
    """H2 pass-through validation boundary for future readiness and assumption gates."""

    def validate_turn(self, turn: dict[str, Any]) -> dict[str, Any]:
        required = ("assistant_response", "brief_json", "source", "harness_trace")
        missing = [key for key in required if key not in turn]
        if missing:
            raise ValueError(f"Design harness turn missing required fields: {', '.join(missing)}")
        return turn

    def compute_readiness(self, turn: dict[str, Any], *, latest_message: str = "") -> tuple[dict[str, Any], list[dict[str, Any]]]:
        clarification_state = turn.get("clarification_state") or {}
        return compute_design_harness_readiness(
            brief=turn.get("brief_json") or {},
            clarification_state=clarification_state,
            conflicts=list(turn.get("conflicts") or []),
            latest_message=latest_message,
        )

    def readiness_stub(self, turn: dict[str, Any]) -> dict[str, Any]:
        readiness, _assumptions = self.compute_readiness(turn)
        return readiness

    def assumptions_stub(self, turn: dict[str, Any]) -> list[dict[str, Any]]:
        _readiness, assumptions = self.compute_readiness(turn)
        return assumptions

    def compile_concept_input(
        self,
        *,
        project_id: str,
        project_name: str | None,
        brief: dict[str, Any],
        readiness: dict[str, Any],
        assumptions: list[dict[str, Any]],
        style_tools: dict[str, Any],
    ) -> tuple[dict[str, Any] | None, dict[str, Any]]:
        result = compile_concept_design_input(
            project_id=project_id,
            project_name=project_name,
            brief=brief,
            readiness=readiness,
            assumptions=assumptions,
            style_tools=style_tools,
        )
        return result.concept_design_input, result.validation

    def validate_concept_input(self, payload: dict[str, Any], *, readiness: dict[str, Any]) -> dict[str, Any]:
        return validate_concept_design_input(payload, readiness=readiness)
