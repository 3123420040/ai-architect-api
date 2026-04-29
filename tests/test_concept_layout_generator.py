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


def _bounds(room):
    xs = [point[0] for point in room.polygon.value]
    ys = [point[1] for point in room.polygon.value]
    return min(xs), min(ys), max(xs), max(ys)


def _width(room) -> float:
    min_x, _, max_x, _ = _bounds(room)
    return max_x - min_x


def _y1(room) -> float:
    _, min_y, _, _ = _bounds(room)
    return min_y


def _y2(room) -> float:
    _, _, _, max_y = _bounds(room)
    return max_y


def _assert_fixtures_fit_rooms(layout) -> None:
    rooms = {room.id: room for room in layout.rooms}
    for fixture in layout.fixtures:
        if not fixture.room_id:
            continue
        room = rooms[fixture.room_id]
        min_x, min_y, max_x, max_y = _bounds(room)
        center_x, center_y = fixture.position.value
        size_x, size_y = fixture.dimensions_m.value
        assert min_x <= center_x - size_x / 2 <= center_x + size_x / 2 <= max_x
        assert min_y <= center_y - size_y / 2 <= center_y + size_y / 2 <= max_y


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
    assert any(room.room_type == "bedroom" and room.level_id == "L1" for room in layout.rooms)
    assert max(room.area_m2.value for room in layout.rooms if room.room_type == "bedroom") <= 30
    assert all(_width(room) < layout.site.width_m.value for room in layout.rooms if room.room_type in {"stair_lightwell", "wc"})
    assert not any(opening.opening_type == "door" and opening.level_id != "L1" for opening in layout.openings)
    _assert_fixtures_fit_rooms(layout)
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
    assert all(room.area_m2.value < 8 for room in layout.rooms if room.room_type in {"wc", "storage", "stair_lightwell"})
    assert all(_width(room) <= 1.6 for room in layout.rooms if room.room_type == "stair_lightwell")
    _assert_fixtures_fit_rooms(layout)
    assert all(room.polygon.assumption for room in layout.rooms)
    assert all(room.area_m2.value > 0 for room in layout.rooms)


def test_low_communication_5x20_uses_conservative_defaults_with_provenance():
    understanding, style, concept = _seed_from_text(
        "Need a 5x20 family house, simple, bright, enough bedrooms, not too expensive."
    )
    layout = generate_concept_layout(concept_model=concept, understanding=understanding, style_id=style.selected_style_id)

    validate_layout(layout)
    assert len(layout.levels) == 3
    assert len([room for room in layout.rooms if room.room_type == "bedroom"]) == 3
    assert len([room for room in layout.rooms if room.room_type == "wc"]) == 3
    assert max(room.area_m2.value for room in layout.rooms if room.room_type == "kitchen_dining") <= 24
    assert any("Assume 3 concept floors" in assumption.value and assumption.needs_confirmation for assumption in layout.assumptions)
    assert all(room.polygon.assumption for room in layout.rooms)


def test_elder_townhouse_stacks_wet_core_and_keeps_ground_bedroom_accessible():
    understanding, style, concept = _seed_from_text(
        "Nha pho 5x20m, 4 tang, 4 phong ngu, 4 wc, co ong ba, phong ngu tang tret, "
        "hien dai nhiet doi, thoang va nhieu anh sang."
    )
    layout = generate_concept_layout(concept_model=concept, understanding=understanding, style_id=style.selected_style_id)

    validate_layout(layout)
    elder_room = next(room for room in layout.rooms if room.label_vi == "Phòng ngủ ông bà")
    wc_rooms = [room for room in layout.rooms if room.room_type == "wc"]
    base_x1, _, base_x2, _ = _bounds(next(room for room in wc_rooms if room.level_id == "L1"))

    assert elder_room.level_id == "L1"
    assert len(wc_rooms) == 4
    assert all(min(base_x2, _bounds(room)[2]) - max(base_x1, _bounds(room)[0]) >= 0.45 for room in wc_rooms)
    assert all(2.0 <= room.area_m2.value <= 8.0 for room in wc_rooms)
    assert max(room.area_m2.value for room in layout.rooms if room.room_type == "kitchen_dining") <= 24


