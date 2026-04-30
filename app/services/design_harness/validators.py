from __future__ import annotations

from typing import Any

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
