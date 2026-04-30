from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from app.services.design_harness.schemas import DesignHarnessTurnRequest


class DesignHarnessContextBuilder:
    def build(self, request: DesignHarnessTurnRequest) -> dict[str, Any]:
        history_items = list(request.history or [])
        return {
            "message": request.message,
            "brief_json": request.brief_json or {},
            "history": history_items,
            "history_count": len(history_items),
        }


def build_turn_request(message: str, brief_json: dict | None, history: Iterable[Any]) -> DesignHarnessTurnRequest:
    return DesignHarnessTurnRequest(message=message, brief_json=brief_json or {}, history=list(history or []))
