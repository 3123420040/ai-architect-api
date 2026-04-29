from __future__ import annotations

from dataclasses import dataclass, replace
from uuid import uuid4

from app.services.design_intelligence.concept_model import ArchitecturalConceptModel, ConceptFacade, ConceptFixture, ConceptRoom
from app.services.design_intelligence.layout_generator import validate_layout
from app.services.design_intelligence.provenance import DecisionValue
from app.services.design_intelligence.revision_interpreter import RevisionOperation
from app.services.professional_deliverables.style_knowledge import StyleKnowledgeBase, StyleKnowledgeError, normalize_signal


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
    fixtures = list(concept_model.fixtures)
    style = concept_model.style
    facade = concept_model.facade
    changelog: list[str] = []
    changed_fields: list[str] = []
    assumptions = list(concept_model.assumptions)
    metadata = dict(concept_model.metadata)
    metadata["parent_version_id"] = parent_version_id
    metadata["revision_operations"] = [_operation_dict(operation) for operation in operations]
    metadata["preserved_requirements"] = _preserved_requirements(concept_model)

    for operation in operations:
        if operation.type in {"resize_room", "resize_room_intent"} and operation.target_id:
            rooms, fixtures, message = _resize_room(
                rooms,
                fixtures,
                operation.target_id,
                float(operation.parameters.get("delta_m") or 0.5),
                operation,
                site_depth=float(concept_model.site.depth_m.value),
            )
            changelog.append(message)
            changed_fields.append(f"rooms.{operation.target_id}.area_m2")
        elif operation.type in {"switch_kitchen_open_closed", "adjust_room_priority"}:
            _append_metadata(metadata, "room_priority_adjustments", _operation_dict(operation))
            if "open_kitchen" in operation.parameters:
                metadata["kitchen_open"] = bool(operation.parameters.get("open_kitchen"))
                changed_fields.append("room_priorities.kitchen_open")
            elif "open" in operation.parameters:
                metadata["kitchen_open"] = bool(operation.parameters.get("open"))
                changed_fields.append("room_priorities.kitchen_open")
            changelog.append(operation.customer_visible_explanation)
        elif operation.type == "move_room_preference":
            _append_metadata(metadata, "room_move_preferences", _operation_dict(operation))
            changed_fields.append("room_priorities.move_preferences")
            changelog.append(operation.customer_visible_explanation)
        elif operation.type == "add_storage_preference":
            rooms, fixtures, message, storage_changed_fields = _add_storage_preference(rooms, fixtures, operation)
            _append_metadata(metadata, "room_priority_adjustments", _operation_dict(operation))
            changelog.append(message)
            changed_fields.extend(storage_changed_fields)
            assumptions.append(_revision_assumption(operation))
        elif operation.type == "change_style_direction":
            style, facade, metadata = _apply_style_direction_change(style, facade, metadata, operation)
            assumptions.append(_revision_assumption(operation))
            changelog.append(operation.customer_visible_explanation)
            changed_fields.extend(("style.selected_style_id", "style.facade_expression", "style.material_notes"))
        elif operation.type == "add_or_strengthen_style_feature":
            _append_metadata(metadata, "style_feature_adjustments", _operation_dict(operation))
            metadata = _apply_style_feature_metadata(metadata, operation)
            feature = operation.parameters.get("feature")
            if feature in {"greenery", "more_greenery"}:
                metadata["greenery_adjustment"] = operation.parameters.get("level", "more")
                changed_fields.append("style.greenery")
            if feature == "lightwell":
                metadata["lightwell_adjustment"] = operation.parameters.get("level", "more_visible")
                changed_fields.append("layout.lightwell")
            if feature in {"warmer_palette", "arches_or_screens", "more_storage", "softer_facade", "tropical_shading", "indochine_decorative_restraint"}:
                changed_fields.append(f"style.features.{feature}")
            assumptions.append(_revision_assumption(operation))
            changelog.append(operation.customer_visible_explanation)
        elif operation.type == "suppress_style_feature":
            _append_metadata(metadata, "suppressed_style_features", _operation_dict(operation))
            metadata = _apply_style_feature_metadata(metadata, operation)
            if operation.parameters.get("feature") == "glass":
                metadata["facade_glass_policy"] = "reduce_large_unshaded_glass"
                changed_fields.append("style.suppressed_features.glass")
            assumptions.append(_revision_assumption(operation))
            changelog.append(operation.customer_visible_explanation)
        elif operation.type == "add_assumption":
            assumptions.append(_revision_assumption(operation))
            _append_metadata(metadata, "revision_assumptions", _operation_dict(operation))
            changelog.append(operation.customer_visible_explanation)
            changed_fields.append("assumptions")
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
            changed_fields.append("style.greenery")
        elif operation.type == "change_facade_emphasis":
            metadata["facade_feedback"] = operation.parameters.get("feedback")
            changelog.append(operation.customer_visible_explanation)
            changed_fields.append("style.facade_expression")
        elif operation.type == "update_style_parameter":
            metadata["style_feedback"] = operation.parameters.get("feedback")
            changelog.append(operation.customer_visible_explanation)
            changed_fields.append("style.parameters")
        elif operation.type == "add_bedroom":
            metadata["pending_program_change"] = "add_bedroom"
            changelog.append("Ghi nhận yêu cầu thêm phòng ngủ; cần cân lại mặt bằng ở lần tạo layout tiếp theo.")
            changed_fields.append("room_program.pending_bedroom_count")

    child_version_id = f"concept-{uuid4().hex[:12]}"
    metadata["child_version_id"] = child_version_id
    metadata["customer_changelog"] = changelog
    metadata["revision_summary"] = _revision_summary(
        parent_version_id=parent_version_id,
        child_version_id=child_version_id,
        concept_model=concept_model,
        operations=operations,
        changelog=tuple(changelog),
        changed_fields=tuple(dict.fromkeys(changed_fields)),
    )
    metadata["regeneration_metadata"] = {
        "source": "concept_revision",
        "parent_version_id": parent_version_id,
        "child_version_id": child_version_id,
        "preserved_original_requirements": True,
        "construction_ready": False,
    }
    child = replace(
        concept_model,
        rooms=tuple(rooms),
        fixtures=tuple(fixtures),
        style=style,
        facade=facade,
        assumptions=_dedupe_decisions(assumptions),
        metadata=metadata,
    )
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
    fixtures: list[ConceptFixture],
    target_id: str,
    delta_m: float,
    operation: RevisionOperation,
    *,
    site_depth: float,
) -> tuple[list[ConceptRoom], list[ConceptFixture], str]:
    target_index = next((index for index, room in enumerate(rooms) if room.id == target_id), None)
    if target_index is None:
        return rooms, fixtures, "Không tìm thấy phòng cần nới; giữ nguyên mặt bằng concept."
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
                return rooms, fixtures, "Phòng kế tiếp không còn đủ chiều sâu để nới tự động."

            target_polygon = ((t_min_x, t_min_y), (t_max_x, t_min_y), (t_max_x, t_max_y + safe_delta), (t_min_x, t_max_y + safe_delta))
            next_polygon = ((n_min_x, n_min_y + safe_delta), (n_max_x, n_min_y + safe_delta), (n_max_x, n_max_y), (n_min_x, n_max_y))
            rooms[target_index] = _replace_room_geometry(target, target_polygon, operation.customer_visible_explanation)
            rooms[next_index] = _replace_room_geometry(next_room, next_polygon, "Cân lại phòng kế tiếp để nhường diện tích trong concept.")
            fixtures = _shift_room_fixtures(fixtures, next_room.id, dy=safe_delta)
            return rooms, fixtures, operation.customer_visible_explanation

    if position > 0:
        previous_index, previous_room = same_level[position - 1]
        if previous_room.room_type not in PROTECTED_RESIZE_ROOM_TYPES:
            p_min_x, p_min_y, p_max_x, p_max_y = _bounds(previous_room.polygon.value)
            safe_delta = min(delta_m, max(0.0, (p_max_y - p_min_y) - 1.6))
            if safe_delta <= 0:
                return rooms, fixtures, "Phòng liền trước không còn đủ chiều sâu để nới tự động."
            target_polygon = ((t_min_x, t_min_y - safe_delta), (t_max_x, t_min_y - safe_delta), (t_max_x, t_max_y), (t_min_x, t_max_y))
            previous_polygon = ((p_min_x, p_min_y), (p_max_x, p_min_y), (p_max_x, p_max_y - safe_delta), (p_min_x, p_max_y - safe_delta))
            rooms[target_index] = _replace_room_geometry(target, target_polygon, operation.customer_visible_explanation)
            rooms[previous_index] = _replace_room_geometry(previous_room, previous_polygon, "Cân lại phòng liền trước để giữ nguyên lõi thang/WC.")
            return rooms, fixtures, operation.customer_visible_explanation

    if operation.parameters.get("allow_service_zone_shift"):
        shifted = _expand_room_by_shifting_following_rooms(
            rooms,
            fixtures,
            target_index=target_index,
            same_level=same_level,
            position=position,
            delta_m=delta_m,
            site_depth=site_depth,
            operation=operation,
        )
        if shifted is not None:
            return shifted

    return rooms, fixtures, "Phòng đang kẹp bởi lõi/garage/khu kinh doanh nên chưa nới tự động để tránh phá vỡ concept."


