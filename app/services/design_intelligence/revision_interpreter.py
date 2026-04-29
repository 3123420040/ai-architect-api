from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.services.design_intelligence.concept_model import ArchitecturalConceptModel
from app.services.design_intelligence.customer_understanding import ReferenceImageDescriptor
from app.services.professional_deliverables.style_knowledge import normalize_signal


REVISION_SOURCES = {"homeowner_feedback", "reference_image_descriptor", "ai_assumption", "style_profile"}

UNSAFE_SCOPE_KEYWORDS = (
    "ban ve thi cong",
    "ho so xin phep",
    "xin phep",
    "cap phep",
    "permit",
    "construction",
    "thi cong",
    "ket cau",
    "structural",
    "mep",
    "dien nuoc",
    "phap ly",
    "legal",
    "dia chat",
    "geotechnical",
    "quy chuan",
    "code compliant",
    "code compliance",
)


@dataclass(frozen=True)
class RevisionOperation:
    type: str
    target_id: str | None
    intent: str
    parameters: dict[str, Any]
    confidence: float
    customer_visible_explanation: str
    source: str = "homeowner_feedback"
    requires_confirmation: bool = False
    affected_room_id: str | None = None
    affected_style_intent: str | None = None
    affected_layout_intent: str | None = None

    def __post_init__(self) -> None:
        if self.source not in REVISION_SOURCES:
            raise ValueError(f"Unsupported revision source: {self.source}")
        if not 0.0 <= float(self.confidence) <= 1.0:
            raise ValueError("Revision confidence must be between 0 and 1")
        if not self.customer_visible_explanation:
            raise ValueError("Revision operation needs a customer-visible explanation")

    @property
    def explanation(self) -> str:
        return self.customer_visible_explanation

    @property
    def needs_confirmation(self) -> bool:
        return self.requires_confirmation

    def as_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "target_id": self.target_id,
            "intent": self.intent,
            "parameters": self.parameters,
            "confidence": self.confidence,
            "source": self.source,
            "explanation": self.customer_visible_explanation,
            "customer_visible_explanation": self.customer_visible_explanation,
            "requires_confirmation": self.requires_confirmation,
            "confirmation_required": self.requires_confirmation,
            "affected_room_id": self.affected_room_id,
            "affected_style_intent": self.affected_style_intent,
            "affected_layout_intent": self.affected_layout_intent,
        }


@dataclass(frozen=True)
class RevisionInterpretation:
    original_feedback: str
    operations: tuple[RevisionOperation, ...]
    needs_confirmation: bool
    confirmation_question: str | None = None
    blockers: tuple[str, ...] = ()


