from __future__ import annotations

from pathlib import Path

from app.services.design_intelligence.concept_drawing_qa import concept_qa_passed, validate_drawing_package_model, validate_physical_sheet_presence
from app.services.design_intelligence.concept_model import seed_concept_model
from app.services.design_intelligence.concept_revision import apply_revision_operations
from app.services.design_intelligence.customer_understanding import parse_customer_understanding
from app.services.design_intelligence.layout_generator import generate_concept_layout, validate_layout
from app.services.design_intelligence.revision_interpreter import parse_revision_feedback
from app.services.design_intelligence.style_inference import infer_style
from app.services.professional_deliverables.concept_pdf_generator import render_concept_2d_package


def _run_concept_workflow(message: str, tmp_path: Path, *, reference_images: list[dict] | None = None):
    understanding = parse_customer_understanding(message, reference_images=reference_images)
    style = infer_style(understanding)
    concept = seed_concept_model(project_id="e2e-concept", understanding=understanding, style_inference=style)
    layout = generate_concept_layout(concept_model=concept, understanding=understanding, style_id=style.selected_style_id)
    render = render_concept_2d_package(layout, tmp_path, project_name="AI Concept E2E", require_dwg=False)
    package_gates = validate_drawing_package_model(render.drawing_package, layout)
    return understanding, style, layout, render, package_gates


def test_e2e_7x25_modern_tropical_garage_package(tmp_path: Path):
    understanding, style, layout, render, package_gates = _run_concept_workflow(
        "Nha 7x25m, 3 tang, 4 phong ngu, co cho dau xe, thich hien dai thoang nhieu cay, "
        "gia dinh 6 nguoi co ong ba va tre nho.",
        tmp_path,
    )

    validate_layout(layout)
    assert style.selected_style_id == "modern_tropical"
    assert understanding.room_program_hints["garage"] is True
    assert len([room for room in layout.rooms if room.room_type == "bedroom"]) == 4
    assert render.bundle.passed
    assert concept_qa_passed(package_gates)
    assert concept_qa_passed(validate_physical_sheet_presence(render.drawing_package, render.bundle))
    assert "not for construction" in layout.concept_status_note.lower()


def test_e2e_5x20_minimal_warm_low_maintenance_package(tmp_path: Path):
    understanding, style, layout, render, package_gates = _run_concept_workflow(
        "Nha pho 5x20m, 3 tang, 3 phong ngu, thich toi gian am, it bao tri, de don va nhieu luu tru.",
        tmp_path,
    )

    assert style.selected_style_id == "minimal_warm"
    assert "low_maintenance" in understanding.family_lifestyle["priorities"]
    assert any(room.room_type == "storage" for room in layout.rooms)
    assert render.bundle.passed
    assert concept_qa_passed(package_gates)
    assert concept_qa_passed(validate_physical_sheet_presence(render.drawing_package, render.bundle))


def test_e2e_apartment_indochine_reference_image_package(tmp_path: Path):
    understanding, style, layout, render, package_gates = _run_concept_workflow(
        "Can ho 95m2 cho gia dinh nho, thich am sang, co chat dong duong nhe va nhieu cho luu tru.",
        tmp_path,
        reference_images=[
            {
                "style_hint": "indochine soft",
                "visual_tags": ["arched opening", "rattan", "pattern tile"],
                "materials": ["dark wood accent", "cream wall"],
            }
        ],
    )

    assert understanding.site_facts["project_type"] == "apartment_renovation"
    assert style.selected_style_id == "indochine_soft"
    assert layout.site.width_m.assumption is True
    assert any("apartment rectangle" in assumption.value for assumption in layout.assumptions)
    assert len(layout.levels) == 1
    assert render.bundle.passed
    assert concept_qa_passed(package_gates)
    assert concept_qa_passed(validate_physical_sheet_presence(render.drawing_package, render.bundle))


def test_e2e_revision_loop_regenerates_child_package(tmp_path: Path):
    _understanding, _style, layout, _render, _package_gates = _run_concept_workflow(
        "Nha 7x25m, 3 tang, 4 phong ngu, co cho dau xe, thich hien dai thoang nhieu cay.",
        tmp_path / "parent",
    )
    living_before = next(room for room in layout.rooms if room.room_type == "living")
    interpretation = parse_revision_feedback("Phong khach rong hon", layout)
    revision = apply_revision_operations(layout, interpretation.operations, parent_version_id="parent-v1")
    child_render = render_concept_2d_package(revision.child_model, tmp_path / "child", project_name="AI Concept E2E Revision", require_dwg=False)
    living_after = next(room for room in revision.child_model.rooms if room.id == living_before.id)

    assert revision.child_version_id != revision.parent_version_id
    assert revision.changelog
    assert living_after.area_m2.value > living_before.area_m2.value
    assert child_render.bundle.passed
    assert child_render.drawing_project.lot_width_m == layout.site.width_m.value
    assert child_render.drawing_project.lot_depth_m == layout.site.depth_m.value
    assert concept_qa_passed(validate_physical_sheet_presence(child_render.drawing_package, child_render.bundle))
