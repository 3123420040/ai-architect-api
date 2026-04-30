from __future__ import annotations

import re
import unicodedata
import uuid
from datetime import datetime, timezone
from typing import Any

from app.services.design_harness.readiness import APARTMENT_PROJECT_TYPES, LANDED_PROJECT_TYPES
from app.services.design_harness.schemas import ConceptDesignInputV1, ConceptInputCompilationResult, FieldProvenance


CONCEPT_INPUT_SCHEMA_VERSION = "concept_design_input_v1"
ALLOWED_READINESS_STATUSES = {"ready_for_concept_input", "partial_with_assumptions"}
UNSAFE_SCOPE_TERMS = (
    "construction ready",
    "permit ready",
    "code compliant",
    "legal compliant",
    "structural verified",
    "mep verified",
    "geotech verified",
    "ready for construction",
    "ready for permit",
    "thi cong",
    "xin phep",
    "giay phep",
    "phap ly",
    "ket cau",
    "co dien",
    "dien nuoc",
    "dia chat",
    "quy chuan",
)


def compile_concept_design_input(
    *,
    project_id: str,
    project_name: str | None,
    brief: dict[str, Any] | None,
    readiness: dict[str, Any] | None,
    assumptions: list[dict[str, Any]] | None,
    style_tools: dict[str, Any] | None,
) -> ConceptInputCompilationResult:
    resolved_brief = brief or {}
    resolved_readiness = readiness or {}
    resolved_assumptions = list(assumptions or [])
    resolved_style_tools = style_tools or {}

    preflight_reasons = _preflight_reasons(resolved_readiness, resolved_brief)
    if preflight_reasons:
        return ConceptInputCompilationResult(
            concept_design_input=None,
            validation=_validation("blocked", preflight_reasons, readiness=resolved_readiness),
        )

    payload = ConceptDesignInputV1(
        project=_project_payload(project_id, project_name, resolved_brief, resolved_assumptions),
        site=_site_payload(resolved_brief),
        program=_program_payload(resolved_brief, resolved_assumptions),
        household=_household_payload(resolved_brief),
        style=_style_payload(resolved_brief, resolved_assumptions, resolved_style_tools),
        layout_intent=_layout_intent_payload(resolved_brief, resolved_style_tools),
        assumptions=_assumptions_payload(resolved_assumptions, resolved_readiness),
        provenance=_provenance_payload(resolved_readiness, resolved_assumptions, resolved_style_tools),
    ).to_dict()
    validation = validate_concept_design_input(payload, readiness=resolved_readiness)
    if validation["status"] != "valid":
        return ConceptInputCompilationResult(concept_design_input=None, validation=validation)
    return ConceptInputCompilationResult(concept_design_input=payload, validation=validation)


def build_concept_input_snapshot(payload: dict[str, Any], validation: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(uuid.uuid4()),
        "schema_version": CONCEPT_INPUT_SCHEMA_VERSION,
        "payload": payload,
        "validation": validation,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "storage": "chat_message_harness_metadata",
    }


def validate_concept_design_input(payload: dict[str, Any], *, readiness: dict[str, Any] | None = None) -> dict[str, Any]:
    reasons: list[dict[str, Any]] = []
    resolved_readiness = readiness or {}

    if payload.get("schema_version") != CONCEPT_INPUT_SCHEMA_VERSION:
        reasons.append(_reason("invalid_schema_version", "schema_version", "Expected concept_design_input_v1."))

    project = _mapping(payload.get("project"))
    site = _mapping(payload.get("site"))
    program = _mapping(payload.get("program"))
    style = _mapping(payload.get("style"))
    provenance = payload.get("provenance") if isinstance(payload.get("provenance"), list) else []

    if project.get("concept_only") is not True:
        reasons.append(_reason("concept_only_required", "project.concept_only", "Concept input must be concept-only."))
    if project.get("construction_ready") is not False:
        reasons.append(_reason("construction_ready_forbidden", "project.construction_ready", "Construction-ready claims are forbidden."))

    project_type = project.get("project_type")
    required_fields = _required_fields(project_type)
    for field_path in required_fields:
        if _value_at(payload, field_path) in (None, "", [], {}):
            reasons.append(_reason("missing_required_field", field_path, f"{field_path} is required."))

    provenance_paths = {item.get("field_path") for item in provenance if isinstance(item, dict)}
    for field_path in required_fields:
        if field_path not in provenance_paths:
            reasons.append(_reason("missing_field_provenance", field_path, f"{field_path} needs provenance."))

    if project_type in LANDED_PROJECT_TYPES and (not _number(site.get("width_m")) or not _number(site.get("depth_m"))):
        reasons.append(_reason("missing_landed_site_dimensions", "site", "Landed house concept input needs width and depth."))
    if project_type in APARTMENT_PROJECT_TYPES and not _number(site.get("area_m2")):
        reasons.append(_reason("missing_apartment_area", "site.area_m2", "Apartment renovation input needs unit area."))

    if not style.get("style_id"):
        reasons.append(_reason("missing_style_intent", "style.style_id", "Style intent is required for concept handoff."))

    if resolved_readiness.get("critical_missing"):
        reasons.append(
            _reason(
                "readiness_critical_missing",
                "readiness.critical_missing",
                "Critical missing fields block concept input.",
                details={"fields": list(resolved_readiness.get("critical_missing") or [])},
            )
        )
    if resolved_readiness.get("status") in {"blocked_by_safety_scope", "conflicting"}:
        reasons.append(_reason("readiness_blocked", "readiness.status", "Readiness status blocks concept input."))

    unsafe_paths = _unsafe_claim_paths(payload)
    for field_path in unsafe_paths:
        reasons.append(_reason("unsafe_scope_claim", field_path, "Unsafe construction/permit/legal/MEP/geotech/code claim is not allowed."))

    status = "valid" if not reasons else "blocked"
    return _validation(status, reasons, readiness=resolved_readiness)


