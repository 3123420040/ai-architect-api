from __future__ import annotations

from app.services.briefing import analyze_message_to_brief, build_clarification_state


def test_context_switch_resets_incompatible_brief_fields():
    existing = {
        "project_type": "villa",
        "project_mode": "new_build",
        "special_requests": ["garden"],
        "rooms": {"bedrooms": 5},
        "style": "modern",
    }

    result = analyze_message_to_brief(
        "Cải tạo căn hộ 95m2 theo phong cách hiện đại ấm, nhiều chỗ lưu trữ",
        existing,
    )

    assert result["brief_json"]["project_type"] == "apartment_reno"
    assert result["brief_json"]["project_mode"] == "renovation"
    assert result["brief_json"]["lot"]["area_m2"] == 95
    assert result["brief_json"].get("special_requests") is None
    assert result["conflicts"]


def test_material_and_color_do_not_false_match_from_bep_text():
    result = analyze_message_to_brief(
        "Có 4 phòng ngủ, 1 phòng khách, phòng bếp và phòng khách thiết kế nối liền",
        {"project_type": "apartment_reno"},
    )

    assert result["brief_json"].get("material_direction") is None
    assert result["brief_json"].get("color_direction") is None
    assert "Bếp và phòng khách liên thông" in (result["brief_json"].get("spatial_preferences") or [])


def test_apartment_clarification_state_uses_area_not_lot_dims():
    brief = {
        "project_type": "apartment_reno",
        "project_mode": "renovation",
        "lot": {"area_m2": 95},
        "rooms": {"bedrooms": 4, "bathrooms": 3},
        "renovation_scope": "full",
        "style": "modern",
        "budget_vnd": 7_000_000_000,
        "timeline_months": 2,
    }

    state = build_clarification_state(brief)

    site_section = next(section for section in state["sections"] if section["id"] == "site")
    program_section = next(section for section in state["sections"] if section["id"] == "program")

    assert site_section["status"] == "complete"
    assert program_section["status"] == "complete"
    assert state["readiness_label"] == "ready_for_confirmation"


def test_vietnamese_customer_sentence_extracts_critical_fields():
    sentence = (
        "Nha biet thu xay moi lo 7*25m huong Tay Nam, 3 tang, 4 phong ngu, "
        "3 WC, gara 1 o to, phong tho, 6 nguoi o gom ong ba va 2 tre nho, "
        "phong cach hien dai am xanh gan gui tu nhien, ngan sach khoang 7 ty, "
        "muon hoan thanh trong 8 thang, bat buoc nhieu anh sang thong gio va "
        "tranh khong gian bi."
    )

    result = analyze_message_to_brief(sentence)
    brief = result["brief_json"]

    assert brief["project_type"] == "villa"
    assert brief["project_mode"] == "new_build"
    assert brief["lot"]["width_m"] == 7
    assert brief["lot"]["depth_m"] == 25
    assert brief["lot"]["area_m2"] == 175
    assert brief["lot"]["orientation"] == "southwest"
    assert brief["floors"] == 3
    assert brief["rooms"]["bedrooms"] == 4
    assert brief["rooms"]["bathrooms"] == 3
    assert "garage" in brief["special_requests"]
    assert "prayer_room" in brief["special_requests"]
    assert brief["occupant_count"] == 6
    assert brief["budget_vnd"] == 7_000_000_000
    assert brief["timeline_months"] == 8
    assert "daylight_priority" in brief["lifestyle_priorities"]
    assert "ventilation_priority" in brief["lifestyle_priorities"]
    assert "Nhiều ánh sáng tự nhiên và thông gió" in brief["must_haves"]
    assert "Tránh không gian bí, tối" in brief["must_not_haves"]