def parse_revision_feedback(
    feedback: str,
    concept_model: ArchitecturalConceptModel,
    reference_image_descriptors: list[dict[str, Any] | ReferenceImageDescriptor] | tuple[dict[str, Any] | ReferenceImageDescriptor, ...] | None = None,
) -> RevisionInterpretation:
    normalized = normalize_signal(feedback)
    descriptors = _reference_descriptors(reference_image_descriptors)
    unsafe_blockers = _unsafe_blockers(normalized)
    if unsafe_blockers:
        operation = _operation(
            "ask_clarifying_question",
            None,
            "concept_only_scope_guard",
            {
                "blocked_scopes": unsafe_blockers,
                "concept_status": concept_model.concept_status_note,
            },
            0.93,
            "Bản này chỉ là concept 2D để trao đổi ý tưởng; phần xin phép, thi công, kết cấu, MEP hoặc pháp lý cần hồ sơ kỹ thuật riêng.",
            requires_confirmation=True,
            affected_layout_intent="concept_only_scope",
        )
        return RevisionInterpretation(
            original_feedback=feedback,
            operations=(operation, _preserve_existing_requirements_operation(concept_model)),
            needs_confirmation=True,
            confirmation_question="Em giữ phạm vi concept-only cho bản này. Anh/chị muốn em chỉnh ý tưởng không gian/style trước, hay cần tách một bước tư vấn hồ sơ kỹ thuật riêng?",
            blockers=unsafe_blockers,
        )

    operations: list[RevisionOperation] = []

    if any(keyword in normalized for keyword in ("phong khach rong hon", "tang phong khach", "living rong")):
        room_id = _find_room_id(concept_model, {"living"}, {"phòng khách", "phong khach"})
        operations.append(
            _operation(
                "resize_room_intent",
                room_id,
                "increase_area",
                {"delta_m": 0.5, "preserve_site_boundary": True},
                0.84,
                "Nới phòng khách thêm khoảng 0.5m trong mặt bằng concept và cân lại phòng kế tiếp.",
                affected_room_id=room_id,
                affected_layout_intent="public_zone_priority",
            )
        )
    if any(
        keyword in normalized
        for keyword in (
            "bep va an rong hon",
            "bep an rong hon",
            "bep rong hon",
            "nha bep rong hon",
            "noi bep",
            "noi khu bep",
            "kitchen/dining larger",
            "kitchen dining larger",
            "kitchen larger",
            "larger kitchen",
            "enlarge kitchen",
            "make kitchen larger",
            "make the kitchen dining larger",
        )
    ):
        kitchen_id = _find_room_id(concept_model, {"kitchen_dining"}, {"bếp", "bep", "bếp và ăn", "bep va an"})
        operations.append(
            _operation(
                "resize_room_intent",
                kitchen_id,
                "increase_kitchen_dining_area",
                {
                    "delta_m": 0.6,
                    "preserve_site_boundary": True,
                    "preferred_tradeoff_room_types": ("secondary_bedroom", "storage", "living"),
                    "allow_service_zone_shift": True,
                },
                0.86,
                "Nới ưu tiên bếp/ăn trong concept, dùng phần dư hoặc cân lại phòng phụ nếu cần nhưng vẫn giữ ranh đất và chương trình chính.",
                affected_room_id=kitchen_id,
                affected_layout_intent="kitchen_dining_priority",
            )
        )
    if any(keyword in normalized for keyword in ("bep mo", "bep lien thong", "mo bep", "bep thoang hon")):
        kitchen_id = _find_room_id(concept_model, {"kitchen_dining"}, {"bếp", "bep"})
        operations.append(
            _operation(
                "adjust_room_priority",
                kitchen_id,
                "open_kitchen_connection",
                {"open_kitchen": True, "priority": "public_connection"},
                0.78,
                "Ưu tiên bếp mở/liên thông hơn ở mức concept và vẫn giữ các phòng bắt buộc.",
                affected_room_id=kitchen_id,
                affected_layout_intent="kitchen_public_connection",
            )
        )
    if any(keyword in normalized for keyword in ("bep kin", "bep kin hon", "dong bep", "khep kin bep", "bep rieng tu hon")):
        kitchen_id = _find_room_id(concept_model, {"kitchen_dining"}, {"bếp", "bep"})
        operations.append(
            _operation(
                "adjust_room_priority",
                kitchen_id,
                "increase_kitchen_privacy",
                {"open_kitchen": False, "priority": "odor_privacy"},
                0.82,
                "Ưu tiên bếp kín hơn để giảm mùi và tăng riêng tư, nhưng chưa đổi kết cấu ở mức concept.",
                affected_room_id=kitchen_id,
                affected_layout_intent="kitchen_privacy",
            )
        )
    if any(
        keyword in normalized
        for keyword in (
            "them luu tru",
            "nhieu luu tru hon",
            "them kho",
            "them tu do",
            "add more storage",
            "more storage",
            "storage near",
            "near entry",
            "near the entry",
            "bedroom storage",
        )
    ):
        operations.append(
            _operation(
                "add_storage_preference",
                None,
                "add_entry_and_bedroom_storage",
                {
                    "zones": ("entry", "bedrooms"),
                    "reduce_secondary_bedroom_if_needed": "reduce secondary bedroom" in normalized or "giam phong ngu phu" in normalized,
                    "preserve_required_room_count": True,
                },
                0.86,
                "Bổ sung ý đồ lưu trữ gần lối vào và khu phòng ngủ; nếu cần chỉ thu gọn phòng ngủ phụ ở mức concept, không bỏ phòng bắt buộc.",
                affected_layout_intent="storage_priority",
            )
        )
    if any(keyword in normalized for keyword in ("them phong ngu", "them 1 phong ngu", "add bedroom")):
        operations.append(
            _operation(
                "add_assumption",
                None,
                "add_one_bedroom_program_review",
                {"count": 1, "requires_layout_regeneration": True},
                0.72,
                "Ghi nhận nhu cầu thêm một phòng ngủ; cần cân lại chương trình phòng ở lần dựng layout tiếp theo.",
                requires_confirmation=True,
                affected_layout_intent="room_program",
            )
        )
    if any(keyword in normalized for keyword in ("chuyen phong ngu ong ba xuong tang 1", "phong ngu ong ba xuong tang 1", "ong ba xuong tang 1", "nguoi gia xuong tang 1")):
        bedroom_id = _find_elder_or_candidate_bedroom_id(concept_model)
        operations.append(
            _operation(
                "move_room_preference",
                bedroom_id,
                "move_elder_bedroom_to_ground_floor",
                {
                    "room_label": "Phòng ngủ ông bà",
                    "preferred_level_id": "L1",
                    "preferred_floor_number": 1,
                    "preserve_total_bedrooms": True,
                    "requires_layout_regeneration": bedroom_id is None or not _room_is_on_level(concept_model, bedroom_id, "L1"),
                },
                0.88,
                "Ưu tiên đưa phòng ngủ ông bà xuống tầng 1 để đi lại thuận tiện, đồng thời giữ số phòng ngủ đã yêu cầu.",
                affected_room_id=bedroom_id,
                affected_layout_intent="elder_accessibility",
            )
        )
    if any(keyword in normalized for keyword in ("nhieu cay hon", "them cay", "them xanh", "greenery")):
        operations.append(
            _operation(
                "add_or_strengthen_style_feature",
                "style",
                "increase_greenery",
                {"feature": "greenery", "level": "more"},
                0.78,
                "Tăng nhấn mạnh cây xanh/ban công xanh trong concept.",
                affected_style_intent=_current_style_id(concept_model),
                affected_layout_intent="greenery_and_balcony",
            )
        )
    if any(keyword in normalized for keyword in ("gieng troi", "skylight", "lightwell")):
        operations.append(
            _operation(
                "add_or_strengthen_style_feature",
                "layout",
                "strengthen_lightwell",
                {"feature": "lightwell", "level": "more_visible"},
                0.78,
                "Tăng vai trò giếng trời/lõi lấy sáng trong concept nếu phù hợp mặt bằng.",
                affected_layout_intent="daylight_and_ventilation",
            )
        )
    if any(keyword in normalized for keyword in ("khong thich qua nhieu kinh", "it kinh hon", "giam kinh", "bot kinh", "less glass")):
        operations.append(
            _operation(
                "suppress_style_feature",
                "style",
                "reduce_glass_heavy_expression",
                {"feature": "glass", "replacement": "shaded_screens_or_solid_warm_surfaces"},
                0.87,
                "Giảm cảm giác quá nhiều kính, ưu tiên mảng đặc ấm hơn và che nắng/lọc nhìn phù hợp style hiện tại.",
                affected_style_intent=_current_style_id(concept_model),
                affected_layout_intent="facade_openings",
            )
        )
    if any(keyword in normalized for keyword in ("am hon", "it lanh", "bot lanh", "warm", "warmer")):
        operations.append(
            _operation(
                "add_or_strengthen_style_feature",
                "style",
                "warmer_material_palette",
                {"feature": "warmer_palette", "materials": ("warm wood", "cream_neutral", "soft_lighting")},
                0.81,
                "Làm bảng vật liệu/không khí ấm hơn, giảm cảm giác lạnh mà vẫn giữ hướng style đã chọn.",
                affected_style_intent=_current_style_id(concept_model),
            )
        )
    if any(keyword in normalized for keyword in ("dong duong nhe hon", "indochine nhe hon", "kieu dong duong nhe", "indochine soft")):
        operations.append(
            _operation(
                "add_or_strengthen_style_feature",
                "style",
                "indochine_decorative_restraint",
                {"feature": "indochine_decorative_restraint", "level": "light"},
                0.82,
                "Tăng chất Đông Dương nhẹ bằng chi tiết tiết chế, không biến concept thành hướng cổ điển nặng.",
                affected_style_intent="indochine_soft",
            )
        )
    if any(keyword in normalized for keyword in ("mat tien", "facade")) and any(keyword in normalized for keyword in ("don gian", "noi bat", "xanh", "am")):
        operations.append(
            _operation(
                "add_or_strengthen_style_feature",
                "facade",
                "adjust_facade_emphasis",
                {"feedback": feedback},
                0.68,
                "Điều chỉnh điểm nhấn mặt tiền theo phản hồi của khách ở mức concept.",
                requires_confirmation=True,
                affected_style_intent=_current_style_id(concept_model),
                affected_layout_intent="facade_expression",
            )
        )
    target_style_id = _target_style_id(normalized)
    if any(keyword in normalized for keyword in ("doi sang", "chuyen sang", "change the style", "change style")) and target_style_id:
        previous_style_id = _current_style_id(concept_model)
        operations.append(
            _operation(
                "change_style_direction",
                "style",
                "change_style_direction",
                {
                    "target_style_id": target_style_id,
                    "previous_style_id": previous_style_id,
                    "preserve_original_style_context": True,
                    "preserve_geometry": True,
                    "preserve_room_program": True,
                    "feedback": feedback,
                },
                0.9 if target_style_id != previous_style_id else 0.78,
                f"Đổi hướng style sang {_style_label(target_style_id)} ở mức concept, đồng thời giữ kích thước lô đất, số tầng và chương trình phòng gốc.",
                affected_style_intent=target_style_id,
            )
        )
    elif any(keyword in normalized for keyword in ("doi sang", "chuyen sang")) and any(keyword in normalized for keyword in ("indochine", "toi gian", "hien dai")):
        operations.append(
            _operation(
                "add_or_strengthen_style_feature",
                "style",
                "change_style_direction",
                {"feedback": feedback, "preserve_original_style_context": True},
                0.66,
                "Cập nhật hướng style theo phản hồi của khách nhưng vẫn giữ lại bối cảnh concept gốc để xác nhận.",
                requires_confirmation=True,
                affected_style_intent=_current_style_id(concept_model),
            )
        )

    operations.extend(_descriptor_operations(descriptors, normalized, concept_model))

    if not operations:
        if _is_ambiguous_feedback(normalized):
            question = "Mình hiểu là anh/chị muốn bản vẽ nhẹ và dễ ở hơn. Em đề xuất ưu tiên phòng khách thoáng hơn và giảm kính mặt tiền, anh/chị xác nhận giúp em nhé?"
        else:
            question = "Em chưa rõ muốn chỉnh phần nào. Anh/chị muốn nới phòng, đổi bếp, thêm cây xanh hay chỉnh mặt tiền?"
        return RevisionInterpretation(
            original_feedback=feedback,
            operations=(
                _operation(
                    "ask_clarifying_question",
                    None,
                    "clarify_homeowner_revision_goal",
                    {"safe_default_assumption": "airier_living_and_less_glass", "destructive_layout_changes_allowed": False},
                    0.44,
                    question,
                    source="ai_assumption",
                    requires_confirmation=True,
                    affected_layout_intent="revision_scope",
                ),
                _preserve_existing_requirements_operation(concept_model),
            ),
            needs_confirmation=True,
            confirmation_question=question,
        )
    operations.append(_preserve_existing_requirements_operation(concept_model))
    needs_confirmation = any(operation.requires_confirmation or operation.confidence < 0.7 for operation in operations)
    return RevisionInterpretation(
        original_feedback=feedback,
        operations=tuple(operations),
        needs_confirmation=needs_confirmation,
        confirmation_question="Em sẽ chỉnh theo các ý trên ở mức concept và giữ các yêu cầu gốc, anh/chị xác nhận giúp em nhé." if needs_confirmation else None,
    )


