from __future__ import annotations

from typing import Any


class DesignHarnessTraceStore:
    """Builds the metadata persisted by the chat API.

    H1 stores sanitized trace summaries in ChatMessage.message_metadata. H2 keeps that
    storage path and adds only a small harness envelope for forward compatibility.
    """

    def build_message_metadata(
        self,
        *,
        turn: dict[str, Any],
        clarification_state: dict[str, Any],
        brief_contract: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "needs_follow_up": turn["needs_follow_up"],
            "follow_up_topics": turn["follow_up_topics"],
            "source": turn["source"],
            "assistant_payload": turn.get("assistant_payload", {}),
            "conflicts": turn.get("conflicts", []),
            "clarification_state": clarification_state,
            "brief_contract": brief_contract,
            "harness_trace": turn.get("harness_trace", {}),
            "harness": turn.get("harness", {}),
        }