def test_garage_garden_townhouse_has_green_buffer_and_bounded_room_sizes():
    understanding, style, concept = _seed_from_text(
        "Nha 7x25m, 3 tang, 4 phong ngu, 4 WC, co gara, san vuon, nhieu cay, hien dai nhiet doi."
    )
    layout = generate_concept_layout(concept_model=concept, understanding=understanding, style_id=style.selected_style_id)

    validate_layout(layout)
    assert any(room.room_type == "garage" and room.level_id == "L1" for room in layout.rooms)
    assert any(room.room_type == "garden" and room.level_id == "L1" for room in layout.rooms)
    assert len([room for room in layout.rooms if room.room_type == "wc"]) == 4
    assert max(room.area_m2.value for room in layout.rooms if room.room_type == "kitchen_dining") <= 36
    assert max(room.area_m2.value for room in layout.rooms if room.room_type == "bedroom") <= 30
    assert any(fixture.fixture_type == "plant" and fixture.label_vi == "Mảng xanh" for fixture in layout.fixtures)


def test_work_from_home_apartment_adds_separated_work_and_storage_zones():
    understanding, style, concept = _seed_from_text(
        "Can ho 95m2, 2 phong ngu, 2 wc, toi gian am, lam viec tai nha, nhieu luu tru."
    )
    layout = generate_concept_layout(concept_model=concept, understanding=understanding, style_id=style.selected_style_id)

    validate_layout(layout)
    work = next(room for room in layout.rooms if room.room_type == "work")
    storage = next(room for room in layout.rooms if room.room_type == "storage")

    assert len(layout.levels) == 1
    assert layout.stairs == ()
    assert 4.0 <= work.area_m2.value <= 8.0
    assert storage.area_m2.value >= 2.0
    assert any(fixture.fixture_type == "desk" and fixture.room_id == work.id for fixture in layout.fixtures)


def test_compact_studio_uses_flexible_sleeping_zone_without_fake_bedrooms():
    understanding, style, concept = _seed_from_text(
        "Can ho studio 35m2, toi gian am, linh hoat, nhieu luu tru, tranh bua bo."
    )
    layout = generate_concept_layout(concept_model=concept, understanding=understanding, style_id=style.selected_style_id)

    validate_layout(layout)
    assert len(layout.levels) == 1
    assert not any(room.room_type == "bedroom" for room in layout.rooms)
    assert any(room.room_type == "flex_sleep" for room in layout.rooms)
    assert any(room.room_type == "storage" for room in layout.rooms)
    assert any(fixture.fixture_type == "convertible_bed" for fixture in layout.fixtures)
    assert sum(room.area_m2.value for room in layout.rooms) <= layout.site.area_m2.value


def test_shophouse_places_front_business_before_private_family_zone():
    understanding, style, concept = _seed_from_text(
        "Nha pho shophouse 5x25m, 3 tang, 3 phong ngu, kinh doanh phia truoc, "
        "rieng tu gia dinh, co kho."
    )
    layout = generate_concept_layout(concept_model=concept, understanding=understanding, style_id=style.selected_style_id)

    validate_layout(layout)
    business = next(room for room in layout.rooms if room.room_type == "business")
    living = next(room for room in layout.rooms if room.room_type == "living" and room.level_id == "L1")

    assert business.level_id == "L1"
    assert _y2(business) <= _y1(living)
    assert any(room.room_type == "storage" and room.level_id == "L1" for room in layout.rooms)
    assert any("business/service area as concept zoning" in assumption.value for assumption in layout.assumptions)


def test_apartment_indochine_descriptor_layout_remains_valid():
    understanding = parse_customer_understanding(
        "Can ho 95m2 cho gia dinh nho, thich am sang, co chat dong duong nhe va nhieu cho luu tru.",
        reference_images=[
            {
                "style_hint": "indochine soft",
                "visual_tags": ["arched opening", "rattan", "pattern tile"],
                "materials": ["dark wood accent", "cream wall"],
            }
        ],
    )
    style = infer_style(understanding)
    concept = seed_concept_model(project_id="layout-test", understanding=understanding, style_inference=style)
    layout = generate_concept_layout(concept_model=concept, understanding=understanding, style_id=style.selected_style_id)

    validate_layout(layout)
    assert style.selected_style_id == "indochine_soft"
    assert len(layout.levels) == 1
    assert layout.stairs == ()
    assert any(room.room_type == "storage" for room in layout.rooms)
    assert all(room.level_id == "L1" for room in layout.rooms)
    assert any("apartment rectangle" in assumption.value for assumption in layout.assumptions)
    _assert_fixtures_fit_rooms(layout)


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