def _find_room_id(concept_model: ArchitecturalConceptModel, room_types: set[str], labels: set[str]) -> str | None:
    normalized_labels = {normalize_signal(label) for label in labels}
    for room in concept_model.rooms:
        if room.room_type in room_types or normalize_signal(room.label_vi) in normalized_labels:
            return room.id
    return None


def _operation(
    operation_type: str,
    target_id: str | None,
    intent: str,
    parameters: dict[str, Any],
    confidence: float,
    explanation: str,
    *,
    source: str = "homeowner_feedback",
    requires_confirmation: bool = False,
    affected_room_id: str | None = None,
    affected_style_intent: str | None = None,
    affected_layout_intent: str | None = None,
) -> RevisionOperation:
    return RevisionOperation(
        type=operation_type,
        target_id=target_id,
        intent=intent,
        parameters=parameters,
        confidence=confidence,
        customer_visible_explanation=explanation,
        source=source,
        requires_confirmation=requires_confirmation,
        affected_room_id=affected_room_id,
        affected_style_intent=affected_style_intent,
        affected_layout_intent=affected_layout_intent,
    )


def _preserve_existing_requirements_operation(concept_model: ArchitecturalConceptModel) -> RevisionOperation:
    return _operation(
        "preserve_existing_requirement",
        None,
        "preserve_original_concept_contract",
        {
            "preserve": (
                "lot_dimensions",
                "project_type",
                "family_lifestyle",
                "required_rooms",
                "selected_or_inferred_style",
                "concept_only_status",
                "previous_assumptions",
            ),
            "lot_dimensions": {
                "width_m": concept_model.site.width_m.value,
                "depth_m": concept_model.site.depth_m.value,
            },
            "style_id": _current_style_id(concept_model),
            "unless_feedback_clearly_overrides": True,
        },
        0.99,
        "Giữ nguyên kích thước, loại công trình, thông tin gia đình, phòng bắt buộc, style và trạng thái concept-only trừ khi phản hồi ghi rõ cần đổi.",
        source="ai_assumption",
    )


