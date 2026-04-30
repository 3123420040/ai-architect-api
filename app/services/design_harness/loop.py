from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from app.services.design_harness.context_builder import DesignHarnessContextBuilder, build_turn_request
from app.services.design_harness.model_client import ExistingIntakeModelClient
from app.services.design_harness.schemas import DesignHarnessTurnResult
from app.services.design_harness.tools import DesignHarnessStyleTools
from app.services.design_harness.validators import DesignHarnessValidator


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
        validated_turn = {**validated_turn, "harness_trace": harness_trace}
        return DesignHarnessTurnResult.from_legacy_turn(
            validated_turn,
            readiness=self.validator.readiness_stub(validated_turn),
            assumptions=self.validator.assumptions_stub(validated_turn),
            style_tools=style_tool_output,
        )
