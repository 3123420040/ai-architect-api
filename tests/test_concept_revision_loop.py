from __future__ import annotations

from app.services.design_intelligence.concept_model import seed_concept_model
from app.services.design_intelligence.concept_revision import apply_revision_operations
from app.services.design_intelligence.customer_understanding import parse_customer_understanding
from app.services.design_intelligence.drawing_package_model import compile_drawing_package
from app.services.design_intelligence.layout_generator import generate_concept_layout, validate_layout
from app.services.design_intelligence.revision_interpreter import parse_revision_feedback
from app.services.design_intelligence.style_inference import infer_style


def _layout(
    message: str = "Nha 7x25m, 3 tang, 4 phong ngu, co cho dau xe, thich hien dai thoang nhieu cay.",
    *,
    reference_images: list[dict] | None = None,
):
    understanding = parse_customer_understanding(
        message,
        reference_images=reference_images,
    )
    style = infer_style(understanding)
    concept = seed_concept_model(project_id="revision-test", understanding=understanding, style_inference=style)
    return generate_concept_layout(concept_model=concept, understanding=understanding, style_id=style.selected_style_id)


def _operation(interpretation, operation_type: str):
    return next(operation for operation in interpretation.operations if operation.type == operation_type)


def test_feedback_maps_to_resize_room_intent_operation_with_provenance():
    concept = _layout()
    interpretation = parse_revision_feedback("Phong khach rong hon mot chut", concept)

    assert interpretation.operations
    operation = _operation(interpretation, "resize_room_intent")
    assert operation.target_id
    assert operation.intent == "increase_area"
    assert operation.parameters["delta_m"] == 0.5
    assert operation.source == "homeowner_feedback"
    assert operation.confidence >= 0.8
    assert operation.explanation
    assert operation.requires_confirmation is False
    assert operation.affected_room_id == operation.target_id
    assert interpretation.needs_confirmation is False
    assert _operation(interpretation, "preserve_existing_requirement")


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
    assert result.preserved_parent_evidence["lot_dimensions"]["width_m"]["value"] == 7.0
    assert result.preserved_parent_evidence["lot_dimensions"]["depth_m"]["value"] == 25.0
    assert result.preserved_parent_evidence["selected_or_inferred_style"] == "modern_tropical"
    assert result.preserved_parent_evidence["assumptions"]


def test_kitchen_storage_feedback_changes_plan_and_keeps_original_requirements():
    concept = _layout("Nha pho 5x20m, 3 tang, 3 phong ngu, thich toi gian am, it bao tri va nhieu luu tru.")
    kitchen_before = next(room for room in concept.rooms if room.room_type == "kitchen_dining")
    secondary_before = next(room for room in concept.rooms if room.label_vi == "Phòng ngủ 3")
    storage_count_before = len([room for room in concept.rooms if room.room_type == "storage"])
    interpretation = parse_revision_feedback(
        "Make the kitchen/dining larger, reduce the secondary bedroom if needed, and add more storage near the entry and bedrooms.",
        concept,
    )
    result = apply_revision_operations(concept, interpretation.operations, parent_version_id="v1")
    kitchen_after = next(room for room in result.child_model.rooms if room.id == kitchen_before.id)
    secondary_after = next(room for room in result.child_model.rooms if room.id == secondary_before.id)
    package = compile_drawing_package(result.child_model)

    validate_layout(result.child_model)
    assert {operation.intent for operation in interpretation.operations} >= {"increase_kitchen_dining_area", "add_entry_and_bedroom_storage"}
    assert kitchen_after.area_m2.value > kitchen_before.area_m2.value
    assert secondary_after.area_m2.value < secondary_before.area_m2.value
    assert len([room for room in result.child_model.rooms if room.room_type == "storage"]) > storage_count_before
    assert result.child_model.site.width_m.value == 5.0
    assert result.child_model.site.depth_m.value == 20.0
    assert len(result.child_model.levels) == len(concept.levels)
    assert len([room for room in result.child_model.rooms if room.room_type == "bedroom"]) == 3
    assert "room_priorities.storage" in result.child_model.metadata["revision_summary"]["changed_fields"]
    assert package.qa_bounds["revision"]["parent_version_id"] == "v1"
    assert package.qa_bounds["revision"]["child_version_id"] == result.child_version_id
    assert any("Revision change:" in note for note in package.sheets_by_kind("assumptions_style_notes")[0].assumption_notes)


