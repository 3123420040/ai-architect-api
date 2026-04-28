from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.services.design_intelligence.concept_model import ArchitecturalConceptModel
from app.services.professional_deliverables.style_knowledge import normalize_signal


@dataclass(frozen=True)
class RevisionOperation:
    type: str
    target_id: str | None
    intent: str
    parameters: dict[str, Any]
    confidence: float
    customer_visible_explanation: str


@dataclass(frozen=True)
class RevisionInterpretation:
    original_feedback: str
    operations: tuple[RevisionOperation, ...]
    needs_confirmation: bool
    confirmation_question: str | None = None


def parse_revision_feedback(feedback: str, concept_model: ArchitecturalConceptModel) -> RevisionInterpretation:
    normalized = normalize_signal(feedback)
    operations: list[RevisionOperation] = []

    if any(keyword in normalized for keyword in ("phong khach rong hon", "tang phong khach", "living rong")):
        room_id = _find_room_id(concept_model, {"living"}, {"phòng khách", "phong khach"})
        operations.append(
            RevisionOperation(
                type="resize_room",
                target_id=room_id,
                intent="increase_area",
                parameters={"delta_m": 0.5},
                confidence=0.82,
                customer_visible_explanation="Nới phòng khách thêm khoảng 0.5m trong mặt bằng concept và cân lại phòng kế tiếp.",
            )
        )
    if any(keyword in normalized for keyword in ("bep mo", "bep lien thong", "mo bep")):
        operations.append(
            RevisionOperation(
                type="switch_kitchen_open_closed",
                target_id=_find_room_id(concept_model, {"kitchen_dining"}, {"bếp", "bep"}),
                intent="open_kitchen",
                parameters={"open": True},
                confidence=0.78,
                customer_visible_explanation="Chuyển bếp sang hướng mở/liên thông ở mức concept.",
            )
        )
    if any(keyword in normalized for keyword in ("bep kin", "dong bep", "khep kin bep")):
        operations.append(
            RevisionOperation(
                type="switch_kitchen_open_closed",
                target_id=_find_room_id(concept_model, {"kitchen_dining"}, {"bếp", "bep"}),
                intent="closed_kitchen",
                parameters={"open": False},
                confidence=0.78,
                customer_visible_explanation="Chuyển bếp sang hướng kín hơn ở mức concept.",
            )
        )
    if any(keyword in normalized for keyword in ("them phong ngu", "them 1 phong ngu", "add bedroom")):
        operations.append(
            RevisionOperation(
                type="add_bedroom",
                target_id=None,
                intent="add_one_bedroom",
                parameters={"count": 1},
                confidence=0.72,
                customer_visible_explanation="Bổ sung một phòng ngủ vào chương trình concept nếu mặt bằng còn đủ chỗ.",
            )
        )
    if any(keyword in normalized for keyword in ("nhieu cay hon", "them cay", "them xanh", "greenery")):
        operations.append(
            RevisionOperation(
                type="adjust_greenery",
                target_id=None,
                intent="increase_greenery",
                parameters={"level": "more"},
                confidence=0.76,
                customer_visible_explanation="Tăng nhấn mạnh cây xanh/ban công xanh trong concept.",
            )
        )
    if any(keyword in normalized for keyword in ("mat tien", "facade")) and any(keyword in normalized for keyword in ("don gian", "noi bat", "xanh", "am")):
        operations.append(
            RevisionOperation(
                type="change_facade_emphasis",
                target_id="facade",
                intent="adjust_facade_emphasis",
                parameters={"feedback": feedback},
                confidence=0.68,
                customer_visible_explanation="Điều chỉnh điểm nhấn mặt tiền theo phản hồi của khách.",
            )
        )
    if any(keyword in normalized for keyword in ("doi sang", "chuyen sang")) and any(keyword in normalized for keyword in ("indochine", "toi gian", "hien dai")):
        operations.append(
            RevisionOperation(
                type="update_style_parameter",
                target_id="style",
                intent="change_style_direction",
                parameters={"feedback": feedback},
                confidence=0.66,
                customer_visible_explanation="Cập nhật hướng style theo phản hồi của khách.",
            )
        )

    if not operations:
        return RevisionInterpretation(
            original_feedback=feedback,
            operations=(),
            needs_confirmation=True,
            confirmation_question="Em chưa rõ muốn chỉnh phần nào. Anh/chị muốn nới phòng, đổi bếp, thêm cây xanh hay chỉnh mặt tiền?",
        )
    needs_confirmation = any(operation.confidence < 0.7 or operation.target_id is None and operation.type in {"resize_room", "switch_kitchen_open_closed"} for operation in operations)
    return RevisionInterpretation(
        original_feedback=feedback,
        operations=tuple(operations),
        needs_confirmation=needs_confirmation,
        confirmation_question="Em sẽ chỉnh theo các ý trên ở mức concept, anh/chị xác nhận giúp em nhé." if needs_confirmation else None,
    )


def _find_room_id(concept_model: ArchitecturalConceptModel, room_types: set[str], labels: set[str]) -> str | None:
    normalized_labels = {normalize_signal(label) for label in labels}
    for room in concept_model.rooms:
        if room.room_type in room_types or normalize_signal(room.label_vi) in normalized_labels:
            return room.id
    return None
