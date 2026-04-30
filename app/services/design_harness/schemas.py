from __future__ import annotations

from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from typing import Any


FieldReadinessStatus = str
AssumptionSource = str
AssumptionLifecycleStatus = str


@dataclass(frozen=True)
class DesignHarnessTurnRequest:
    message: str
    brief_json: dict[str, Any] | None = None
    history: Iterable[Any] = field(default_factory=list)


@dataclass(frozen=True)
class HarnessConversationOutput:
    assistant_response: str
    assistant_payload: dict[str, Any] = field(default_factory=dict)
    needs_follow_up: bool = True
    follow_up_topics: list[str] = field(default_factory=list)
    conflicts: list[dict[str, str]] = field(default_factory=list)
    clarification_state: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class HarnessMachineOutput:
    brief_json: dict[str, Any] = field(default_factory=dict)
    source: str = "deterministic"
    readiness: dict[str, Any] = field(default_factory=dict)
    assumptions: list[dict[str, Any]] = field(default_factory=list)
    style_tools: dict[str, Any] = field(default_factory=dict)
    concept_design_input: dict[str, Any] | None = None
    concept_input_validation: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DesignAssumption:
    id: str
    field_path: str
    value: Any
    source: AssumptionSource
    confidence: float
    needs_confirmation: bool
    explanation: str
    status: AssumptionLifecycleStatus = "proposed"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["confidence"] = round(float(self.confidence), 2)
        return payload


@dataclass(frozen=True)
class DesignHarnessFieldStatus:
    field_path: str
    status: FieldReadinessStatus
    value: Any = None
    source: AssumptionSource | None = None
    confidence: float = 0.0
    required: bool = False
    blocks_concept_input: bool = False
    evidence: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["confidence"] = round(float(self.confidence), 2)
        return payload


@dataclass(frozen=True)
class DesignHarnessReadiness:
    schema_version: str
    status: str
    confidence: float
    safe_to_emit_concept_input: bool
    critical_missing: list[str] = field(default_factory=list)
    optional_missing: list[str] = field(default_factory=list)
    confirmed_fields: list[str] = field(default_factory=list)
    inferred_fields: list[str] = field(default_factory=list)
    defaulted_fields: list[str] = field(default_factory=list)
    conflicting_fields: list[str] = field(default_factory=list)
    assumptions_requiring_confirmation: list[str] = field(default_factory=list)
    field_statuses: dict[str, dict[str, Any]] = field(default_factory=dict)
    source: str = "brief_clarification_state"
    legacy_clarification: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["confidence"] = round(float(self.confidence), 2)
        return payload


@dataclass(frozen=True)
class HarnessTraceMetadata:
    harness_id: str = "design_intake_harness"
    harness_version: str = "h2_core_wrapper_v1"
    terminal_reason: str = "turn_completed"
    trace: dict[str, Any] = field(default_factory=dict)
    validation_gates: list[dict[str, str]] = field(default_factory=list)

    def public_summary(self) -> dict[str, Any]:
        return {
            "harness_id": self.harness_id,
            "harness_version": self.harness_version,
            "terminal_reason": self.terminal_reason,
            "source": self.trace.get("source"),
            "trace_schema_version": self.trace.get("schema_version"),
            "prompt_id": self.trace.get("prompt_id"),
        }