def _find_elder_or_candidate_bedroom_id(concept_model: ArchitecturalConceptModel) -> str | None:
    elder_keywords = ("ong ba", "nguoi gia", "lon tuoi")
    for room in concept_model.rooms:
        label = normalize_signal(room.label_vi)
        if room.room_type == "bedroom" and any(keyword in label for keyword in elder_keywords):
            return room.id
    upper_bedroom = next((room for room in concept_model.rooms if room.room_type == "bedroom" and room.level_id != "L1"), None)
    if upper_bedroom is not None:
        return upper_bedroom.id
    bedroom = next((room for room in concept_model.rooms if room.room_type == "bedroom"), None)
    return bedroom.id if bedroom else None


def _room_is_on_level(concept_model: ArchitecturalConceptModel, room_id: str, level_id: str) -> bool:
    return any(room.id == room_id and room.level_id == level_id for room in concept_model.rooms)


def _current_style_id(concept_model: ArchitecturalConceptModel) -> str | None:
    return str(concept_model.style.value) if concept_model.style else None


def _target_style_id(normalized: str) -> str | None:
    if any(keyword in normalized for keyword in ("minimal warm", "toi gian am", "toi gian nong", "calmer and warmer", "calm and warm")):
        return "minimal_warm"
    if any(keyword in normalized for keyword in ("modern tropical", "hien dai nhiet doi", "nhiet doi", "xanh mat hien dai")):
        return "modern_tropical"
    if any(keyword in normalized for keyword in ("indochine", "dong duong", "dong duong nhe")):
        return "indochine_soft"
    return None


