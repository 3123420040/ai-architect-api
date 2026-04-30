from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from app.services.design_harness.context_builder import DesignHarnessContextBuilder, build_turn_request
from app.services.design_harness.model_client import ExistingIntakeModelClient
from app.services.design_harness.schemas import DesignHarnessTurnResult
from app.services.design_harness.validators import DesignHarnessValidator


class DesignIntakeHarnessLoop:
    def __init__(
        self,
        *,
        context_builder: DesignHarnessContextBuilder | None = None,
        model_client: ExistingIntakeModelClient | None = None,
        validator: DesignHarnessValidator | None = None,
    ) -> None:
        self.context_builder = context_builder or DesignHarnessContextBuilder()
        self.model_client = model_client or ExistingIntakeModelClient()
        self.validator = validator or DesignHarnessValidator()

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
        return DesignHarnessTurnResult.from_legacy_turn(
            validated_turn,
            readiness=self.validator.readiness_stub(validated_turn),
            assumptions=self.validator.assumptions_stub(validated_turn),
        )