def test_style_revision_changes_style_fields_without_geometry_or_program_drift():
    concept = _layout(
        "Nha pho 5x20m, 4 tang, 4 phong ngu, 4 wc, hien dai nhiet doi, thoang va nhieu cay."
    )
    interpretation = parse_revision_feedback(
        "Change the style to minimal warm. Keep the same lot, number of floors, and room program. Make the facade calmer and warmer.",
        concept,
    )
    result = apply_revision_operations(concept, interpretation.operations, parent_version_id="tropical-v1")
    package = compile_drawing_package(result.child_model)

    validate_layout(result.child_model)
    assert _operation(interpretation, "change_style_direction").parameters["target_style_id"] == "minimal_warm"
    assert result.child_model.style.value == "minimal_warm"
    assert result.child_model.site.width_m.value == concept.site.width_m.value
    assert result.child_model.site.depth_m.value == concept.site.depth_m.value
    assert len(result.child_model.levels) == len(concept.levels)
    assert len([room for room in result.child_model.rooms if room.room_type == "bedroom"]) == len([room for room in concept.rooms if room.room_type == "bedroom"])
    assert result.child_model.metadata["preserved_requirements"]["selected_or_inferred_style"] == "modern_tropical"
    assert result.child_model.metadata["style_metadata"]["previous_style_id"] == "modern_tropical"
    assert result.child_model.metadata["style_metadata"]["style_id"] == "minimal_warm"
    assert "style.selected_style_id" in result.child_model.metadata["revision_summary"]["changed_fields"]
    assert package.style_provenance["revision_style_change"]["parameters"]["target_style_id"] == "minimal_warm"


def test_revision_parser_supports_common_homeowner_operations():
    concept = _layout()
    interpretation = parse_revision_feedback("Bep kin hon va them cay xanh o mat tien", concept)
    operation_types = {operation.type for operation in interpretation.operations}

    assert "adjust_room_priority" in operation_types
    assert "add_or_strengthen_style_feature" in operation_types
    assert "preserve_existing_requirement" in operation_types
    kitchen_operation = _operation(interpretation, "adjust_room_priority")
    assert kitchen_operation.parameters["open_kitchen"] is False
    assert kitchen_operation.affected_layout_intent == "kitchen_privacy"


def test_elder_bedroom_ground_floor_revision_preserves_7x25_modern_tropical_context():
    concept = _layout()
    interpretation = parse_revision_feedback("Chuyen phong ngu ong ba xuong tang 1", concept)
    operation = _operation(interpretation, "move_room_preference")
    result = apply_revision_operations(concept, interpretation.operations, parent_version_id="v1")

    assert operation.parameters["preferred_level_id"] == "L1"
    assert operation.parameters["preserve_total_bedrooms"] is True
    assert operation.source == "homeowner_feedback"
    assert result.child_model.site.width_m.value == 7.0
    assert result.child_model.site.depth_m.value == 25.0
    assert result.child_model.style.value == "modern_tropical"
    assert result.child_model.metadata["preserved_requirements"]["selected_or_inferred_style"] == "modern_tropical"
    assert result.child_model.metadata["room_move_preferences"][0]["intent"] == "move_elder_bedroom_to_ground_floor"
    assert len([room for room in result.child_model.rooms if room.room_type == "bedroom"]) == 4
    assert "not for construction" in result.child_model.concept_status_note.lower()


