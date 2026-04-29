from __future__ import annotations

from dataclasses import dataclass, replace
from uuid import uuid4

from app.services.design_intelligence.concept_model import ArchitecturalConceptModel, ConceptRoom
from app.services.design_intelligence.layout_generator import validate_layout
from app.services.design_intelligence.provenance import DecisionValue
from app.services.design_intelligence.revision_interpreter import RevisionOperation
from app.services.professional_deliverables.style_knowledge import normalize_signal


PROTECTED_RESIZE_ROOM_TYPES = {"stair_lightwell", "wc", "garage", "business"}


@dataclass(frozen=True)
class ConceptRevisionResult:
    parent_version_id: str
    child_version_id: str
    parent_model: ArchitecturalConceptModel
    child_model: ArchitecturalConceptModel
    operations: tuple[RevisionOperation, ...]
    changelog: tuple[str, ...]
    preserved_parent_evidence: dict


def apply_revision_operations(
    concept_model: ArchitecturalConceptModel,
    operations: tuple[RevisionOperation, ...],
    *,
    parent_version_id: str,
) -> ConceptRevisionResult:
    rooms = list(concept_model.rooms)
    changelog: list[str] = []
    assumptions = list(concept_model.assumptions)
    metadata = dict(concept_model.metadata)
    metadata["parent_version_id"] = parent_version_id
    metadata["revision_operations"] = [_operation_dict(operation) for operation in operations]
    metadata["preserved_requirements"] = _preserved_requirements(concept_model)

    for operation in operations:
        if operation.type in {"resize_room", "resize_room_intent"} and operation.target_id:
            rooms, message = _resize_room(rooms, operation.target_id, float(operation.parameters.get("delta_m") or 0.5), operation)
            changelog.append(message)
        elif operation.type in {"switch_kitchen_open_closed", "adjust_room_priority"}:
            _append_metadata(metadata, "room_priority_adjustments", _operation_dict(operation))
            if "open_kitchen" in operation.parameters:
                metadata["kitchen_open"] = bool(operation.parameters.get("open_kitchen"))
            elif "open" in operation.parameters:
                metadata["kitchen_open"] = bool(operation.parameters.get("open"))
            changelog.append(operation.customer_visible_explanation)
        elif operation.type == "move_room_preference":
            _append_metadata(metadata, "room_move_preferences", _operation_dict(operation))
            changelog.append(operation.customer_visible_explanation)
        elif operation.type == "add_or_strengthen_style_feature":
            _append_metadata(metadata, "style_feature_adjustments", _operation_dict(operation))
            feature = operation.parameters.get("feature")
            if feature in {"greenery", "more_greenery"}:
                metadata["greenery_adjustment"] = operation.parameters.get("level", "more")
            if feature == "lightwell":
                metadata["lightwell_adjustment"] = operation.parameters.get("level", "more_visible")
            changelog.append(operation.customer_visible_explanation)
        elif operation.type == "suppress_style_feature":
            _append_metadata(metadata, "suppressed_style_features", _operation_dict(operation))
            if operation.parameters.get("feature") == "glass":
                metadata["facade_glass_policy"] = "reduce_large_unshaded_glass"
            changelog.append(operation.customer_visible_explanation)
        elif operation.type == "add_assumption":
            assumptions.append(_revision_assumption(operation))
            _append_metadata(metadata, "revision_assumptions", _operation_dict(operation))
            changelog.append(operation.customer_visible_explanation)
        elif operation.type == "ask_clarifying_question":
            _append_metadata(metadata, "revision_clarifications", _operation_dict(operation))
            blockers = operation.parameters.get("blocked_scopes")
            if blockers:
                metadata["revision_blockers"] = tuple(blockers)
            changelog.append(operation.customer_visible_explanation)
        elif operation.type == "preserve_existing_requirement":
            metadata["preserved_requirements"] = _preserved_requirements(concept_model)
        elif operation.type == "adjust_greenery":
            metadata["greenery_adjustment"] = operation.parameters.get("level", "more")
            changelog.append(operation.customer_visible_explanation)
        elif operation.type == "change_facade_emphasis":
            metadata["facade_feedback"] = operation.parameters.get("feedback")
            changelog.append(operation.customer_visible_explanation)
        elif operation.type == "update_style_parameter":
            metadata["style_feedback"] = operation.parameters.get("feedback")
            changelog.append(operation.customer_visible_explanation)
        elif operation.type == "add_bedroom":
            metadata["pending_program_change"] = "add_bedroom"
            changelog.append("Ghi nhận yêu cầu thêm phòng ngủ; cần cân lại mặt bằng ở lần tạo layout tiếp theo.")

    child_version_id = f"concept-{uuid4().hex[:12]}"
    metadata["child_version_id"] = child_version_id
    metadata["customer_changelog"] = changelog
    child = replace(concept_model, rooms=tuple(rooms), assumptions=tuple(assumptions), metadata=metadata)
    validate_layout(child)
    return ConceptRevisionResult(
        parent_version_id=parent_version_id,
        child_version_id=child_version_id,
        parent_model=concept_model,
        child_model=child,
        operations=operations,
        changelog=tuple(changelog),
        preserved_parent_evidence=_preserved_requirements(concept_model),
    )


