from __future__ import annotations

import re
import unicodedata
from typing import Any

from app.services.design_harness.schemas import DesignAssumption, DesignHarnessFieldStatus, DesignHarnessReadiness


LANDED_PROJECT_TYPES = {"townhouse", "villa", "shophouse", "home_office"}
APARTMENT_PROJECT_TYPES = {"apartment_reno"}
UNSAFE_SCOPE_KEYWORDS = (
    "construction ready",
    "permit ready",
    "code compliant",
    "legal compliant",
    "structural verified",
    "mep verified",
    "geotech verified",
    "giay phep",
    "xin phep",
    "phap ly",
    "thi cong",
    "ket cau",
    "co dien",
    "dien nuoc",
    "dia chat",
    "quy chuan",
)


def compute_design_harness_readiness(
    *,
    brief: dict[str, Any] | None,
    clarification_state: dict[str, Any] | None = None,
    conflicts: list[dict[str, str]] | None = None,
    latest_message: str = "",
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    resolved = brief or {}
    state = clarification_state or {}
    active_conflicts = list(conflicts or state.get("conflicts") or [])
    assumptions = _build_assumptions(resolved)
    field_statuses: dict[str, DesignHarnessFieldStatus] = {}

    def add_field(
        field_path: str,
        *,
        status: str,
        value: Any = None,
        source: str | None = None,
        confidence: float = 0.0,
        required: bool = False,
        blocks_concept_input: bool = False,
        evidence: list[dict[str, Any]] | None = None,
    ) -> None:
        field_statuses[field_path] = DesignHarnessFieldStatus(
            field_path=field_path,
            status=status,
            value=value,
            source=source,
            confidence=confidence,
            required=required,
            blocks_concept_input=blocks_concept_input,
            evidence=evidence or [],
        )

    project_type = resolved.get("project_type")
    lot = resolved.get("lot") or {}
    rooms = resolved.get("rooms") or {}
    is_apartment = project_type in APARTMENT_PROJECT_TYPES
    program_intent_present = bool(
        resolved.get("occupant_count")
        or resolved.get("household_profile")
        or resolved.get("space_requests")
        or resolved.get("special_requests")
        or resolved.get("lifestyle_priorities")
    )

    _add_value_or_missing(
        add_field,
        resolved,
        "project_type",
        required=True,
        evidence_label="brief.project_type",
    )

    if project_type:
        expected_mode = "renovation" if is_apartment else "new_build"
        if resolved.get("project_mode"):
            add_field(
                "project_mode",
                status="confirmed",
                value=resolved.get("project_mode"),
                source="user",
                confidence=0.95,
                required=True,
                evidence=[_evidence("brief.project_mode", "provided")],
            )
        else:
            add_field(
                "project_mode",
                status="defaulted",
                value=expected_mode,
                source="deterministic" if is_apartment else "default",
                confidence=0.88 if is_apartment else 0.64,
                required=True,
                evidence=[_evidence("project_type", f"defaulted from {project_type}")],
            )
    else:
        add_field(
            "project_mode",
            status="missing_critical",
            required=True,
            blocks_concept_input=True,
            evidence=[_evidence("brief.project_mode", "missing")],
        )

    if is_apartment:
        _add_value_or_missing(
            add_field,
            lot,
            "area_m2",
            field_path="site.area_m2",
            required=True,
            blocks_concept_input=True,
            evidence_label="brief.lot.area_m2",
        )
        _add_value_or_missing(
            add_field,
            resolved,
            "renovation_scope",
            required=True,
            blocks_concept_input=True,
            evidence_label="brief.renovation_scope",
        )
        _add_program_fields(
            add_field,
            rooms=rooms,
            program_intent_present=program_intent_present,
        )
    else:
        _add_value_or_missing(
            add_field,
            lot,
            "width_m",
            field_path="site.width_m",
            required=True,
            blocks_concept_input=True,
            evidence_label="brief.lot.width_m",
        )
        _add_value_or_missing(
            add_field,
            lot,
            "depth_m",
            field_path="site.depth_m",
            required=True,
            blocks_concept_input=True,
            evidence_label="brief.lot.depth_m",
        )
        _add_value_or_missing(
            add_field,
            resolved,
            "floors",
            required=True,
            blocks_concept_input=True,
            evidence_label="brief.floors",
        )
        _add_program_fields(
            add_field,
            rooms=rooms,
            program_intent_present=program_intent_present,
        )

    if resolved.get("style"):
        add_field(
            "style",
            status="confirmed",
            value=resolved.get("style"),
            source="user",
            confidence=0.95,
            required=True,
            evidence=[_evidence("brief.style", "provided")],
        )
    else:
        style_assumption = _find_assumption(assumptions, "style")
        add_field(
            "style",
            status="inferred" if style_assumption and style_assumption.source != "default" else "defaulted",
            value=style_assumption.value if style_assumption else None,
            source=style_assumption.source if style_assumption else None,
            confidence=style_assumption.confidence if style_assumption else 0.0,
            required=True,
            evidence=[_evidence("design_direction", "proposed assumption")],
        )

    _add_optional_field(add_field, resolved.get("occupant_count"), "household.occupant_count")
    _add_optional_field(add_field, resolved.get("household_profile"), "household.profile")
    _add_optional_field(add_field, lot.get("orientation"), "site.orientation")
    _add_optional_field(add_field, lot.get("access"), "site.access_context")
    _add_optional_field(add_field, resolved.get("budget_vnd"), "budget.amount_vnd")
    _add_optional_field(add_field, resolved.get("timeline_months"), "schedule.timeline_months")
    _add_optional_field(add_field, resolved.get("must_not_haves"), "priorities.dislikes")

    add_field(
        "safety_scope.concept_only",
        status="defaulted",
        value=True,
        source="deterministic",
        confidence=1.0,
        required=True,
        evidence=[_evidence("harness_policy", "AI Architect intake is concept-only")],
    )

    if active_conflicts:
        for index, conflict in enumerate(active_conflicts, start=1):
            add_field(
                f"conflicts.{index}",
                status="conflicting",
                value=conflict.get("title"),
                source="user",
                confidence=1.0,
                required=True,
                blocks_concept_input=True,
                evidence=[_evidence("clarification_state.conflicts", conflict.get("detail", "conflict"))],
            )

    if _has_unsafe_scope(latest_message, resolved):
        add_field(
            "safety_scope.unsafe_request",
            status="conflicting",
            value="unsafe_scope_claim",
            source="user",
            confidence=1.0,
            required=True,
            blocks_concept_input=True,
            evidence=[_evidence("latest_user_message", "unsafe construction/permit/legal/MEP/geotech/code scope requested")],
        )

    readiness = _summarize_readiness(
        field_statuses=field_statuses,
        assumptions=assumptions,
        legacy_clarification=state,
        is_known_project_type=bool(project_type in LANDED_PROJECT_TYPES or project_type in APARTMENT_PROJECT_TYPES),
    )
    return readiness.to_dict(), [assumption.to_dict() for assumption in assumptions]


def _add_program_fields(
    add_field,
    *,
    rooms: dict[str, Any],
    program_intent_present: bool,
) -> None:
    for key in ("bedrooms", "bathrooms"):
        value = rooms.get(key)
        if value:
            add_field(
                f"program.{key}",
                status="confirmed",
                value=value,
                source="user",
                confidence=0.95,
                required=True,
                evidence=[_evidence(f"brief.rooms.{key}", "provided")],
            )
            continue
        if program_intent_present:
            add_field(
                f"program.{key}",
                status="missing_optional",
                required=True,
                blocks_concept_input=False,
                evidence=[_evidence("program_intent", "household/program intent can guide early concept assumptions")],
            )
            continue
        add_field(
            f"program.{key}",
            status="missing_critical",
            required=True,
            blocks_concept_input=True,
            evidence=[_evidence(f"brief.rooms.{key}", "missing")],
        )


def _add_value_or_missing(
    add_field,
    mapping: dict[str, Any],
    key: str,
    *,
    field_path: str | None = None,
    required: bool,
    blocks_concept_input: bool = False,
    evidence_label: str,
) -> None:
    path = field_path or key
    value = mapping.get(key)
    if value:
        add_field(
            path,
            status="confirmed",
            value=value,
            source="user",
            confidence=0.95,
            required=required,
            evidence=[_evidence(evidence_label, "provided")],
        )
        return
    add_field(
        path,
        status="missing_critical" if required else "missing_optional",
        required=required,
        blocks_concept_input=blocks_concept_input,
        evidence=[_evidence(evidence_label, "missing")],
    )


def _add_optional_field(add_field, value: Any, field_path: str) -> None:
    if value:
        add_field(
            field_path,
            status="confirmed",
            value=value,
            source="user",
            confidence=0.9,
            evidence=[_evidence(field_path, "provided")],
        )
        return
    add_field(
        field_path,
        status="missing_optional",
        confidence=0.0,
        evidence=[_evidence(field_path, "missing")],
    )


def _build_assumptions(brief: dict[str, Any]) -> list[DesignAssumption]:
    assumptions: list[DesignAssumption] = []
    project_type = brief.get("project_type")
    lot = brief.get("lot") or {}
    rooms = brief.get("rooms") or {}

    if project_type == "apartment_reno" and not brief.get("project_mode"):
        assumptions.append(
            _assumption(
                "project-mode-renovation",
                "project_mode",
                "renovation",
                "deterministic",
                0.88,
                "Vì loại dự án là cải tạo căn hộ, harness mặc định phạm vi là cải tạo.",
            )
        )
    elif project_type in LANDED_PROJECT_TYPES and not brief.get("project_mode"):
        assumptions.append(
            _assumption(
                "project-mode-new-build",
                "project_mode",
                "new_build",
                "default",
                0.62,
                "Nhà phố/biệt thự/shophouse thường bắt đầu như brief xây mới nếu khách chưa nói cải tạo.",
            )
        )

    if project_type in LANDED_PROJECT_TYPES:
        if lot.get("width_m") and lot.get("depth_m"):
            if not brief.get("floors"):
                assumptions.append(
                    _assumption(
                        "landed-floors-pattern",
                        "floors",
                        3,
                        "pattern_memory",
                        0.56,
                        "Với brief nhà ở thấp tầng chưa nêu số tầng, 3 tầng là giả định công năng ban đầu để xác nhận.",
                    )
                )
            if not rooms.get("bedrooms"):
                assumptions.append(
                    _assumption(
                        "landed-bedrooms-pattern",
                        "program.bedrooms",
                        3,
                        "pattern_memory",
                        0.52,
                        "Chưa có số phòng ngủ nên harness đề xuất 3 phòng ngủ như điểm bắt đầu để xác nhận.",
                    )
                )
            if not rooms.get("bathrooms"):
                assumptions.append(
                    _assumption(
                        "landed-bathrooms-pattern",
                        "program.bathrooms",
                        3,
                        "pattern_memory",
                        0.5,
                        "Chưa có số WC nên harness đề xuất 3 WC như giả định công năng ban đầu.",
                    )
                )

    if project_type == "apartment_reno":
        area = lot.get("area_m2") or 0
        if area and not brief.get("renovation_scope"):
            assumptions.append(
                _assumption(
                    "apartment-renovation-scope-default",
                    "renovation_scope",
                    "full",
                    "default",
                    0.54,
                    "Khách chỉ nêu diện tích căn hộ, nên harness đề xuất cải tạo toàn bộ để xác nhận phạm vi.",
                )
            )
        if area and not rooms.get("bedrooms"):
            assumptions.append(
                _assumption(
                    "apartment-bedrooms-pattern",
                    "program.bedrooms",
                    2 if float(area) < 95 else 3,
                    "pattern_memory",
                    0.5,
                    "Số phòng ngủ được đề xuất theo diện tích căn hộ và cần chủ nhà xác nhận.",
                )
            )
        if area and not rooms.get("bathrooms"):
            assumptions.append(
                _assumption(
                    "apartment-bathrooms-pattern",
                    "program.bathrooms",
                    2,
                    "pattern_memory",
                    0.48,
                    "Số WC được đề xuất như giả định ban đầu cho căn hộ diện tích trung bình.",
                )
            )

    if not brief.get("style"):
        style_value, source, confidence, explanation = _infer_style_assumption(brief)
        assumptions.append(_assumption("style-direction", "style", style_value, source, confidence, explanation))

    return assumptions


def _infer_style_assumption(brief: dict[str, Any]) -> tuple[str, str, float, str]:
    text = _normalize_text(
        " ".join(
            str(item)
            for item in [
                *(brief.get("design_goals") or []),
                *(brief.get("lifestyle_priorities") or []),
                brief.get("material_direction") or "",
                brief.get("color_direction") or "",
                " ".join(brief.get("must_haves") or []),
            ]
        )
    )
    if any(token in text for token in ("xanh", "tu nhien", "daylight", "ventilation", "anh sang", "thong gio")):
        return (
            "tropical_modern",
            "style_profile",
            0.58,
            "Từ khóa về xanh, tự nhiên, ánh sáng hoặc thông gió gợi ý hướng nhiệt đới hiện đại cần xác nhận.",
        )
    if any(token in text for token in ("am ap", "trung tinh", "go", "warm")):
        return (
            "minimal_warm",
            "style_profile",
            0.56,
            "Từ khóa về cảm giác ấm hoặc vật liệu gỗ gợi ý hướng tối giản ấm cần xác nhận.",
        )
    return (
        "minimal_warm",
        "default",
        0.42,
        "Chưa có gu thẩm mỹ rõ, nên harness đề xuất tối giản ấm như mặc định dễ tiếp tục trao đổi.",
    )


def _summarize_readiness(
    *,
    field_statuses: dict[str, DesignHarnessFieldStatus],
    assumptions: list[DesignAssumption],
    legacy_clarification: dict[str, Any],
    is_known_project_type: bool,
) -> DesignHarnessReadiness:
    fields = {path: field_status.to_dict() for path, field_status in field_statuses.items()}
    critical_missing = sorted(
        path
        for path, field_status in field_statuses.items()
        if field_status.status == "missing_critical" and field_status.blocks_concept_input
    )
    optional_missing = sorted(path for path, field_status in field_statuses.items() if field_status.status == "missing_optional")
    confirmed_fields = sorted(path for path, field_status in field_statuses.items() if field_status.status == "confirmed")
    inferred_fields = sorted(path for path, field_status in field_statuses.items() if field_status.status == "inferred")
    defaulted_fields = sorted(path for path, field_status in field_statuses.items() if field_status.status == "defaulted")
    conflicting_fields = sorted(path for path, field_status in field_statuses.items() if field_status.status == "conflicting")
    assumptions_requiring_confirmation = sorted(
        assumption.field_path for assumption in assumptions if assumption.needs_confirmation and assumption.status == "proposed"
    )

    if "safety_scope.unsafe_request" in conflicting_fields:
        status = "blocked_by_safety_scope"
    elif conflicting_fields:
        status = "conflicting"
    elif critical_missing or not is_known_project_type:
        status = "missing_critical"
    elif assumptions_requiring_confirmation:
        status = "partial_with_assumptions"
    else:
        status = "ready_for_concept_input"

    safe_to_emit = status == "ready_for_concept_input"
    if status == "blocked_by_safety_scope":
        confidence = 0.0
    else:
        required = [field_status for field_status in field_statuses.values() if field_status.required]
        ready = [
            field_status
            for field_status in required
            if (
                field_status.status in {"confirmed", "inferred", "defaulted"}
                and not field_status.blocks_concept_input
            )
            or field_status.status == "confirmed"
        ]
        confidence = len(ready) / len(required) if required else 0.0

    return DesignHarnessReadiness(
        schema_version="design_harness_readiness_v1",
        status=status,
        confidence=confidence,
        safe_to_emit_concept_input=safe_to_emit,
        critical_missing=critical_missing,
        optional_missing=optional_missing,
        confirmed_fields=confirmed_fields,
        inferred_fields=inferred_fields,
        defaulted_fields=defaulted_fields,
        conflicting_fields=conflicting_fields,
        assumptions_requiring_confirmation=assumptions_requiring_confirmation,
        field_statuses=fields,
        legacy_clarification={
            "readiness_label": legacy_clarification.get("readiness_label"),
            "blocking_missing": list(legacy_clarification.get("blocking_missing") or []),
            "advisory_missing": list(legacy_clarification.get("advisory_missing") or []),
        },
    )


def _assumption(
    assumption_id: str,
    field_path: str,
    value: Any,
    source: str,
    confidence: float,
    explanation: str,
) -> DesignAssumption:
    return DesignAssumption(
        id=assumption_id,
        field_path=field_path,
        value=value,
        source=source,
        confidence=confidence,
        needs_confirmation=True,
        explanation=explanation,
        status="proposed",
    )


def _find_assumption(assumptions: list[DesignAssumption], field_path: str) -> DesignAssumption | None:
    for assumption in assumptions:
        if assumption.field_path == field_path:
            return assumption
    return None


def _has_unsafe_scope(latest_message: str, brief: dict[str, Any]) -> bool:
    text = _normalize_text(
        " ".join(
            [
                latest_message or "",
                " ".join(str(item) for item in brief.get("notes") or []),
            ]
        )
    )
    return any(keyword in text for keyword in UNSAFE_SCOPE_KEYWORDS)


def _normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFD", value.lower())
    return "".join(character for character in normalized if unicodedata.category(character) != "Mn")


def _evidence(source: str, detail: str) -> dict[str, Any]:
    return {"source": source, "detail": re.sub(r"\s+", " ", str(detail)).strip()[:220]}