def _style_label(style_id: str) -> str:
    return {
        "minimal_warm": "tối giản ấm",
        "modern_tropical": "hiện đại nhiệt đới",
        "indochine_soft": "Đông Dương nhẹ",
    }.get(style_id, style_id.replace("_", " "))


def _reference_descriptors(
    descriptors: list[dict[str, Any] | ReferenceImageDescriptor] | tuple[dict[str, Any] | ReferenceImageDescriptor, ...] | None,
) -> tuple[ReferenceImageDescriptor, ...]:
    return tuple(ReferenceImageDescriptor.from_payload(item) for item in (descriptors or ()))


def _descriptor_operations(
    descriptors: tuple[ReferenceImageDescriptor, ...],
    normalized_feedback: str,
    concept_model: ArchitecturalConceptModel,
) -> list[RevisionOperation]:
    if not descriptors:
        return []
    should_use_reference = any(keyword in normalized_feedback for keyword in ("hinh mau", "hinh tham khao", "reference", "giong hinh", "giong anh", "am hon", "it lanh"))
    if not should_use_reference:
        return []
    descriptor_signals = tuple(dict.fromkeys(signal for descriptor in descriptors for signal in descriptor.signals()))
    signals = " ".join(normalize_signal(signal) for signal in descriptor_signals)
    feature_specs = (
        (
            "warmer_palette",
            ("warm", "am", "cream", "mau kem", "wood", "go", "dark wood", "earth", "neutral"),
            "Bám descriptor hình mẫu để làm palette ấm hơn bằng gỗ/kem/trung tính.",
        ),
        (
            "arches_or_screens",
            ("arch", "arched", "vom", "screen", "louver", "rattan", "may tre", "pergola"),
            "Bám descriptor hình mẫu cho chi tiết vòm/màn lọc nắng ở mức tiết chế.",
        ),
        (
            "more_greenery",
            ("greenery", "plant", "cay", "tropical"),
            "Bám descriptor hình mẫu để tăng mảng xanh phù hợp concept.",
        ),
        (
            "more_storage",
            ("storage", "cabinet", "built in", "tu do", "luu tru"),
            "Bám descriptor hình mẫu để tăng ý đồ lưu trữ gọn hơn.",
        ),
        (
            "softer_facade",
            ("soft facade", "softer", "curved", "rounded", "mem"),
            "Bám descriptor hình mẫu để làm mặt đứng mềm hơn ở mức concept.",
        ),
        (
            "tropical_shading",
            ("shade", "shading", "deep overhang", "overhang", "louver", "che nang"),
            "Bám descriptor hình mẫu để tăng che nắng nhiệt đới thay vì mở kính thô.",
        ),
        (
            "indochine_decorative_restraint",
            ("indochine", "dong duong", "pattern tile", "gach bong", "rattan", "dark wood", "cream"),
            "Bám descriptor hình mẫu để thêm chất Đông Dương nhẹ, tiết chế chi tiết trang trí.",
        ),
    )
    operations: list[RevisionOperation] = []
    for feature, keywords, explanation in feature_specs:
        if not any(keyword in signals for keyword in keywords):
            continue
        operations.append(
            _operation(
                "add_or_strengthen_style_feature",
                "style",
                f"reference_descriptor_{feature}",
                {"feature": feature, "descriptor_signals": descriptor_signals[:12]},
                0.72,
                explanation,
                source="reference_image_descriptor",
                affected_style_intent=_current_style_id(concept_model),
            )
        )
    if any(keyword in signals for keyword in ("less glass", "it kinh", "small window", "solid wall")):
        operations.append(
            _operation(
                "suppress_style_feature",
                "style",
                "reference_descriptor_reduce_glass",
                {"feature": "glass", "replacement": "solid_or_screened_warm_surfaces"},
                0.72,
                "Bám descriptor hình mẫu để giảm mảng kính lớn và dùng bề mặt ấm/lọc nắng hơn.",
                source="reference_image_descriptor",
                affected_style_intent=_current_style_id(concept_model),
                affected_layout_intent="facade_openings",
            )
        )
    return operations


def _unsafe_blockers(normalized: str) -> tuple[str, ...]:
    return tuple(keyword for keyword in UNSAFE_SCOPE_KEYWORDS if keyword in normalized)


def _is_ambiguous_feedback(normalized: str) -> bool:
    ambiguous_keywords = ("nhin chua on", "chua on", "khong on", "sua cho dep hon", "chinh lai cho dep", "dep hon", "chua dep")
    return any(keyword in normalized for keyword in ambiguous_keywords)
