from __future__ import annotations

from app.services.design_intelligence.concept_model import seed_concept_model
from app.services.design_intelligence.concept_revision import apply_revision_operations
from app.services.design_intelligence.customer_understanding import parse_customer_understanding
from app.services.design_intelligence.layout_generator import generate_concept_layout, validate_layout
from app.services.design_intelligence.revision_interpreter import parse_revision_feedback
from app.services.design_intelligence.style_inference import infer_style


def _layout():
    understanding = parse_customer_understanding(
        "Nha 7x25m, 3 tang, 4 phong ngu, co cho dau xe, thich hien dai thoang nhieu cay."
    )
    style = infer_style(understanding)
    concept = seed_concept_model(project_id="revision-test", understanding=understanding, style_inference=style)
    return generate_concept_layout(concept_model=concept, understanding=understanding, style_id=style.selected_style_id)


def test_feedback_maps_to_resize_room_operation():
    concept = _layout()
    interpretation = parse_revision_feedback("Phong khach rong hon mot chut", concept)

    assert interpretation.operations
    operation = interpretation.operations[0]
    assert operation.type == "resize_room"
    assert operation.target_id
    assert operation.intent == "increase_area"
    assert operation.parameters["delta_m"] == 0.5
    assert interpretation.needs_confirmation is False


def test_revision_application_creates_child_version_and_changelog():
    concept = _layout()
    living_before = next(room for room in concept.rooms if room.room_type == "living")
    operations = parse_revision_feedback("Phong khach rong hon", concept).operations
    result = apply_revision_operations(concept, operations, parent_version_id="v1")
    living_after = next(room for room in result.child_model.rooms if room.id == living_before.id)

    validate_layout(result.child_model)
    assert result.parent_version_id == "v1"
    assert result.child_version_id != "v1"
    assert result.child_model.metadata["parent_version_id"] == "v1"
    assert result.changelog
    assert living_after.area_m2.value > living_before.area_m2.value
    assert living_before.area_m2.source == "ai_proposal"
    assert living_after.area_m2.source == "reviewer_override"
    assert result.parent_model.rooms == concept.rooms
    assert result.preserved_parent_evidence["source_brief"] == concept.source_brief
    assert result.preserved_parent_evidence["assumptions"]


def test_revision_parser_supports_common_homeowner_operations():
    concept = _layout()
    interpretation = parse_revision_feedback("Bep mo hon va them cay xanh o mat tien", concept)
    operation_types = {operation.type for operation in interpretation.operations}

    assert "switch_kitchen_open_closed" in operation_types
    assert "adjust_greenery" in operation_types
    assert "change_facade_emphasis" in operation_types


def test_unclear_revision_asks_plain_language_question():
    concept = _layout()
    interpretation = parse_revision_feedback("Chinh lai cho dep hon", concept)

    assert interpretation.needs_confirmation is True
    assert not interpretation.operations
    assert interpretation.confirmation_question
    assert "CAD" not in interpretation.confirmation_question