@dataclass(frozen=True)
class DesignHarnessTurnResult:
    conversation: HarnessConversationOutput
    machine: HarnessMachineOutput
    trace_metadata: HarnessTraceMetadata

    @property
    def assistant_response(self) -> str:
        return self.conversation.assistant_response

    @property
    def assistant_payload(self) -> dict[str, Any]:
        return self.conversation.assistant_payload

    @property
    def brief_json(self) -> dict[str, Any]:
        return self.machine.brief_json

    @property
    def needs_follow_up(self) -> bool:
        return self.conversation.needs_follow_up

    @property
    def source(self) -> str:
        return self.machine.source

    @property
    def follow_up_topics(self) -> list[str]:
        return self.conversation.follow_up_topics

    @property
    def conflicts(self) -> list[dict[str, str]]:
        return self.conversation.conflicts

    @property
    def clarification_state(self) -> dict[str, Any]:
        return self.conversation.clarification_state

    @property
    def harness_trace(self) -> dict[str, Any]:
        return self.trace_metadata.trace

    def as_legacy_turn(self) -> dict[str, Any]:
        harness = self.trace_metadata.public_summary()
        harness["readiness"] = self.machine.readiness
        harness["assumptions"] = self.machine.assumptions
        harness["concept_input_status"] = self.machine.concept_input_validation.get("status")
        harness["concept_input_available"] = self.machine.concept_design_input is not None
        harness["concept_input_validation"] = self.machine.concept_input_validation
        if self.machine.concept_design_input is not None:
            harness["concept_design_input"] = self.machine.concept_design_input
            harness["latest_concept_input_snapshot"] = {
                "schema_version": self.machine.concept_design_input.get("schema_version"),
                "payload": self.machine.concept_design_input,
                "validation": self.machine.concept_input_validation,
            }
        return {
            "assistant_response": self.conversation.assistant_response,
            "assistant_payload": self.conversation.assistant_payload,
            "brief_json": self.machine.brief_json,
            "needs_follow_up": self.conversation.needs_follow_up,
            "source": self.machine.source,
            "follow_up_topics": self.conversation.follow_up_topics,
            "conflicts": self.conversation.conflicts,
            "clarification_state": self.conversation.clarification_state,
            "harness_trace": self.trace_metadata.trace,
            "harness": harness,
            "harness_machine_output": {
                "readiness": self.machine.readiness,
                "assumptions": self.machine.assumptions,
                "style_tools": self.machine.style_tools,
                "concept_design_input": self.machine.concept_design_input,
                "concept_input_validation": self.machine.concept_input_validation,
            },
        }

    @classmethod
    def from_legacy_turn(
        cls,
        turn: dict[str, Any],
        *,
        readiness: dict[str, Any] | None = None,
        assumptions: list[dict[str, Any]] | None = None,
        style_tools: dict[str, Any] | None = None,
        concept_design_input: dict[str, Any] | None = None,
        concept_input_validation: dict[str, Any] | None = None,
        terminal_reason: str = "turn_completed",
    ) -> "DesignHarnessTurnResult":
        trace = turn.get("harness_trace") or {}
        conversation = HarnessConversationOutput(
            assistant_response=turn["assistant_response"],
            assistant_payload=turn.get("assistant_payload", {}),
            needs_follow_up=bool(turn.get("needs_follow_up", True)),
            follow_up_topics=list(turn.get("follow_up_topics") or []),
            conflicts=list(turn.get("conflicts") or []),
            clarification_state=turn.get("clarification_state") or {},
        )
        machine = HarnessMachineOutput(
            brief_json=turn.get("brief_json") or {},
            source=str(turn.get("source") or "deterministic"),
            readiness=readiness or {},
            assumptions=assumptions or [],
            style_tools=style_tools or {},
            concept_design_input=concept_design_input,
            concept_input_validation=concept_input_validation or {},
        )
        trace_metadata = HarnessTraceMetadata(
            terminal_reason=terminal_reason,
            trace=trace,
            validation_gates=list(trace.get("validation_gates") or []),
        )
        return cls(conversation=conversation, machine=machine, trace_metadata=trace_metadata)


@dataclass(frozen=True)
class HarnessToolEvidence:
    signal: str
    source_tag: str
    polarity: str = "positive"
    confidence: float | None = None

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "signal": self.signal,
            "source_tag": self.source_tag,
            "polarity": self.polarity,
        }
        if self.confidence is not None:
            payload["confidence"] = self.confidence
        return payload


@dataclass(frozen=True)
class HarnessStyleCandidateOutput:
    style_id: str
    display_name: str
    confidence: float
    evidence: tuple[HarnessToolEvidence, ...] = field(default_factory=tuple)

    def as_dict(self) -> dict[str, Any]:
        return {
            "style_id": self.style_id,
            "display_name": self.display_name,
            "confidence": self.confidence,
            "evidence": [item.as_dict() for item in self.evidence],
            "source_tags": sorted({item.source_tag for item in self.evidence}),
        }


@dataclass(frozen=True)
class HarnessStyleToolOutput:
    schema_version: str
    selected_style_id: str | None
    candidates: tuple[HarnessStyleCandidateOutput, ...]
    evidence: tuple[HarnessToolEvidence, ...]
    source_tags: tuple[str, ...]
    confidence: float
    needs_confirmation: bool
    confirmation_question: str | None
    customer_understanding: dict[str, Any]
    style_profile: dict[str, Any] | None = None
    pattern_memory: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    dislike_suppression: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    reference_descriptor_matches: tuple[dict[str, Any], ...] = field(default_factory=tuple)

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "selected_style_id": self.selected_style_id,
            "candidates": [candidate.as_dict() for candidate in self.candidates],
            "evidence": [item.as_dict() for item in self.evidence],
            "source_tags": list(self.source_tags),
            "confidence": self.confidence,
            "needs_confirmation": self.needs_confirmation,
            "confirmation_question": self.confirmation_question,
            "customer_understanding": self.customer_understanding,
            "style_profile": self.style_profile,
            "pattern_memory": list(self.pattern_memory),
            "dislike_suppression": list(self.dislike_suppression),
            "reference_descriptor_matches": list(self.reference_descriptor_matches),
        }


@dataclass(frozen=True)
class FieldProvenance:
    field_path: str
    source: str
    confidence: float
    evidence: list[dict[str, Any]] = field(default_factory=list)
    assumption_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["confidence"] = round(float(self.confidence), 2)
        return payload


@dataclass(frozen=True)
class ConceptDesignInputV1:
    project: dict[str, Any]
    site: dict[str, Any]
    program: dict[str, Any]
    household: dict[str, Any]
    style: dict[str, Any]
    layout_intent: dict[str, Any]
    assumptions: list[dict[str, Any]]
    provenance: list[dict[str, Any]]
    schema_version: str = "concept_design_input_v1"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "project": self.project,
            "site": self.site,
            "program": self.program,
            "household": self.household,
            "style": self.style,
            "layout_intent": self.layout_intent,
            "assumptions": self.assumptions,
            "provenance": self.provenance,
        }


@dataclass(frozen=True)
class ConceptInputCompilationResult:
    concept_design_input: dict[str, Any] | None
    validation: dict[str, Any]

    @property
    def is_valid(self) -> bool:
        return self.concept_design_input is not None and self.validation.get("status") == "valid"