def _project_payload(
    project_id: str,
    project_name: str | None,
    brief: dict[str, Any],
    assumptions: list[dict[str, Any]],
) -> dict[str, Any]:
    project_type = brief.get("project_type")
    project_mode = brief.get("project_mode") or _assumption_value(assumptions, "project_mode")
    if not project_mode:
        project_mode = "renovation" if project_type in APARTMENT_PROJECT_TYPES else "new_build"
    return {
        "project_id": project_id,
        "project_name": project_name or brief.get("project_name") or "Untitled project",
        "project_type": project_type,
        "project_mode": project_mode,
        "concept_only": True,
        "construction_ready": False,
    }


def _site_payload(brief: dict[str, Any]) -> dict[str, Any]:
    project_type = brief.get("project_type")
    lot = _mapping(brief.get("lot"))
    width = _number(lot.get("width_m"))
    depth = _number(lot.get("depth_m"))
    area = _number(lot.get("area_m2")) or (round(width * depth, 2) if width and depth else None)
    return {
        "kind": "apartment_unit" if project_type in APARTMENT_PROJECT_TYPES else "land_lot",
        "width_m": width,
        "depth_m": depth,
        "area_m2": area,
        "orientation": lot.get("orientation") or "unknown",
        "access_context": lot.get("access") or lot.get("access_context") or "unknown",
        "source": "user" if lot else "unknown",
        "confidence": 0.95 if lot else 0.0,
    }


def _program_payload(brief: dict[str, Any], assumptions: list[dict[str, Any]]) -> dict[str, Any]:
    rooms = _mapping(brief.get("rooms"))
    space_requests = _list(brief.get("space_requests"))
    special_requests = _list(brief.get("special_requests"))
    must_haves = _list(brief.get("must_haves"))
    return {
        "floors": _number(brief.get("floors")) or _assumption_value(assumptions, "floors"),
        "bedrooms": _number(rooms.get("bedrooms")) or _assumption_value(assumptions, "program.bedrooms"),
        "bathrooms": _number(rooms.get("bathrooms") or rooms.get("wc")) or _assumption_value(assumptions, "program.bathrooms"),
        "parking": _number(rooms.get("parking")) or (1 if "garage" in special_requests else None),
        "workspaces": _number(rooms.get("workspaces")),
        "renovation_scope": brief.get("renovation_scope") or _assumption_value(assumptions, "renovation_scope"),
        "required_spaces": _dedupe([*must_haves, *special_requests]),
        "preferred_spaces": _dedupe([*space_requests, *_list(brief.get("spatial_preferences"))]),
        "must_not_haves": _list(brief.get("must_not_haves")),
    }


def _household_payload(brief: dict[str, Any]) -> dict[str, Any]:
    return {
        "occupant_count": _number(brief.get("occupant_count")),
        "profile": brief.get("household_profile"),
        "priorities": _dedupe([*_list(brief.get("lifestyle_priorities")), *_list(brief.get("design_goals"))]),
    }


