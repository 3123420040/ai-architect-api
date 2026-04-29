from __future__ import annotations

import pytest

from app.services.design_intelligence.customer_understanding import parse_customer_understanding
from app.services.design_intelligence.provenance import (
    DecisionValue,
    ProvenanceError,
    ai_proposal,
    pattern_memory,
    reference_image,
    style_profile,
)
from app.services.design_intelligence.style_inference import infer_style


def test_sparse_vietnamese_brief_infers_facts_and_modern_tropical_style():
    understanding = parse_customer_understanding(
        "Nha 7x25m, 3 tang, 4 phong ngu, co cho dau xe, thich hien dai thoang nhieu cay, "
        "gia dinh 6 nguoi co ong ba va tre nho."
    )
    result = infer_style(understanding)

    assert understanding.site_facts["width_m"] == 7
    assert understanding.site_facts["depth_m"] == 25
    assert understanding.site_facts["shape"] == "assumed_rectangle"
    assert understanding.project_type == "townhouse"
    assert understanding.site_facts["project_type_source"] == "inferred_from_lot_dimensions"
    assert understanding.room_program_hints["floors"] == 3
    assert understanding.room_program_hints["bedrooms"] == 4
    assert understanding.room_program_hints["garage"] is True
    assert understanding.family_lifestyle["occupant_count"] == 6
    assert understanding.family_lifestyle["has_elders"] is True
    assert understanding.family_lifestyle["has_children"] is True
    assert not understanding.missing_blockers
    assert "Assume rectangular lot" in understanding.assumptions[0]
    assert result.selected_style_id == "modern_tropical"
    assert result.needs_confirmation is False
    assert result.candidates[0].confidence >= 0.75
    assert any(item.source == "customer_language" for item in result.candidates[0].source_evidence)


def test_5x20_minimal_warm_low_maintenance_brief_extracts_program_and_style():
    understanding = parse_customer_understanding(
        "Nha pho 5x20m, 3 tang, 3 phong ngu, thich toi gian am, it bao tri, de don va nhieu luu tru."
    )
    result = infer_style(understanding)

    assert understanding.site_facts["width_m"] == 5
    assert understanding.site_facts["depth_m"] == 20
    assert understanding.project_type == "townhouse"
    assert understanding.room_program_hints["floors"] == 3
    assert understanding.room_program_hints["bedrooms"] == 3
    assert understanding.room_program_hints["storage"] is True
    assert "low_maintenance" in understanding.family_lifestyle["priorities"]
    assert "storage" in understanding.family_lifestyle["priorities"]
    assert result.selected_style_id == "minimal_warm"
    assert result.needs_confirmation is False
    assert result.candidates[0].confidence >= 0.75


def test_reference_image_descriptors_influence_style_score():
    understanding = parse_customer_understanding(
        "Can ho 95m2 cho gia dinh nho, thich nha am va co chut chat rieng.",
        reference_images=[
            {
                "style_hint": "soft indochine",
                "visual_tags": ["arched opening", "rattan", "pattern tile"],
                "materials": ["dark wood accent", "cream wall"],
            }
        ],
    )
    result = infer_style(understanding)

    assert understanding.site_facts["project_type"] == "apartment_renovation"
    assert understanding.project_type == "apartment_renovation"
    assert any("apartment rectangle" in item for item in understanding.assumptions)
    assert understanding.image_signals
    assert result.selected_style_id == "indochine_soft"
    assert result.candidates[0].evidence
    assert any(item.source == "reference_image_descriptor" for item in result.candidates[0].source_evidence)


def test_image_descriptors_do_not_override_explicit_customer_dislike():
    understanding = parse_customer_understanding(
        "Can ho 95m2, thich gon am va khong thich dong duong.",
        reference_images=[
            {
                "style_hint": "indochine soft",
                "visual_tags": ["arched opening", "rattan", "pattern tile"],
            }
        ],
    )
    result = infer_style(understanding)

    assert result.candidates[0].style_id != "indochine_soft"
    indochine = next(candidate for candidate in result.candidates if candidate.style_id == "indochine_soft")
    assert indochine.confidence == 0
    assert any(item.startswith("explicit_dislike:") for item in indochine.evidence)


def test_low_confidence_returns_friendly_nontechnical_question():
    understanding = parse_customer_understanding("Nha cho gia dinh tre, muon dep va de o.")
    result = infer_style(understanding)

    assert result.selected_style_id is None
    assert result.needs_confirmation is True
    assert result.confirmation_question
    forbidden = ("wall", "cad", "mep", "sill", "layer", "thickness", "kết cấu", "thi công")
    assert not any(term in result.confirmation_question.lower() for term in forbidden)


def test_provenance_helpers_keep_complete_ai_default_contract():
    decisions = (
        reference_image("arched opening", "Ảnh tham khảo có vòm nhẹ."),
        style_profile(1.2, "minimal_warm", "Cửa sổ concept lấy theo mặc định style."),
        pattern_memory("center stair", "townhouse_5x20_lightwell", "Gợi ý thang giữa từ mẫu nhà phố tương tự."),
        ai_proposal("minimal_warm", "Phong cách được suy luận từ mô tả khách hàng.", confidence=0.78),
    )

    for decision in decisions:
        payload = decision.as_dict()
        assert payload["source"]
        assert 0 <= payload["confidence"] <= 1
        assert payload["assumption"] is True
        assert payload["customer_visible_explanation"]
        assert isinstance(payload["needs_confirmation"], bool)

    with pytest.raises(ProvenanceError):
        DecisionValue(
            value="minimal_warm",
            source="ai_proposal",
            confidence=0.8,
            assumption=False,
            customer_visible_explanation="AI-filled values must stay visible as assumptions.",
        )
