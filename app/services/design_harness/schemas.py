from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any


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
            "harness": self.trace_metadata.public_summary(),
            "harness_machine_output": {
                "readiness": self.machine.readiness,
                "assumptions": self.machine.assumptions,
            },
        }

    @classmethod
    def from_legacy_turn(
        cls,
        turn: dict[str, Any],
        *,
        readiness: dict[str, Any] | None = None,
        assumptions: list[dict[str, Any]] | None = None,
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
        )
        trace_metadata = HarnessTraceMetadata(
            terminal_reason=terminal_reason,
            trace=trace,
            validation_gates=list(trace.get("validation_gates") or []),
        )
        return cls(conversation=conversation, machine=machine, trace_metadata=trace_metadata)