def _resize_room(
    rooms: list[ConceptRoom],
    target_id: str,
    delta_m: float,
    operation: RevisionOperation,
) -> tuple[list[ConceptRoom], str]:
    target_index = next((index for index, room in enumerate(rooms) if room.id == target_id), None)
    if target_index is None:
        return rooms, "Không tìm thấy phòng cần nới; giữ nguyên mặt bằng concept."
    target = rooms[target_index]
    same_level = sorted(
        [(index, room) for index, room in enumerate(rooms) if room.level_id == target.level_id],
        key=lambda item: _bounds(item[1].polygon.value)[1],
    )
    position = next(index for index, item in enumerate(same_level) if item[1].id == target_id)
    t_min_x, t_min_y, t_max_x, t_max_y = _bounds(target.polygon.value)

    if position < len(same_level) - 1:
        next_index, next_room = same_level[position + 1]
        if next_room.room_type not in PROTECTED_RESIZE_ROOM_TYPES:
            n_min_x, n_min_y, n_max_x, n_max_y = _bounds(next_room.polygon.value)
            safe_delta = min(delta_m, max(0.0, (n_max_y - n_min_y) - 1.2))
            if safe_delta <= 0:
                return rooms, "Phòng kế tiếp không còn đủ chiều sâu để nới tự động."

            target_polygon = ((t_min_x, t_min_y), (t_max_x, t_min_y), (t_max_x, t_max_y + safe_delta), (t_min_x, t_max_y + safe_delta))
            next_polygon = ((n_min_x, n_min_y + safe_delta), (n_max_x, n_min_y + safe_delta), (n_max_x, n_max_y), (n_min_x, n_max_y))
            rooms[target_index] = _replace_room_geometry(target, target_polygon, operation.customer_visible_explanation)
            rooms[next_index] = _replace_room_geometry(next_room, next_polygon, "Cân lại phòng kế tiếp để nhường diện tích trong concept.")
            return rooms, operation.customer_visible_explanation

    if position > 0:
        previous_index, previous_room = same_level[position - 1]
        if previous_room.room_type not in PROTECTED_RESIZE_ROOM_TYPES:
            p_min_x, p_min_y, p_max_x, p_max_y = _bounds(previous_room.polygon.value)
            safe_delta = min(delta_m, max(0.0, (p_max_y - p_min_y) - 1.6))
            if safe_delta <= 0:
                return rooms, "Phòng liền trước không còn đủ chiều sâu để nới tự động."
            target_polygon = ((t_min_x, t_min_y - safe_delta), (t_max_x, t_min_y - safe_delta), (t_max_x, t_max_y), (t_min_x, t_max_y))
            previous_polygon = ((p_min_x, p_min_y), (p_max_x, p_min_y), (p_max_x, p_max_y - safe_delta), (p_min_x, p_max_y - safe_delta))
            rooms[target_index] = _replace_room_geometry(target, target_polygon, operation.customer_visible_explanation)
            rooms[previous_index] = _replace_room_geometry(previous_room, previous_polygon, "Cân lại phòng liền trước để giữ nguyên lõi thang/WC.")
            return rooms, operation.customer_visible_explanation

    return rooms, "Phòng đang kẹp bởi lõi/garage/khu kinh doanh nên chưa nới tự động để tránh phá vỡ concept."