def _style_payload(
    brief: dict[str, Any],
    assumptions: list[dict[str, Any]],
    style_tools: dict[str, Any],
) -> dict[str, Any]:
    selected_style_id = style_tools.get("selected_style_id")
    candidates = style_tools.get("candidates") if isinstance(style_tools.get("candidates"), list) else []
    top_candidate = candidates[0] if candidates and isinstance(candidates[0], dict) else {}
    style_id = brief.get("style") or selected_style_id or _assumption_value(assumptions, "style") or top_candidate.get("style_id")
    customer_understanding = _mapping(style_tools.get("customer_understanding"))
    profile = _mapping(style_tools.get("style_profile"))
    evidence = style_tools.get("evidence") if isinstance(style_tools.get("evidence"), list) else []
    return {
        "style_id": style_id,
        "confidence": _number(style_tools.get("confidence")) or _assumption_confidence(assumptions, "style") or 0.5,
        "evidence": evidence,
        "dislikes": _dedupe([*_list(brief.get("must_not_haves")), *_list(customer_understanding.get("dislikes"))]),
        "reference_descriptors": _list(customer_understanding.get("reference_image_descriptors")),
        "material_direction": _dedupe([brief.get("material_direction"), *_list(profile.get("material_palette"))]),
        "color_direction": _dedupe([brief.get("color_direction")]),
        "source_tags": _list(style_tools.get("source_tags")),
    }


def _layout_intent_payload(brief: dict[str, Any], style_tools: dict[str, Any]) -> dict[str, Any]:
    patterns = style_tools.get("pattern_memory") if isinstance(style_tools.get("pattern_memory"), list) else []
    pattern = patterns[0] if patterns and isinstance(patterns[0], dict) else {}
    project_type = brief.get("project_type")
    return {
        "public_private_gradient": "front_public_rear_private" if project_type not in APARTMENT_PROJECT_TYPES else "entry_public_private_rooms",
        "stair_core_strategy": pattern.get("stair_lightwell_position") or ("not_applicable" if project_type in APARTMENT_PROJECT_TYPES else "side_core_lightwell"),
        "wet_core_strategy": "stacked",
        "daylight_strategy": _dedupe([pattern.get("facade_strategy"), *_list(brief.get("spatial_preferences"))]),
        "storage_strategy": ["distributed_storage"] if "storage" in " ".join(_list(brief.get("space_requests"))).lower() else [],
        "revision_preferences": [],
        "pattern_memory": pattern,
    }


def _assumptions_payload(assumptions: list[dict[str, Any]], readiness: dict[str, Any]) -> list[dict[str, Any]]:
    requiring_confirmation = set(readiness.get("assumptions_requiring_confirmation") or [])
    payload: list[dict[str, Any]] = []
    for assumption in assumptions:
        if not isinstance(assumption, dict):
            continue
        item = {
            "id": assumption.get("id"),
            "field_path": assumption.get("field_path"),
            "value": assumption.get("value"),
            "source": assumption.get("source"),
            "confidence": assumption.get("confidence"),
            "needs_confirmation": bool(assumption.get("needs_confirmation")),
            "status": assumption.get("status", "proposed"),
            "requires_confirmation_for_handoff": assumption.get("field_path") in requiring_confirmation,
            "explanation": assumption.get("explanation"),
        }
        payload.append(item)
    return payload


def _provenance_payload(
    readiness: dict[str, Any],
    assumptions: list[dict[str, Any]],
    style_tools: dict[str, Any],
) -> list[dict[str, Any]]:
    field_statuses = _mapping(readiness.get("field_statuses"))
    provenance: list[dict[str, Any]] = [
        FieldProvenance(
            field_path="project.project_id",
            source="project_record",
            confidence=1.0,
            evidence=[{"source": "Project.id", "detail": "Existing project record identity."}],
        ).to_dict(),
        FieldProvenance(
            field_path="project.construction_ready",
            source="harness_policy",
            confidence=1.0,
            evidence=[{"source": "harness_policy", "detail": "Concept input is never construction-ready."}],
        ).to_dict(),
    ]
    for field_path, status in field_statuses.items():
        if not isinstance(status, dict):
            continue
        provenance.append(
            FieldProvenance(
                field_path=_concept_path(field_path),
                source=str(status.get("source") or status.get("status") or "unknown"),
                confidence=float(status.get("confidence") or 0.0),
                evidence=_list(status.get("evidence")),
                assumption_id=_assumption_id(assumptions, field_path),
            ).to_dict()
        )
    if style_tools:
        provenance.append(
            FieldProvenance(
                field_path="style.style_id",
                source="style_pattern_tools",
                confidence=float(style_tools.get("confidence") or 0.0),
                evidence=_list(style_tools.get("evidence")),
                assumption_id=_assumption_id(assumptions, "style"),
            ).to_dict()
        )
    return _dedupe_provenance(provenance)


def _preflight_reasons(readiness: dict[str, Any], brief: dict[str, Any]) -> list[dict[str, Any]]:
    reasons: list[dict[str, Any]] = []
    project_type = brief.get("project_type")
    if project_type not in LANDED_PROJECT_TYPES | APARTMENT_PROJECT_TYPES:
        reasons.append(_reason("unsupported_project_type", "project.project_type", "Concept input supports landed houses and apartment renovations."))
    status = readiness.get("status")
    if status not in ALLOWED_READINESS_STATUSES:
        reasons.append(_reason("readiness_status_not_allowed", "readiness.status", f"Readiness status {status or 'unknown'} does not allow concept input."))
    if readiness.get("critical_missing"):
        reasons.append(
            _reason(
                "critical_missing",
                "readiness.critical_missing",
                "Critical missing fields block concept input.",
                details={"fields": list(readiness.get("critical_missing") or [])},
            )
        )
    if readiness.get("conflicting_fields"):
        reasons.append(
            _reason(
                "conflicting_fields",
                "readiness.conflicting_fields",
                "Conflicting fields block concept input.",
                details={"fields": list(readiness.get("conflicting_fields") or [])},
            )
        )
    return reasons