def test_less_glass_and_warmer_feedback_suppresses_glass_without_erasing_style():
    concept = _layout()
    interpretation = parse_revision_feedback("Khong thich qua nhieu kinh, giong hinh mau hon, am hon, it lanh", concept)
    operation_types = {operation.type for operation in interpretation.operations}
    result = apply_revision_operations(concept, interpretation.operations, parent_version_id="v1")

    assert "suppress_style_feature" in operation_types
    assert "add_or_strengthen_style_feature" in operation_types
    suppress = _operation(interpretation, "suppress_style_feature")
    assert suppress.parameters["feature"] == "glass"
    assert suppress.source == "homeowner_feedback"
    assert result.child_model.style.value == "modern_tropical"
    assert result.child_model.metadata["facade_glass_policy"] == "reduce_large_unshaded_glass"
    assert result.child_model.metadata["preserved_requirements"]["selected_or_inferred_style"] == "modern_tropical"


def test_apartment_indochine_reference_descriptors_adjust_style_without_townhouse_assumptions():
    descriptors = [
        {
            "style_hint": "indochine soft",
            "visual_tags": ["arched opening", "rattan", "pattern tile"],
            "materials": ["dark wood accent", "cream wall"],
            "spatial_features": ["built in storage"],
        }
    ]
    concept = _layout(
        "Can ho 95m2 cho gia dinh nho, thich am sang, co chat dong duong nhe va nhieu cho luu tru.",
        reference_images=descriptors,
    )
    interpretation = parse_revision_feedback(
        "Giong hinh mau hon, am hon, it lanh",
        concept,
        reference_image_descriptors=descriptors,
    )
    result = apply_revision_operations(concept, interpretation.operations, parent_version_id="v1")
    reference_operations = [operation for operation in interpretation.operations if operation.source == "reference_image_descriptor"]

    assert concept.style.value == "indochine_soft"
    assert reference_operations
    assert any(operation.parameters["feature"] == "warmer_palette" for operation in reference_operations)
    assert result.child_model.style.value == "indochine_soft"
    assert len(result.child_model.levels) == 1
    assert not result.child_model.stairs
    assert result.child_model.metadata["preserved_requirements"]["project_type"] == "apartment_renovation"
    assert result.child_model.metadata["style_metadata"]["reference_style_hints"]
    assert any("no real image analysis" in assumption.customer_visible_explanation for assumption in result.child_model.assumptions)
    assert not any("townhouse" in str(assumption.value).lower() for assumption in result.child_model.assumptions)


def test_unclear_revision_asks_plain_language_question_without_destructive_changes():
    concept = _layout()
    original_rooms = concept.rooms
    interpretation = parse_revision_feedback("Nhin chua on, sua cho dep hon", concept)
    result = apply_revision_operations(concept, interpretation.operations, parent_version_id="v1")
    operation_types = {operation.type for operation in interpretation.operations}

    assert interpretation.needs_confirmation is True
    assert "ask_clarifying_question" in operation_types
    assert "resize_room_intent" not in operation_types
    assert "move_room_preference" not in operation_types
    assert interpretation.confirmation_question
    assert "CAD" not in interpretation.confirmation_question
    assert result.child_model.rooms == original_rooms
    assert result.child_model.metadata["revision_clarifications"][0]["requires_confirmation"] is True


def test_unsafe_construction_permit_mep_feedback_is_blocked_as_concept_only():
    concept = _layout()
    interpretation = parse_revision_feedback("Lam luon ho so xin phep, ket cau va dien nuoc thi cong", concept)
    result = apply_revision_operations(concept, interpretation.operations, parent_version_id="v1")
    operation_types = {operation.type for operation in interpretation.operations}

    assert interpretation.needs_confirmation is True
    assert interpretation.blockers
    assert "ask_clarifying_question" in operation_types
    assert "resize_room_intent" not in operation_types
    assert "not for construction" in result.child_model.concept_status_note.lower()
    assert "xin phep" in result.child_model.metadata["revision_blockers"]
    assert "dien nuoc" in result.child_model.metadata["revision_blockers"]
    assert result.child_model.rooms == concept.rooms
