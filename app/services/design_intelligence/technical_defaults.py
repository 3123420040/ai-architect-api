from __future__ import annotations

from dataclasses import dataclass

from app.services.design_intelligence.provenance import DecisionValue
from app.services.professional_deliverables.style_knowledge import StyleKnowledgeBase


@dataclass(frozen=True)
class TechnicalDefaults:
    style_id: str
    exterior_wall_thickness_m: DecisionValue
    interior_wall_thickness_m: DecisionValue
    main_door_width_m: DecisionValue
    internal_door_width_m: DecisionValue
    window_width_m: DecisionValue
    window_height_m: DecisionValue
    window_sill_height_m: DecisionValue
    stair_width_m: DecisionValue
    stair_run_m: DecisionValue
    floor_to_floor_height_m: DecisionValue
    clear_height_m: DecisionValue
    lightwell_min_width_m: DecisionValue


def resolve_technical_defaults(style_id: str, *, knowledge_base: StyleKnowledgeBase | None = None) -> TechnicalDefaults:
    kb = knowledge_base or StyleKnowledgeBase.load_default()
    profile = kb.get(style_id)
    opening = profile.opening_rules
    is_tropical = style_id == "modern_tropical"
    is_minimal = style_id == "minimal_warm"
    return TechnicalDefaults(
        style_id=style_id,
        exterior_wall_thickness_m=_style_default(0.2, style_id, "Tường bao concept lấy 200mm theo mặc định style/rule."),
        interior_wall_thickness_m=_style_default(0.12, style_id, "Tường ngăn concept lấy 120mm theo mặc định style/rule."),
        main_door_width_m=_style_default(1.2, style_id, "Cửa chính concept lấy 1.2m để mặt bằng dễ đọc."),
        internal_door_width_m=_style_default(0.9, style_id, "Cửa phòng concept lấy 0.9m theo mặc định."),
        window_width_m=_style_default(1.6 if is_tropical else 1.2, style_id, f"Cửa sổ concept theo nguyên tắc mở {opening.get('window_to_wall_ratio', 'moderate')}."),
        window_height_m=_style_default(1.4 if is_tropical else 1.2, style_id, "Chiều cao cửa sổ concept lấy theo hướng style."),
        window_sill_height_m=_style_default(0.85 if is_tropical else 0.9, style_id, "Cao độ bệ cửa concept lấy theo mặc định dân dụng."),
        stair_width_m=_style_default(1.05 if not is_minimal else 1.0, style_id, "Bề rộng thang concept lấy mặc định phù hợp nhà phố."),
        stair_run_m=_style_default(4.2, style_id, "Chiều dài vế thang concept lấy theo module sơ bộ."),
        floor_to_floor_height_m=_style_default(3.3, style_id, "Chiều cao tầng concept giữ 3.3m để dựng sơ đồ."),
        clear_height_m=_style_default(3.0, style_id, "Chiều cao thông thủy concept giữ 3.0m."),
        lightwell_min_width_m=_style_default(1.4 if is_tropical else 1.0, style_id, "Giếng trời/sân trong concept lấy từ định hướng style."),
    )


def _style_default(value: float, style_id: str, explanation: str) -> DecisionValue:
    return DecisionValue(
        value=value,
        source="style_profile",
        confidence=0.72,
        assumption=True,
        customer_visible_explanation=f"{explanation} Nguồn: {style_id}.",
        needs_confirmation=False,
    )