def _expand_room_by_shifting_following_rooms(
    rooms: list[ConceptRoom],
    fixtures: list[ConceptFixture],
    *,
    target_index: int,
    same_level: list[tuple[int, ConceptRoom]],
    position: int,
    delta_m: float,
    site_depth: float,
    operation: RevisionOperation,
) -> tuple[list[ConceptRoom], list[ConceptFixture], str] | None:
    target = rooms[target_index]
    t_min_x, t_min_y, t_max_x, t_max_y = _bounds(target.polygon.value)
    following = [(index, room) for index, room in same_level[position + 1 :] if _bounds(room.polygon.value)[1] >= t_max_y - 0.001]
    max_room_y = max((_bounds(room.polygon.value)[3] for _, room in following), default=t_max_y)
    available_depth = max(0.0, site_depth - 0.3 - max_room_y)
    safe_delta = min(delta_m, available_depth)
    if safe_delta <= 0.0:
        return None

    target_polygon = ((t_min_x, t_min_y), (t_max_x, t_min_y), (t_max_x, t_max_y + safe_delta), (t_min_x, t_max_y + safe_delta))
    rooms[target_index] = _replace_room_geometry(target, target_polygon, operation.customer_visible_explanation)
    for index, room in following:
        rooms[index] = _shift_room_geometry(room, dy=safe_delta, explanation="Dịch khu phụ phía sau để nhường thêm chiều sâu cho bếp/ăn concept.")
        fixtures = _shift_room_fixtures(fixtures, room.id, dy=safe_delta)
    return rooms, fixtures, operation.customer_visible_explanation


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


