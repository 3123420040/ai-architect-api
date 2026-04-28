from __future__ import annotations

from app.services.design_intelligence.concept_model import seed_concept_model
from app.services.design_intelligence.customer_understanding import parse_customer_understanding
from app.services.design_intelligence.layout_generator import generate_concept_layout, validate_layout
from app.services.design_intelligence.program_planner import plan_room_program
from app.services.design_intelligence.style_inference import infer_style
from app.services.design_intelligence.technical_defaults import resolve_technical_defaults


def _seed_from_text(text: str):
    understanding = parse_customer_understanding(text)
    style = infer_style(understanding)
    return understanding, style, seed_concept_model(project_id="layout-test", understanding=understanding, style_inference=style)


def test_7x25_three_floor_modern_tropical_layout_is_valid():
    understanding, style, concept = _seed_from_text(
        "Nha 7x25m, 3 tang, 4 phong ngu, co cho dau xe, thich hien dai thoang nhieu cay, "
        "gia dinh 6 nguoi co ong ba va tre nho."
    )
    layout = generate_concept_layout(concept_model=concept, understanding=understanding, style_id=style.selected_style_id)

    validate_layout(layout)
    assert style.selected_style_id == "modern_tropical"
    assert len([room for room in layout.rooms if room.room_type == "bedroom"]) == 4
    assert any(room.room_type == "garage" for room in layout.rooms)
    assert any(room.room_type == "stair_lightwell" for room in layout.rooms)
    assert any(room.room_type == "terrace_green" for room in layout.rooms)
    assert layout.walls
    assert layout.openings
    assert layout.stairs
    assert layout.fixtures
    assert layout.section_lines
    assert all(wall.thickness_m.assumption for wall in layout.walls)
    assert all(opening.width_m.source in {"style_profile", "ai_proposal"} for opening in layout.openings)


def test_minimal_warm_5x20_low_maintenance_layout_is_valid():
    understanding, style, concept = _seed_from_text(
        "Nha pho 5x20m, 3 tang, 3 phong ngu, thich toi gian am, it bao tri va nhieu luu tru."
    )
    layout = generate_concept_layout(concept_model=concept, understanding=understanding, style_id=style.selected_style_id)

    validate_layout(layout)
    assert style.selected_style_id == "minimal_warm"
    assert len([room for room in layout.rooms if room.room_type == "bedroom"]) == 3
    assert any(room.room_type == "storage" for room in layout.rooms)
    assert all(room.polygon.assumption for room in layout.rooms)
    assert all(room.area_m2.value > 0 for room in layout.rooms)


def test_room_program_retrieves_pattern_for_sparse_7x25_facts():
    understanding, style, concept = _seed_from_text(
        "Nha 7x25m, 3 tang, 4 phong ngu, co cho dau xe, thich hien dai thoang nhieu cay."
    )
    plan = plan_room_program(understanding=understanding, concept_model=concept, style_id=style.selected_style_id or "modern_tropical")

    assert plan.selected_pattern
    assert plan.selected_pattern.pattern_id == "townhouse_villa_7x25_green_core"
    assert "central stair" in plan.strategy_notes[0]


def test_technical_defaults_are_style_derived_not_customer_questions():
    defaults = resolve_technical_defaults("modern_tropical")

    assert defaults.exterior_wall_thickness_m.source == "style_profile"
    assert defaults.exterior_wall_thickness_m.assumption is True
    assert defaults.window_width_m.value >= 1.4
    assert defaults.stair_width_m.value > 0
    assert "CAD" not in defaults.exterior_wall_thickness_m.customer_visible_explanation
