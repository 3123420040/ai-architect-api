from __future__ import annotations

from dataclasses import dataclass

from app.services.design_intelligence.concept_model import ArchitecturalConceptModel
from app.services.design_intelligence.customer_understanding import CustomerUnderstanding
from app.services.professional_deliverables.pattern_memory import PatternMemory, ProjectPattern


@dataclass(frozen=True)
class RoomProgramItem:
    room_type: str
    label_vi: str
    level_number: int
    priority: str
    target_area_m2: float | None = None


@dataclass(frozen=True)
class ProgramPlan:
    items: tuple[RoomProgramItem, ...]
    selected_pattern: ProjectPattern | None
    strategy_notes: tuple[str, ...]
    project_type: str | None = None


def plan_room_program(
    *,
    understanding: CustomerUnderstanding,
    concept_model: ArchitecturalConceptModel,
    style_id: str,
    pattern_memory: PatternMemory | None = None,
) -> ProgramPlan:
    facts = {
        "width_m": concept_model.site.width_m.value,
        "depth_m": concept_model.site.depth_m.value,
        "project_type": understanding.site_facts.get("project_type"),
        "floors": len(concept_model.levels),
        "bedrooms": understanding.room_program_hints.get("bedrooms"),
        "garage": understanding.room_program_hints.get("garage"),
        "occupants": understanding.family_lifestyle.get("occupant_count"),
        "signals": understanding.family_lifestyle.get("priorities", []),
    }
    patterns = (pattern_memory or PatternMemory()).retrieve(facts, style_id=style_id, limit=1)
    pattern = patterns[0] if patterns else None
    project_type = understanding.site_facts.get("project_type")
    floors = len(concept_model.levels)
    bedrooms = int(understanding.room_program_hints.get("bedrooms") or (2 if floors <= 2 else 3))
    has_garage = bool(understanding.room_program_hints.get("garage"))
    priorities = set(understanding.family_lifestyle.get("priorities", []) or [])
    wants_storage = bool(understanding.room_program_hints.get("storage") or "storage" in priorities)

    if project_type == "apartment_renovation":
        items: list[RoomProgramItem] = [
            RoomProgramItem("living", "Phòng khách", 1, "core_public"),
            RoomProgramItem("kitchen_dining", "Bếp và ăn", 1, "core_public"),
            RoomProgramItem("wc", "Vệ sinh", 1, "support"),
        ]
        for index in range(bedrooms):
            label = "Phòng ngủ master" if index == 0 else f"Phòng ngủ {index + 1}"
            items.append(RoomProgramItem("bedroom", label, 1, "private"))
        if wants_storage:
            items.append(RoomProgramItem("storage", "Kho/lưu trữ", 1, "storage"))
        if understanding.room_program_hints.get("laundry"):
            items.append(RoomProgramItem("laundry", "Giặt phơi", 1, "support"))
        notes = (
            pattern.stair_lightwell_position if pattern else "Use apartment renovation mode; no townhouse stair concept.",
            pattern.facade_strategy if pattern else "Interior concept follows selected style profile; external facade unchanged unless allowed.",
        )
        return ProgramPlan(items=tuple(items), selected_pattern=pattern, strategy_notes=notes, project_type=project_type)

    items: list[RoomProgramItem] = []
    if has_garage:
        items.append(RoomProgramItem("garage", "Chỗ đậu xe", 1, "user_fact"))
    if understanding.family_lifestyle.get("has_elders") and floors >= 2 and bedrooms > 0:
        items.append(RoomProgramItem("bedroom", "Phòng ngủ ông bà", 1, "private_elder_access"))
        bedrooms -= 1
    items.extend(
        [
            RoomProgramItem("living", "Phòng khách", 1, "core_public"),
            RoomProgramItem("stair_lightwell", "Thang + giếng trời", 1, "circulation_green_core"),
            RoomProgramItem("kitchen_dining", "Bếp và ăn", 1, "core_public"),
            RoomProgramItem("wc", "Vệ sinh", 1, "support"),
        ]
    )

    level_cycle = [floor for floor in range(2, floors + 1)] or [1]
    for index in range(bedrooms):
        floor = level_cycle[index % len(level_cycle)]
        label = "Phòng ngủ master" if index == 0 else f"Phòng ngủ {index + 1}"
        items.append(RoomProgramItem("bedroom", label, floor, "private"))

    if understanding.room_program_hints.get("prayer_room") or floors >= 3:
        items.append(RoomProgramItem("prayer", "Phòng thờ", floors, "family_culture"))
    if understanding.room_program_hints.get("laundry") or floors >= 3:
        items.append(RoomProgramItem("laundry", "Giặt phơi", floors, "support"))
    if style_id == "modern_tropical":
        items.append(RoomProgramItem("terrace_green", "Sân thượng xanh", floors, "greenery"))
    elif wants_storage or "low_maintenance" in priorities:
        items.append(RoomProgramItem("storage", "Kho/lưu trữ", floors, "low_maintenance"))

    notes = (
        pattern.stair_lightwell_position if pattern else "Use compact central stair/lightwell concept.",
        pattern.facade_strategy if pattern else "Facade strategy will follow selected style profile.",
    )
    return ProgramPlan(items=tuple(items), selected_pattern=pattern, strategy_notes=notes, project_type=project_type)