def _shift_room_geometry(room: ConceptRoom, *, dy: float, explanation: str) -> ConceptRoom:
    shifted = tuple((x, round(y + dy, 3)) for x, y in room.polygon.value)
    return _replace_room_geometry(room, shifted, explanation)


def _shift_room_fixtures(fixtures: list[ConceptFixture], room_id: str, *, dy: float) -> list[ConceptFixture]:
    shifted: list[ConceptFixture] = []
    for fixture in fixtures:
        if fixture.room_id != room_id:
            shifted.append(fixture)
            continue
        x, y = fixture.position.value
        shifted.append(
            replace(
                fixture,
                position=DecisionValue(
                    value=(x, round(y + dy, 3)),
                    source="reviewer_override",
                    confidence=0.8,
                    assumption=True,
                    customer_visible_explanation="Vị trí fixture dịch theo phòng sau phản hồi concept.",
                    needs_confirmation=False,
                ),
            )
        )
    return shifted


def _add_storage_preference(
    rooms: list[ConceptRoom],
    fixtures: list[ConceptFixture],
    operation: RevisionOperation,
) -> tuple[list[ConceptRoom], list[ConceptFixture], str, tuple[str, ...]]:
    changed_fields = ["room_priorities.storage"]
    rooms = list(rooms)
    fixtures = list(fixtures)
    for index, room in enumerate(rooms):
        if room.room_type == "storage" and room.level_id == "L1":
            rooms[index] = replace(
                room,
                priority=DecisionValue(
                    value="entry_storage_revision",
                    source="reviewer_override",
                    confidence=0.84,
                    assumption=True,
                    customer_visible_explanation="Kho tầng trệt được ưu tiên như mảng lưu trữ gần lối vào theo phản hồi.",
                    needs_confirmation=False,
                ),
            )
            changed_fields.append(f"rooms.{room.id}.priority")
            break

    candidate_index = _secondary_bedroom_index(rooms)
    if candidate_index is None:
        return rooms, fixtures, operation.customer_visible_explanation, tuple(dict.fromkeys(changed_fields))

    bedroom = rooms[candidate_index]
    min_x, min_y, max_x, max_y = _bounds(bedroom.polygon.value)
    bedroom_depth = max_y - min_y
    storage_depth = min(1.0, bedroom_depth - 3.0)
    if storage_depth < 0.65:
        return rooms, fixtures, operation.customer_visible_explanation, tuple(dict.fromkeys(changed_fields))

    bedroom_polygon = ((min_x, min_y), (max_x, min_y), (max_x, max_y - storage_depth), (min_x, max_y - storage_depth))
    storage_polygon = ((min_x, max_y - storage_depth), (max_x, max_y - storage_depth), (max_x, max_y), (min_x, max_y))
    rooms[candidate_index] = _replace_room_geometry(
        bedroom,
        bedroom_polygon,
        "Thu gọn phòng ngủ phụ một phần để tạo tủ/kho gần khu phòng ngủ theo phản hồi.",
    )
    storage_id = _unique_room_id(rooms, bedroom.level_id, "storage")
    storage_room = ConceptRoom(
        id=storage_id,
        level_id=bedroom.level_id,
        room_type="storage",
        label_vi="Tủ/kho phòng ngủ",
        polygon=DecisionValue(
            value=storage_polygon,
            source="reviewer_override",
            confidence=0.84,
            assumption=True,
            customer_visible_explanation="Tủ/kho phòng ngủ thêm theo phản hồi khách, là ý đồ concept cần xác nhận kích thước chi tiết.",
            needs_confirmation=False,
        ),
        area_m2=DecisionValue(
            value=round((max_x - min_x) * storage_depth, 2),
            source="reviewer_override",
            confidence=0.84,
            assumption=True,
            customer_visible_explanation="Diện tích tủ/kho phòng ngủ được tách từ phòng ngủ phụ ở mức concept.",
            needs_confirmation=False,
        ),
        priority=DecisionValue(
            value="bedroom_storage_revision",
            source="reviewer_override",
            confidence=0.84,
            assumption=True,
            customer_visible_explanation="Ưu tiên tăng lưu trữ gần phòng ngủ theo phản hồi khách.",
            needs_confirmation=False,
        ),
        adjacency=(bedroom.id,),
    )
    rooms.append(storage_room)
    fixtures.append(_storage_fixture(storage_room))
    changed_fields.extend((f"rooms.{bedroom.id}.area_m2", f"rooms.{storage_id}.created", f"fixtures.fx-{storage_id}.created"))
    return rooms, fixtures, operation.customer_visible_explanation, tuple(dict.fromkeys(changed_fields))


