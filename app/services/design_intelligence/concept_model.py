from __future__ import annotations

from dataclasses import dataclass, field
from math import sqrt
from typing import Any

from app.services.design_intelligence.customer_understanding import CustomerUnderstanding
from app.services.design_intelligence.provenance import DecisionValue, ai_proposal, rule_default, user_fact
from app.services.design_intelligence.style_inference import StyleInferenceResult


Point = tuple[float, float]


class ConceptModelValidationError(ValueError):
    pass


@dataclass(frozen=True)
class ConceptSite:
    boundary: DecisionValue
    width_m: DecisionValue
    depth_m: DecisionValue
    area_m2: DecisionValue
    orientation: DecisionValue | None = None
    access_edge: DecisionValue | None = None


@dataclass(frozen=True)
class ConceptBuildableArea:
    polygon: DecisionValue
    front_setback_m: DecisionValue
    rear_setback_m: DecisionValue
    side_setback_m: DecisionValue


@dataclass(frozen=True)
class ConceptLevel:
    id: str
    floor_number: int
    name: str
    finished_floor_elevation_m: DecisionValue
    floor_to_floor_height_m: DecisionValue
    clear_height_m: DecisionValue


@dataclass(frozen=True)
class ConceptRoom:
    id: str
    level_id: str
    room_type: str
    label_vi: str
    polygon: DecisionValue
    area_m2: DecisionValue
    priority: DecisionValue
    adjacency: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class ConceptWall:
    id: str
    level_id: str
    start: DecisionValue
    end: DecisionValue
    thickness_m: DecisionValue
    height_m: DecisionValue
    wall_type: str
    exterior: bool


@dataclass(frozen=True)
class ConceptOpening:
    id: str
    level_id: str
    wall_id: str
    opening_type: str
    width_m: DecisionValue
    height_m: DecisionValue
    sill_height_m: DecisionValue | None
    operation: DecisionValue
    start: DecisionValue | None = None
    end: DecisionValue | None = None


@dataclass(frozen=True)
class ConceptStair:
    id: str
    level_from: str
    level_to: str
    footprint: DecisionValue
    width_m: DecisionValue
    strategy: DecisionValue


@dataclass(frozen=True)
class ConceptFixture:
    id: str
    level_id: str
    room_id: str | None
    fixture_type: str
    position: DecisionValue
    dimensions_m: DecisionValue
    label_vi: str


