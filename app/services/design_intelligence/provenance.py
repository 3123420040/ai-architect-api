from __future__ import annotations

from dataclasses import dataclass
from typing import Any


ALLOWED_DECISION_SOURCES = {
    "user_fact",
    "reference_image",
    "style_profile",
    "pattern_memory",
    "rule_default",
    "ai_proposal",
    "reviewer_override",
}

AI_OR_DEFAULT_DECISION_SOURCES = {
    "reference_image",
    "style_profile",
    "pattern_memory",
    "rule_default",
    "ai_proposal",
}


class ProvenanceError(ValueError):
    pass


@dataclass(frozen=True)
class DecisionValue:
    value: Any
    source: str
    confidence: float
    assumption: bool
    customer_visible_explanation: str
    needs_confirmation: bool = False

    def __post_init__(self) -> None:
        if self.source not in ALLOWED_DECISION_SOURCES:
            raise ProvenanceError(f"Unsupported decision source: {self.source}")
        if not 0.0 <= float(self.confidence) <= 1.0:
            raise ProvenanceError("Decision confidence must be between 0 and 1")
        if self.source in AI_OR_DEFAULT_DECISION_SOURCES and self.assumption is not True:
            raise ProvenanceError(f"{self.source} decisions must be marked as assumptions")
        if not self.customer_visible_explanation:
            raise ProvenanceError("DecisionValue needs a customer-visible explanation")
        if not isinstance(self.needs_confirmation, bool):
            raise ProvenanceError("DecisionValue needs_confirmation must be a boolean")

    def as_dict(self) -> dict[str, Any]:
        return {
            "value": self.value,
            "source": self.source,
            "confidence": self.confidence,
            "assumption": self.assumption,
            "customer_visible_explanation": self.customer_visible_explanation,
            "needs_confirmation": self.needs_confirmation,
        }


def user_fact(value: Any, explanation: str, *, confidence: float = 1.0) -> DecisionValue:
    return DecisionValue(
        value=value,
        source="user_fact",
        confidence=confidence,
        assumption=False,
        customer_visible_explanation=explanation,
        needs_confirmation=False,
    )


def rule_default(value: Any, explanation: str, *, confidence: float = 0.72, needs_confirmation: bool = False) -> DecisionValue:
    return DecisionValue(
        value=value,
        source="rule_default",
        confidence=confidence,
        assumption=True,
        customer_visible_explanation=explanation,
        needs_confirmation=needs_confirmation,
    )


def ai_proposal(value: Any, explanation: str, *, confidence: float, needs_confirmation: bool = False) -> DecisionValue:
    return DecisionValue(
        value=value,
        source="ai_proposal",
        confidence=confidence,
        assumption=True,
        customer_visible_explanation=explanation,
        needs_confirmation=needs_confirmation,
    )


def reference_image(value: Any, explanation: str, *, confidence: float = 0.68, needs_confirmation: bool = True) -> DecisionValue:
    return DecisionValue(
        value=value,
        source="reference_image",
        confidence=confidence,
        assumption=True,
        customer_visible_explanation=explanation,
        needs_confirmation=needs_confirmation,
    )


def style_profile(value: Any, style_id: str, explanation: str, *, confidence: float = 0.72, needs_confirmation: bool = False) -> DecisionValue:
    return DecisionValue(
        value=value,
        source="style_profile",
        confidence=confidence,
        assumption=True,
        customer_visible_explanation=f"{explanation} Nguồn style: {style_id}.",
        needs_confirmation=needs_confirmation,
    )


def pattern_memory(value: Any, pattern_id: str, explanation: str, *, confidence: float = 0.7, needs_confirmation: bool = False) -> DecisionValue:
    return DecisionValue(
        value=value,
        source="pattern_memory",
        confidence=confidence,
        assumption=True,
        customer_visible_explanation=f"{explanation} Mẫu tham chiếu: {pattern_id}.",
        needs_confirmation=needs_confirmation,
    )


def reviewer_override(value: Any, explanation: str, *, confidence: float = 0.85, assumption: bool = False) -> DecisionValue:
    return DecisionValue(
        value=value,
        source="reviewer_override",
        confidence=confidence,
        assumption=assumption,
        customer_visible_explanation=explanation,
        needs_confirmation=False,
    )