def _secondary_bedroom_index(rooms: list[ConceptRoom]) -> int | None:
    bedrooms = [
        (index, room)
        for index, room in enumerate(rooms)
        if room.room_type == "bedroom" and "master" not in normalize_signal(room.label_vi) and "ong ba" not in normalize_signal(room.label_vi)
    ]
    bedrooms.sort(key=lambda item: (item[1].level_id, item[1].area_m2.value))
    for index, room in bedrooms:
        min_x, min_y, max_x, max_y = _bounds(room.polygon.value)
        if (max_y - min_y) >= 3.65 and (max_x - min_x) >= 1.5:
            return index
    return None


def _unique_room_id(rooms: list[ConceptRoom], level_id: str, room_type: str) -> str:
    existing = {room.id for room in rooms}
    floor = level_id.replace("L", "")
    index = 1
    while True:
        candidate = f"f{floor}-{room_type}-revision-{index}"
        if candidate not in existing:
            return candidate
        index += 1


def _storage_fixture(room: ConceptRoom) -> ConceptFixture:
    min_x, min_y, max_x, max_y = _bounds(room.polygon.value)
    width = min(1.4, max_x - min_x - 0.2)
    depth = min(0.55, max_y - min_y - 0.1)
    return ConceptFixture(
        id=f"fx-{room.id}",
        level_id=room.level_id,
        room_id=room.id,
        fixture_type="cabinet",
        position=DecisionValue(
            value=(round(min_x + width / 2 + 0.1, 3), round(min_y + depth / 2 + 0.05, 3)),
            source="reviewer_override",
            confidence=0.82,
            assumption=True,
            customer_visible_explanation="Tủ lưu trữ thêm đặt sơ bộ trong kho phòng ngủ revision.",
            needs_confirmation=False,
        ),
        dimensions_m=DecisionValue(
            value=(round(width, 2), round(depth, 2)),
            source="reviewer_override",
            confidence=0.82,
            assumption=True,
            customer_visible_explanation="Module tủ lưu trữ revision là kích thước concept, chưa phải chi tiết sản xuất.",
            needs_confirmation=False,
        ),
        label_vi="Tủ lưu trữ",
    )


