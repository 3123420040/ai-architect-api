from __future__ import annotations

from typing import Any


class DesignHarnessValidator:
    """H2 pass-through validation boundary for future readiness and assumption gates."""

    def validate_turn(self, turn: dict[str, Any]) -> dict[str, Any]:
        required = ("assistant_response", "brief_json", "source", "harness_trace")
        missing = [key for key in required if key not in turn]
        if missing:
            raise ValueError(f"Design harness turn missing required fields: {', '.join(missing)}")
        return turn

    def readiness_stub(self, turn: dict[str, Any]) -> dict[str, Any]:
        clarification_state = turn.get("clarification_state") or {}
        return {
            "schema_version": "design_harness_readiness_stub_v1",
            "status": clarification_state.get("readiness_label", "pass_through"),
            "source": "brief_clarification_state",
            "field_statuses": {},
        }

    def assumptions_stub(self, turn: dict[str, Any]) -> list[dict[str, Any]]:
        return []