def _required_fields(project_type: Any) -> tuple[str, ...]:
    base = (
        "project.project_id",
        "project.project_type",
        "project.project_mode",
        "project.concept_only",
        "project.construction_ready",
        "program.bedrooms",
        "program.bathrooms",
        "style.style_id",
    )
    if project_type in APARTMENT_PROJECT_TYPES:
        return (*base, "site.area_m2", "program.renovation_scope")
    return (*base, "site.width_m", "site.depth_m", "program.floors")


def _validation(status: str, reasons: list[dict[str, Any]], *, readiness: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "concept_input_validation_v1",
        "status": status,
        "allowed": status == "valid",
        "readiness_status": readiness.get("status"),
        "critical_missing": list(readiness.get("critical_missing") or []),
        "assumptions_requiring_confirmation": list(readiness.get("assumptions_requiring_confirmation") or []),
        "reasons": reasons,
    }


def _reason(code: str, field_path: str, message: str, *, details: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = {"code": code, "field_path": field_path, "message": message}
    if details:
        payload["details"] = details
    return payload


def _unsafe_claim_paths(value: Any, path: str = "") -> list[str]:
    if isinstance(value, dict):
        paths: list[str] = []
        for key, item in value.items():
            child_path = f"{path}.{key}" if path else str(key)
            if key == "construction_ready" and item is False:
                continue
            if key == "concept_only":
                continue
            paths.extend(_unsafe_claim_paths(item, child_path))
        return paths
    if isinstance(value, list | tuple):
        paths: list[str] = []
        for index, item in enumerate(value):
            paths.extend(_unsafe_claim_paths(item, f"{path}[{index}]"))
        return paths
    text = _normalize(str(value)) if value not in (None, "") else ""
    return [path] if text and any(term in text for term in UNSAFE_SCOPE_TERMS) else []


def _value_at(payload: dict[str, Any], field_path: str) -> Any:
    current: Any = payload
    for part in field_path.split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def _concept_path(field_path: str) -> str:
    mapping = {
        "project_type": "project.project_type",
        "project_mode": "project.project_mode",
        "site.width_m": "site.width_m",
        "site.depth_m": "site.depth_m",
        "site.area_m2": "site.area_m2",
        "floors": "program.floors",
        "program.bedrooms": "program.bedrooms",
        "program.bathrooms": "program.bathrooms",
        "renovation_scope": "program.renovation_scope",
        "style": "style.style_id",
        "safety_scope.concept_only": "project.concept_only",
    }
    return mapping.get(field_path, field_path)


def _assumption_value(assumptions: list[dict[str, Any]], field_path: str) -> Any:
    for assumption in assumptions:
        if isinstance(assumption, dict) and assumption.get("field_path") == field_path:
            return assumption.get("value")
    return None


def _assumption_confidence(assumptions: list[dict[str, Any]], field_path: str) -> float | None:
    for assumption in assumptions:
        if isinstance(assumption, dict) and assumption.get("field_path") == field_path:
            return _number(assumption.get("confidence"))
    return None


def _assumption_id(assumptions: list[dict[str, Any]], field_path: str) -> str | None:
    for assumption in assumptions:
        if isinstance(assumption, dict) and assumption.get("field_path") == field_path:
            return str(assumption.get("id"))
    return None


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def _number(value: Any) -> int | float | None:
    if isinstance(value, bool) or value in (None, ""):
        return None
    if isinstance(value, int | float):
        return value
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return int(parsed) if parsed.is_integer() else parsed


def _dedupe(values: list[Any]) -> list[Any]:
    result: list[Any] = []
    seen: set[str] = set()
    for value in values:
        if value in (None, "", [], {}):
            continue
        key = str(value)
        if key in seen:
            continue
        seen.add(key)
        result.append(value)
    return result


def _dedupe_provenance(values: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for value in values:
        field_path = str(value.get("field_path"))
        if field_path in seen:
            continue
        seen.add(field_path)
        result.append(value)
    return result


def _normalize(value: str) -> str:
    normalized = unicodedata.normalize("NFD", value.lower()).replace("đ", "d")
    text = "".join(character for character in normalized if unicodedata.category(character) != "Mn")
    return re.sub(r"\s+", " ", text)
