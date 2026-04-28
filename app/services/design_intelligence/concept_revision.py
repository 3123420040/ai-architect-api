from __future__ import annotations

from dataclasses import dataclass, replace
from uuid import uuid4

from app.services.design_intelligence.concept_model import ArchitecturalConceptModel, ConceptRoom
from app.services.design_intelligence.layout_generator import validate_layout
from app.services.design_intelligence.provenance import DecisionValue
from app.services.design_intelligence.revision_interpreter import RevisionOperation


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
    metadata = dict(concept_model.metadata)
    metadata["parent_version_id"] = parent_version_id
    metadata["revision_operations"] = [operation.__dict__ for operation in operations]

    for operation in operations:
        if operation.type == "resize_room" and operation.target_id:
            rooms, message = _resize_room(rooms, operation.target_id, float(operation.parameters.get("delta_m") or 0.5), operation)
            changelog.append(message)
        elif operation.type == "switch_kitchen_open_closed":
            metadata["kitchen_open"] = bool(operation.parameters.get("open"))
            changelog.append(operation.customer_visible_explanation)
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
    child = replace(concept_model, rooms=tuple(rooms), metadata=metadata)
    validate_layout(child)
    return ConceptRevisionResult(
        parent_version_id=parent_version_id,
        child_version_id=child_version_id,
        parent_model=concept_model,
        child_model=child,
        operations=operations,
        changelog=tuple(changelog),
        preserved_parent_evidence={
            "source_brief": concept_model.source_brief,
            "assumptions": [assumption.as_dict() for assumption in concept_model.assumptions],
            "style": concept_model.style.as_dict() if concept_model.style else None,
        },
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
    if position >= len(same_level) - 1:
        return rooms, "Phòng đang ở cuối chuỗi nên chưa nới tự động để tránh vượt ranh đất."
    next_index, next_room = same_level[position + 1]
    t_min_x, t_min_y, t_max_x, t_max_y = _bounds(target.polygon.value)
    n_min_x, n_min_y, n_max_x, n_max_y = _bounds(next_room.polygon.value)
    safe_delta = min(delta_m, max(0.0, (n_max_y - n_min_y) - 1.2))
    if safe_delta <= 0:
        return rooms, "Phòng kế tiếp không còn đủ chiều sâu để nới tự động."

    target_polygon = ((t_min_x, t_min_y), (t_max_x, t_min_y), (t_max_x, t_max_y + safe_delta), (t_min_x, t_max_y + safe_delta))
    next_polygon = ((n_min_x, n_min_y + safe_delta), (n_max_x, n_min_y + safe_delta), (n_max_x, n_max_y), (n_min_x, n_max_y))
    rooms[target_index] = _replace_room_geometry(target, target_polygon, operation.customer_visible_explanation)
    rooms[next_index] = _replace_room_geometry(next_room, next_polygon, "Cân lại phòng kế tiếp để nhường diện tích trong concept.")
    return rooms, operation.customer_visible_explanation


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