def _apply_style_direction_change(
    style: DecisionValue | None,
    facade: ConceptFacade | None,
    metadata: dict,
    operation: RevisionOperation,
) -> tuple[DecisionValue, ConceptFacade, dict]:
    target_style_id = str(operation.parameters.get("target_style_id") or "").strip()
    if not target_style_id:
        return style, facade, metadata  # type: ignore[return-value]
    previous_style_id = str(operation.parameters.get("previous_style_id") or (style.value if style else "") or "")
    style_decision = DecisionValue(
        value=target_style_id,
        source="reviewer_override",
        confidence=operation.confidence,
        assumption=True,
        customer_visible_explanation=operation.customer_visible_explanation,
        needs_confirmation=operation.requires_confirmation,
    )
    style_metadata = _style_metadata_copy(metadata)
    style_metadata["previous_style_id"] = previous_style_id or None
    style_metadata["style_id"] = target_style_id
    style_metadata["style_origin"] = "homeowner_revision"
    style_metadata["style_revision"] = {
        "previous_style_id": previous_style_id or None,
        "target_style_id": target_style_id,
        "preserve_geometry": bool(operation.parameters.get("preserve_geometry")),
        "preserve_room_program": bool(operation.parameters.get("preserve_room_program")),
        "source": operation.source,
        "explanation": operation.customer_visible_explanation,
    }
    style_metadata["drawing_notes"] = _prepend_tuple(
        style_metadata.get("drawing_notes") or style_metadata.get("style_notes") or (),
        (
            f"Revision feedback: {operation.customer_visible_explanation}",
            "Revision preserves lot geometry, floor count, and required room program unless the homeowner explicitly changes them.",
        ),
    )
    style_metadata["style_notes"] = style_metadata["drawing_notes"]
    provenance = dict(style_metadata.get("style_provenance") or {})
    provenance["revision_style_change"] = _operation_dict(operation)
    style_metadata["style_provenance"] = provenance
    facade_intent = f"Style revision target: {target_style_id}"
    try:
        profile = StyleKnowledgeBase.load_default().get(target_style_id)
    except StyleKnowledgeError:
        profile = None
    if profile is not None:
        facade_intent = profile.facade_intent
        style_metadata.update(
            {
                "style_name": profile.display_name,
                "style_display_name": profile.display_name,
                "customer_style_label": _customer_style_label(profile.style_id, profile.display_name),
                "facade_intent": profile.facade_intent,
                "facade_strategy": profile.facade_intent,
                "facade_rules": profile.facade_rules,
                "facade_expression": profile.facade_expression,
                "material_palette": profile.material_palette,
                "material_assumptions": profile.material_assumptions,
                "drawing_rules": profile.drawing_rules,
                "drawing_notes": _prepend_tuple(
                    profile.drawing_notes,
                    (
                        f"Revision feedback: {operation.customer_visible_explanation}",
                        "Revision preserves lot geometry, floor count, and required room program unless the homeowner explicitly changes them.",
                    ),
                ),
            }
        )
        style_metadata["style_notes"] = style_metadata["drawing_notes"]

    metadata = dict(metadata)
    metadata["style_metadata"] = style_metadata
    facade_strategy = DecisionValue(
        value=facade_intent,
        source="reviewer_override",
        confidence=operation.confidence,
        assumption=True,
        customer_visible_explanation="Mặt tiền concept cập nhật theo style revision của khách, không phải đặc tả vật liệu cuối cùng.",
        needs_confirmation=operation.requires_confirmation,
    )
    if facade is None:
        facade = ConceptFacade(style_id=style_decision, strategy=facade_strategy)
    else:
        facade = replace(facade, style_id=style_decision, strategy=facade_strategy)
    return style_decision, facade, metadata