@dataclass(frozen=True)
class ConceptFacade:
    style_id: DecisionValue
    strategy: DecisionValue
    material_notes: tuple[DecisionValue, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class ConceptSectionLine:
    id: str
    label: str
    start: DecisionValue
    end: DecisionValue
    intent: DecisionValue


@dataclass(frozen=True)
class ArchitecturalConceptModel:
    project_id: str
    source_brief: str
    concept_status_note: str
    site: ConceptSite
    buildable_area: ConceptBuildableArea
    levels: tuple[ConceptLevel, ...]
    rooms: tuple[ConceptRoom, ...] = field(default_factory=tuple)
    walls: tuple[ConceptWall, ...] = field(default_factory=tuple)
    openings: tuple[ConceptOpening, ...] = field(default_factory=tuple)
    stairs: tuple[ConceptStair, ...] = field(default_factory=tuple)
    fixtures: tuple[ConceptFixture, ...] = field(default_factory=tuple)
    style: DecisionValue | None = None
    facade: ConceptFacade | None = None
    section_lines: tuple[ConceptSectionLine, ...] = field(default_factory=tuple)
    assumptions: tuple[DecisionValue, ...] = field(default_factory=tuple)
    metadata: dict[str, Any] = field(default_factory=dict)


def seed_concept_model(
    *,
    project_id: str,
    understanding: CustomerUnderstanding,
    style_inference: StyleInferenceResult,
) -> ArchitecturalConceptModel:
    site_facts = understanding.site_facts
    derived_apartment_rectangle = False
    if ("width_m" not in site_facts or "depth_m" not in site_facts) and site_facts.get("project_type") == "apartment_renovation" and site_facts.get("area_m2"):
        area_value = float(site_facts["area_m2"])
        width_guess = round(sqrt(area_value * 0.72), 2)
        depth_guess = round(area_value / width_guess, 2)
        site_facts = {**site_facts, "width_m": width_guess, "depth_m": depth_guess, "shape": "assumed_apartment_rectangle"}
        derived_apartment_rectangle = True
    if "width_m" not in site_facts or "depth_m" not in site_facts:
        raise ConceptModelValidationError("Lot width/depth or a site polygon is required before seeding a concept model")

    width = float(site_facts["width_m"])
    depth = float(site_facts["depth_m"])
    area = float(site_facts.get("area_m2") or width * depth)
    boundary: tuple[Point, ...] = ((0.0, 0.0), (width, 0.0), (width, depth), (0.0, depth))
    default_floors = 1 if site_facts.get("project_type") == "apartment_renovation" else 2
    floors = int(understanding.room_program_hints.get("floors") or default_floors)
    levels = tuple(
        ConceptLevel(
            id=f"L{floor}",
            floor_number=floor,
            name=f"Tầng {floor}",
            finished_floor_elevation_m=rule_default((floor - 1) * 3.3, f"Cao độ tầng {floor} tạm tính theo chiều cao tầng concept.", confidence=0.7),
            floor_to_floor_height_m=rule_default(3.3, "Chiều cao tầng concept lấy mặc định 3.3m để dựng sơ đồ.", confidence=0.7),
            clear_height_m=rule_default(3.0, "Chiều cao thông thủy concept lấy mặc định 3.0m.", confidence=0.68),
        )
        for floor in range(1, floors + 1)
    )

    selected = style_inference.selected_style_id or (style_inference.candidates[0].style_id if style_inference.candidates else "minimal_warm")
    selected_confidence = next((candidate.confidence for candidate in style_inference.candidates if candidate.style_id == selected), 0.5)
    style_decision = ai_proposal(
        selected,
        "Phong cách được suy luận từ mô tả khách hàng và tín hiệu hình ảnh tham khảo.",
        confidence=selected_confidence,
        needs_confirmation=style_inference.needs_confirmation,
    )
    assumption_items = list(understanding.assumptions)
    if derived_apartment_rectangle:
        assumption_items.append("Assume a simple apartment rectangle from stated area until an as-built plan is provided.")
    assumptions = tuple(
        rule_default(item, item, confidence=0.76, needs_confirmation="rectangle" in item.lower())
        for item in assumption_items
    )

    model = ArchitecturalConceptModel(
        project_id=project_id,
        source_brief=understanding.original_text,
        concept_status_note="Professional Concept 2D Package - not for construction.",
        site=ConceptSite(
            boundary=rule_default(boundary, "Tạm dựng ranh đất hình chữ nhật từ kích thước khách hàng cung cấp.", confidence=0.82, needs_confirmation=True),
            width_m=rule_default(width, f"Chiều ngang căn hộ concept tạm suy ra khoảng {width:g}m từ diện tích.") if derived_apartment_rectangle else user_fact(width, f"Khách hàng cung cấp chiều ngang lô đất {width:g}m."),
            depth_m=rule_default(depth, f"Chiều sâu căn hộ concept tạm suy ra khoảng {depth:g}m từ diện tích.") if derived_apartment_rectangle else user_fact(depth, f"Khách hàng cung cấp chiều sâu lô đất {depth:g}m."),
            area_m2=user_fact(area, f"Diện tích khách hàng cung cấp/tạm tính là {area:g}m2."),
            orientation=user_fact(site_facts["orientation"], "Hướng đất do khách hàng cung cấp.") if site_facts.get("orientation") else None,
            access_edge=rule_default("front", "Giả định lối tiếp cận ở cạnh trước lô đất cho concept.", confidence=0.72, needs_confirmation=True),
        ),
        buildable_area=ConceptBuildableArea(
            polygon=rule_default(boundary, "Vùng xây dựng concept tạm bám theo ranh đất trước khi có thông tin lùi ranh.", confidence=0.62, needs_confirmation=True),
            front_setback_m=rule_default(0.0, "Chưa có yêu cầu lùi ranh; concept giữ giá trị 0m và sẽ thể hiện như giả định.", confidence=0.55, needs_confirmation=True),
            rear_setback_m=rule_default(0.0, "Chưa có yêu cầu lùi ranh sau; concept giữ giá trị 0m và sẽ thể hiện như giả định.", confidence=0.55, needs_confirmation=True),
            side_setback_m=rule_default(0.0, "Chưa có yêu cầu lùi hông; concept giữ giá trị 0m và sẽ thể hiện như giả định.", confidence=0.55, needs_confirmation=True),
        ),
        levels=levels,
        style=style_decision,
        facade=ConceptFacade(
            style_id=style_decision,
            strategy=ai_proposal(
                "facade_strategy_pending_layout",
                "Chiến lược mặt tiền sẽ lấy từ style profile và layout ở bước tiếp theo.",
                confidence=0.6,
                needs_confirmation=False,
            ),
        ),
        assumptions=assumptions,
        metadata={
            "missing_blockers": understanding.missing_blockers,
            "room_program_hints": understanding.room_program_hints,
            "family_lifestyle": understanding.family_lifestyle,
        },
    )
    validate_concept_model(model)
    return model


def validate_concept_model(model: ArchitecturalConceptModel) -> None:
    if "construction" in model.concept_status_note.lower() and "not for construction" not in model.concept_status_note.lower():
        raise ConceptModelValidationError("Concept model must not claim construction readiness")
    boundary = model.site.boundary.value
    if not boundary or len(boundary) < 3:
        raise ConceptModelValidationError("Concept site boundary is required")
    if model.site.width_m.value <= 0 or model.site.depth_m.value <= 0:
        raise ConceptModelValidationError("Concept site dimensions must be positive")
    if model.site.boundary.assumption and not any(assumption.assumption for assumption in model.assumptions):
        raise ConceptModelValidationError("Assumed site geometry must be visible in assumptions")
    if not model.levels:
        raise ConceptModelValidationError("At least one concept level is required")
    if model.style is not None and model.style.assumption is False and model.style.source != "user_fact":
        raise ConceptModelValidationError("AI-filled style decisions must preserve assumption metadata")