def _replace_room_geometry(room: ConceptRoom, polygon: tuple[tuple[float, float], ...], explanation: str) -> ConceptRoom:
    area = round((_bounds(polygon)[2] - _bounds(polygon)[0]) * (_bounds(polygon)[3] - _bounds(polygon)[1]), 2)
    return replace(
        room,
        polygon=DecisionValue(
            value=polygon,
            source="reviewer_override",
            confidence=0.8,
            assumption=True,
            customer_visible_explanation=explanation,
            needs_confirmation=False,
        ),
        area_m2=DecisionValue(
            value=area,
            source="reviewer_override",
            confidence=0.8,
            assumption=True,
            customer_visible_explanation=f"Diện tích {room.label_vi} cập nhật theo phản hồi.",
            needs_confirmation=False,
        ),
    )


def _bounds(points: tuple[tuple[float, float], ...]) -> tuple[float, float, float, float]:
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return min(xs), min(ys), max(xs), max(ys)


def _operation_dict(operation: RevisionOperation) -> dict:
    if hasattr(operation, "as_dict"):
        return operation.as_dict()
    return operation.__dict__


def _append_metadata(metadata: dict, key: str, value: dict) -> None:
    current = list(metadata.get(key) or [])
    current.append(value)
    metadata[key] = current


def _revision_assumption(operation: RevisionOperation) -> DecisionValue:
    return DecisionValue(
        value=operation.parameters,
        source="ai_proposal",
        confidence=operation.confidence,
        assumption=True,
        customer_visible_explanation=operation.customer_visible_explanation,
        needs_confirmation=operation.requires_confirmation,
    )


def _preserved_requirements(concept_model: ArchitecturalConceptModel) -> dict:
    return {
        "source_brief": concept_model.source_brief,
        "concept_status_note": concept_model.concept_status_note,
        "project_type": _project_type(concept_model),
        "lot_dimensions": {
            "width_m": concept_model.site.width_m.as_dict(),
            "depth_m": concept_model.site.depth_m.as_dict(),
            "area_m2": concept_model.site.area_m2.as_dict(),
        },
        "family_lifestyle": dict(concept_model.metadata.get("family_lifestyle") or {}),
        "room_program_hints": dict(concept_model.metadata.get("room_program_hints") or {}),
        "required_rooms": [
            {
                "id": room.id,
                "level_id": room.level_id,
                "room_type": room.room_type,
                "label_vi": room.label_vi,
                "priority": room.priority.as_dict(),
            }
            for room in concept_model.rooms
        ],
        "style": concept_model.style.as_dict() if concept_model.style else None,
        "selected_or_inferred_style": concept_model.style.value if concept_model.style else None,
        "assumptions": [assumption.as_dict() for assumption in concept_model.assumptions],
    }


def _project_type(concept_model: ArchitecturalConceptModel) -> str | None:
    metadata_type = concept_model.metadata.get("project_type")
    if metadata_type:
        return str(metadata_type)
    brief = normalize_signal(concept_model.source_brief)
    if any(keyword in brief for keyword in ("can ho", "chung cu", "apartment", "flat", "studio")):
        return "apartment_renovation"
    if any(keyword in brief for keyword in ("nha pho", "nha ong", "townhouse")):
        return "townhouse"
    if any(keyword in brief for keyword in ("biet thu", "villa")):
        return "villa"
    return "townhouse" if float(concept_model.site.width_m.value) <= 8.0 else "villa"