def _apply_style_feature_metadata(metadata: dict, operation: RevisionOperation) -> dict:
    metadata = dict(metadata)
    style_metadata = _style_metadata_copy(metadata)
    note = f"Revision feedback: {operation.customer_visible_explanation}"
    style_metadata["drawing_notes"] = _prepend_tuple(style_metadata.get("drawing_notes") or style_metadata.get("style_notes") or (), (note,))
    style_metadata["style_notes"] = style_metadata["drawing_notes"]
    feature = operation.parameters.get("feature")
    operation_payload = {
        "feature": feature,
        "source": operation.source,
        "intent": operation.intent,
        "drawing_note": operation.customer_visible_explanation,
        "descriptor_signals": tuple(operation.parameters.get("descriptor_signals") or ()),
    }
    if operation.source == "reference_image_descriptor":
        style_metadata["reference_style_hints"] = _append_tuple(style_metadata.get("reference_style_hints") or (), operation_payload)
        style_metadata["reference_descriptor_signals"] = _prepend_tuple(
            style_metadata.get("reference_descriptor_signals") or (),
            tuple(operation.parameters.get("descriptor_signals") or ()),
        )
    elif operation.type == "suppress_style_feature":
        style_metadata["suppressed_style_features"] = _append_tuple(style_metadata.get("suppressed_style_features") or (), operation_payload)
    else:
        style_metadata["revision_style_hints"] = _append_tuple(style_metadata.get("revision_style_hints") or (), operation_payload)
    if feature == "warmer_palette":
        style_metadata["material_palette"] = _warmer_palette(style_metadata.get("material_palette"))
    provenance = dict(style_metadata.get("style_provenance") or {})
    provenance[f"revision_{operation.intent}"] = _operation_dict(operation)
    style_metadata["style_provenance"] = provenance
    metadata["style_metadata"] = style_metadata
    return metadata


def _style_metadata_copy(metadata: dict) -> dict:
    style_metadata = metadata.get("style_metadata") if isinstance(metadata, dict) else None
    return dict(style_metadata) if isinstance(style_metadata, dict) else {}


def _prepend_tuple(existing, values: tuple) -> tuple:
    if isinstance(existing, str):
        existing_values = (existing,) if existing.strip() else ()
    elif isinstance(existing, (list, tuple)):
        existing_values = tuple(existing)
    else:
        existing_values = ()
    return tuple(dict.fromkeys((*values, *existing_values)))


def _append_tuple(existing, value) -> tuple:
    if isinstance(existing, str):
        existing_values = (existing,) if existing.strip() else ()
    elif isinstance(existing, (list, tuple)):
        existing_values = tuple(existing)
    else:
        existing_values = ()
    return (*existing_values, value)


def _warmer_palette(value) -> dict:
    palette = dict(value) if isinstance(value, dict) else {}
    base = tuple(dict.fromkeys(("warm neutral", "cream wall", *tuple(palette.get("base") or ()))))
    accent = tuple(dict.fromkeys(("warm wood", "soft lighting", *tuple(palette.get("accent") or ()))))
    return {**palette, "base": base, "accent": accent}


def _customer_style_label(style_id: str, display_name: str) -> str:
    english = {
        "minimal_warm": "Modern Minimalist",
        "modern_tropical": "Modern Tropical",
        "indochine_soft": "Indochine Soft",
    }.get(style_id, style_id.replace("_", " ").title())
    return f"{english} / {display_name}"


def _revision_summary(
    *,
    parent_version_id: str,
    child_version_id: str,
    concept_model: ArchitecturalConceptModel,
    operations: tuple[RevisionOperation, ...],
    changelog: tuple[str, ...],
    changed_fields: tuple[str, ...],
) -> dict:
    return {
        "parent_version_id": parent_version_id,
        "child_version_id": child_version_id,
        "operation_count": len(operations),
        "changed_fields": changed_fields,
        "changelog": changelog,
        "requires_confirmation": any(operation.requires_confirmation for operation in operations),
        "blockers": tuple(
            blocker
            for operation in operations
            for blocker in tuple(operation.parameters.get("blocked_scopes") or ())
            if isinstance(operation.parameters, dict)
        ),
        "preserved": {
            "lot_width_m": concept_model.site.width_m.value,
            "lot_depth_m": concept_model.site.depth_m.value,
            "floor_count": len(concept_model.levels),
            "room_count": len(concept_model.rooms),
            "selected_or_inferred_style": concept_model.style.value if concept_model.style else None,
            "concept_only_status": concept_model.concept_status_note,
        },
        "construction_ready": False,
    }


def _dedupe_decisions(decisions: list[DecisionValue]) -> tuple[DecisionValue, ...]:
    seen: set[tuple[str, str]] = set()
    output: list[DecisionValue] = []
    for decision in decisions:
        key = (str(decision.value), decision.customer_visible_explanation)
        if key in seen:
            continue
        seen.add(key)
        output.append(decision)
    return tuple(output)


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
    if operation.source == "reference_image_descriptor":
        return DecisionValue(
            value=tuple(operation.parameters.get("descriptor_signals") or operation.parameters.items()),
            source="reference_image",
            confidence=operation.confidence,
            assumption=True,
            customer_visible_explanation=f"{operation.customer_visible_explanation} Reference descriptors are homeowner-provided style hints only; no real image analysis is performed.",
            needs_confirmation=operation.requires_confirmation,
        )
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
