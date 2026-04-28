from __future__ import annotations

import pytest

from app.services.design_intelligence.concept_model import (
    ArchitecturalConceptModel,
    ConceptModelValidationError,
    seed_concept_model,
    validate_concept_model,
)
from app.services.design_intelligence.customer_understanding import parse_customer_understanding
from app.services.design_intelligence.provenance import DecisionValue, ProvenanceError, rule_default
from app.services.design_intelligence.style_inference import infer_style


def test_decision_value_validates_source_confidence_and_explanation():
    decision = DecisionValue(
        value=4.0,
        source="rule_default",
        confidence=0.8,
        assumption=True,
        customer_visible_explanation="Chừa sân trước 4m để có chỗ đậu xe concept.",
        needs_confirmation=True,
    )

    assert decision.as_dict()["source"] == "rule_default"
    assert decision.as_dict()["assumption"] is True
    with pytest.raises(ProvenanceError):
        DecisionValue(value=1, source="engineering_claim", confidence=0.5, assumption=True, customer_visible_explanation="x")
    with pytest.raises(ProvenanceError):
        DecisionValue(value=1, source="rule_default", confidence=1.2, assumption=True, customer_visible_explanation="x")


def test_seed_concept_model_contains_required_sections_and_provenance():
    understanding = parse_customer_understanding(
        "Nha 7x25m, 3 tang, 4 phong ngu, co cho dau xe, thich hien dai thoang nhieu cay."
    )
    model = seed_concept_model(project_id="concept-test", understanding=understanding, style_inference=infer_style(understanding))

    assert isinstance(model, ArchitecturalConceptModel)
    assert model.site.width_m.value == 7
    assert model.site.width_m.source == "user_fact"
    assert model.site.boundary.assumption is True
    assert model.buildable_area.polygon.assumption is True
    assert len(model.levels) == 3
    assert model.levels[0].floor_to_floor_height_m.source == "rule_default"
    assert model.style and model.style.value == "modern_tropical"
    assert model.style.source == "ai_proposal"
    assert model.facade
    assert model.rooms == ()
    assert model.walls == ()
    assert model.openings == ()
    assert model.stairs == ()
    assert model.fixtures == ()
    assert model.section_lines == ()
    assert any(assumption.assumption for assumption in model.assumptions)


def test_missing_critical_site_data_blocks_concept_seed():
    understanding = parse_customer_understanding("Gia dinh 4 nguoi thich nha am va de o.")

    with pytest.raises(ConceptModelValidationError):
        seed_concept_model(project_id="missing-site", understanding=understanding, style_inference=infer_style(understanding))


def test_assumed_site_boundary_requires_visible_assumption():
    understanding = parse_customer_understanding("Nha 5x20m, 3 tang, thich toi gian am.")
    model = seed_concept_model(project_id="assumption-test", understanding=understanding, style_inference=infer_style(understanding))
    invalid = ArchitecturalConceptModel(
        project_id=model.project_id,
        source_brief=model.source_brief,
        concept_status_note=model.concept_status_note,
        site=model.site,
        buildable_area=model.buildable_area,
        levels=model.levels,
        style=model.style,
        facade=model.facade,
        assumptions=(),
    )

    with pytest.raises(ConceptModelValidationError):
        validate_concept_model(invalid)


def test_rule_default_values_are_assumptions_and_can_need_confirmation():
    decision = rule_default(3.3, "Chiều cao tầng concept lấy mặc định.", needs_confirmation=True)

    assert decision.assumption is True
    assert decision.source == "rule_default"
    assert decision.needs_confirmation is True
