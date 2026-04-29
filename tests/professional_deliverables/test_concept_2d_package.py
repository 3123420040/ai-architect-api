from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import fitz
import ezdxf

from app.services.design_intelligence.concept_drawing_qa import (
    concept_qa_passed,
    validate_drawing_package_model,
    validate_physical_sheet_presence,
    validate_rendered_concept_bundle,
)
from app.services.design_intelligence.concept_model import seed_concept_model
from app.services.design_intelligence.product_concept_adapter import adapt_live_design_version_to_concept_source
from app.services.design_intelligence.customer_understanding import parse_customer_understanding
from app.services.design_intelligence.layout_generator import generate_concept_layout
from app.services.design_intelligence.style_inference import infer_style
from app.services.geometry import build_geometry_v2
from app.services.professional_deliverables.concept_pdf_generator import render_concept_2d_package
from tests.test_flows import complete_brief_payload


def _concept_layout():
    understanding = parse_customer_understanding(
        "Nha 7x25m, 3 tang, 4 phong ngu, co cho dau xe, thich hien dai thoang nhieu cay, "
        "gia dinh 6 nguoi co ong ba va tre nho."
    )
    style = infer_style(understanding)
    concept = seed_concept_model(project_id="concept-2d-test", understanding=understanding, style_inference=style)
    return generate_concept_layout(concept_model=concept, understanding=understanding, style_id=style.selected_style_id)


def _render_from_message(message: str, tmp_path: Path, *, reference_images: list[dict] | None = None):
    understanding = parse_customer_understanding(message, reference_images=reference_images)
    style = infer_style(understanding)
    concept = seed_concept_model(project_id=f"style-{abs(hash(message))}", understanding=understanding, style_inference=style)
    layout = generate_concept_layout(concept_model=concept, understanding=understanding, style_id=style.selected_style_id)
    render = render_concept_2d_package(layout, tmp_path, project_name="Style Concept", require_dwg=False)
    return understanding, style, layout, render, _pdf_text(render.bundle.pdf_path)


def _pdf_text(path: Path) -> str:
    with fitz.open(path) as doc:
        return "\n".join(page.get_text("text") for page in doc)


def test_drawing_package_model_contains_required_concept_sheets_schedules_and_assumptions(tmp_path: Path):
    concept = _concept_layout()
    result = render_concept_2d_package(concept, tmp_path, project_name="Nhà phố concept", require_dwg=False)
    package = result.drawing_package
    gates = validate_drawing_package_model(package, concept)

    assert concept_qa_passed(gates)
    assert {
        "cover_index",
        "site",
        "floorplan",
        "elevations",
        "sections",
        "room_area_schedule",
        "door_window_schedule",
        "assumptions_style_notes",
    } <= {sheet.kind for sheet in package.sheets}
    assert package.qa_bounds["lot_width_m"] == 7
    assert package.qa_bounds["lot_depth_m"] == 25
    assert package.qa_bounds["sheet_count"] == len(package.sheets)
    room_schedule_sheet = package.sheets_by_kind("room_area_schedule")[0]
    opening_schedule_sheet = package.sheets_by_kind("door_window_schedule")[0]
    notes_sheet = package.sheets_by_kind("assumptions_style_notes")[0]
    assert any(schedule.schedule_type == "room_area" for schedule in room_schedule_sheet.schedules)
    assert any(schedule.schedule_type == "door_window" for schedule in opening_schedule_sheet.schedules)
    assert any(schedule.schedule_type == "assumptions" for schedule in notes_sheet.schedules)
    assert notes_sheet.assumption_notes
    assert notes_sheet.style_notes


def test_concept_pdf_and_dxf_render_from_source_geometry(tmp_path: Path):
    concept = _concept_layout()
    result = render_concept_2d_package(concept, tmp_path, project_name="Nhà phố concept", require_dwg=False)

    assert result.bundle.passed
    text = _pdf_text(result.bundle.pdf_path)
    assert "7.00 m" in text
    assert "25.00 m" in text
    assert "Ranh đất 7 m x 25 m" in text
    assert "Ranh đất 5 m x 15 m" not in text
    assert "Bản vẽ khái niệm - không dùng cho thi công" in text
    assert "Bìa, mục lục và giả định" in text
    assert "Bảng phòng và diện tích" in text
    assert "Bảng cửa đi và cửa sổ" in text
    assert "Giả định và ghi chú style" in text
    assert "Phòng khách" in text
    assert "D-MAIN" in text or "D-L1-MAIN" in text
    assert "{'type':" not in text
    assert '"type":' not in text
    assert "Modern Tropical / Hiện đại nhiệt đới" in text
    assert "Vật liệu nền concept" in text
    assert "Mặt tiền concept" in text
    assert "Tầng-tầng 3.30 m" in text
    assert "Thông thủy ~3.00 m" in text
    assert "Sinh hoạt chung" in text
    assert "Kích thước sơ bộ để review công năng" in text
    assert "stair_lightwell" not in text
    assert any(" m x " in line and "m²" not in line for line in text.splitlines())
    with fitz.open(result.bundle.pdf_path) as doc:
        assert doc.page_count == len(result.drawing_package.sheets)
        for page in doc:
            pix = page.get_pixmap(matrix=fitz.Matrix(0.18, 0.18), alpha=False)
            assert any(value < 245 for value in pix.samples)

    expected_dxf_names = {
        "A-000-cover-index.dxf",
        "A-100-site.dxf",
        "A-101-F1-floorplan.dxf",
        "A-101-F2-floorplan.dxf",
        "A-101-F3-floorplan.dxf",
        "A-201-elevations.dxf",
        "A-301-sections.dxf",
        "A-601-room-area-schedule.dxf",
        "A-602-door-window-schedule.dxf",
        "A-901-assumptions-style-notes.dxf",
    }
    assert expected_dxf_names <= {path.name for path in result.bundle.dxf_paths}
    site_dxf = result.bundle.two_d_dir / "A-100-site.dxf"
    doc = ezdxf.readfile(site_dxf)
    assert doc.header["$INSUNITS"] == 6
    layers = {layer.dxf.name for layer in doc.layers}
    assert {"A-WALL", "A-DOOR", "A-GLAZ", "A-AREA", "A-ANNO-DIMS", "L-SITE"} <= layers
    schedule_doc = ezdxf.readfile(result.bundle.two_d_dir / "A-601-room-area-schedule.dxf")
    schedule_text = "\n".join(entity.dxf.text for entity in schedule_doc.modelspace() if entity.dxftype() == "TEXT")
    assert "Bang phong va dien tich" in schedule_text
    assert "Phòng khách" in schedule_text
    assert " m x " in schedule_text
    opening_schedule_doc = ezdxf.readfile(result.bundle.two_d_dir / "A-602-door-window-schedule.dxf")
    opening_schedule_text = "\n".join(entity.dxf.text for entity in opening_schedule_doc.modelspace() if entity.dxftype() == "TEXT")
    assert "{'type':" not in opening_schedule_text
    assert '"type":' not in opening_schedule_text
    assert "Sinh hoat chung" in schedule_text
    assert "Review cong nang" in schedule_text

    physical_gates = validate_physical_sheet_presence(result.drawing_package, result.bundle)
    assert concept_qa_passed(physical_gates)
    gate_codes = {gate.code for gate in physical_gates}
    assert {
        "CONCEPT_PDF_TITLE_BLOCKS",
        "CONCEPT_PDF_RENDER_ARTIFACTS",
        "CONCEPT_DXF_TITLE_BLOCKS",
        "CONCEPT_DXF_RENDER_ARTIFACTS",
        "CONCEPT_RENDER_SCOPE_TEXT",
    } <= gate_codes
    rendered_gate_names = {gate.name for gate in result.bundle.gate_results}
    assert {
        "PDF_SHEET_TITLE_BLOCKS",
        "PDF_CONCEPT_SCOPE_TEXT",
        "PDF_PLAN_VIEWPORT_USAGE",
        "PDF_ROOM_LABEL_NON_OVERLAP",
        "DXF_SHEET_PARITY",
        "DXF_MODELSPACE_NONEMPTY",
        "DXF_SHEET_TITLE_BLOCKS",
        "DXF_ENTITY_RICHNESS",
    } <= rendered_gate_names


def test_concept_render_qa_gates_report_pass_or_explicit_skip(tmp_path: Path):
    concept = _concept_layout()
    result = render_concept_2d_package(concept, tmp_path, project_name="Nhà phố concept", require_dwg=False)
    gates = validate_rendered_concept_bundle(result.bundle, result.drawing_package)

    assert gates
    assert all(gate.status == "pass" for gate in gates)


def test_style_selection_changes_facade_expression_and_material_notes(tmp_path: Path):
    _minimal_understanding, minimal_style, _minimal_layout, _minimal_render, minimal_text = _render_from_message(
        "Nha pho 5x20m, 3 tang, 3 phong ngu, thich toi gian am, it bao tri va nhieu luu tru.",
        tmp_path / "minimal",
    )
    _tropical_understanding, tropical_style, _tropical_layout, _tropical_render, tropical_text = _render_from_message(
        "Nha pho 5x20m, 4 tang, 4 phong ngu, thich hien dai nhiet doi, thoang, nhieu cay va che nang.",
        tmp_path / "tropical",
    )
    _indochine_understanding, indochine_style, _indochine_layout, _indochine_render, indochine_text = _render_from_message(
        "Nha pho 6x22m, 3 tang, gia dinh co tre nho, thich indochine nhe, go va may tre.",
        tmp_path / "indochine",
    )

    assert minimal_style.selected_style_id == "minimal_warm"
    assert tropical_style.selected_style_id == "modern_tropical"
    assert indochine_style.selected_style_id == "indochine_soft"
    assert "Calm asymmetric bays" in minimal_text
    assert "Layered vertical rhythm" in tropical_text
    assert "Soft vertical rhythm" in indochine_text
    assert "Vật liệu nền concept" in minimal_text
    assert "Vật liệu nền concept" in tropical_text
    assert "Vật liệu nền concept" in indochine_text
    assert len({minimal_text, tropical_text, indochine_text}) == 3


def test_explicit_dislikes_reduce_glass_and_surface_in_style_output(tmp_path: Path):
    understanding, style, layout, _render, text = _render_from_message(
        "Nha pho 5x20m, 3 tang, thich hien dai nhiet doi nhung khong thich qua nhieu kinh, mat tien lanh, vat lieu toi bong.",
        tmp_path / "dislikes",
    )

    assert style.selected_style_id == "modern_tropical"
    assert "too much glass" in understanding.dislikes
    front_windows = [opening for opening in layout.openings if opening.opening_type == "window" and opening.wall_id.endswith("-front")]
    assert front_windows
    assert all(float(opening.width_m.value) < 1.6 for opening in front_windows)
    assert "Dislike suppressed: large glass" in text
    assert "Giảm kính theo dislike" in text
    assert "Provenance: style-derived facade/material fields are tagged" in text


def test_reference_descriptors_render_as_style_hints_not_image_analysis(tmp_path: Path):
    _understanding, style, _layout, _render, text = _render_from_message(
        "Can ho 70m2, 2 phong ngu, 2 wc, thich indochine nhe, luu tru gon va phong khach am.",
        tmp_path / "reference-descriptors",
        reference_images=[
            {
                "visual_tags": ["arches", "rattan", "textured screens"],
                "materials": ["wood", "neutral palette"],
                "colors": ["soft contrast"],
            }
        ],
    )

    assert style.selected_style_id == "indochine_soft"
    assert "Reference descriptors are homeowner-provided style hints only" in text
    assert "no real image analysis" in text
    assert "Reference descriptors: soft arch" in text or "Reference descriptors: rattan timber screen" in text


def test_concept_render_qa_catches_missing_artifacts_and_titles(tmp_path: Path):
    concept = _concept_layout()
    result = render_concept_2d_package(concept, tmp_path, project_name="Nhà phố concept", require_dwg=False)

    removed = result.bundle.two_d_dir / "A-601-room-area-schedule.dxf"
    removed.unlink()
    missing_artifact_gates = validate_physical_sheet_presence(result.drawing_package, result.bundle)
    assert any(gate.code == "CONCEPT_DXF_PHYSICAL_SHEETS" and gate.status == "fail" for gate in missing_artifact_gates)
    assert any(gate.code == "CONCEPT_DXF_RENDER_ARTIFACTS" and gate.status == "fail" for gate in missing_artifact_gates)

    first_sheet = result.drawing_package.sheets[0]
    broken_package = replace(
        result.drawing_package,
        sheets=(replace(first_sheet, title="Missing rendered sheet title"), *result.drawing_package.sheets[1:]),
    )
    missing_title_gates = validate_physical_sheet_presence(broken_package, result.bundle)
    assert any(gate.code == "CONCEPT_PDF_SHEET_TITLES" and gate.status == "fail" for gate in missing_title_gates)
    assert any(gate.code == "CONCEPT_PDF_TITLE_BLOCKS" and gate.status == "fail" for gate in missing_title_gates)


def test_concept_package_qa_catches_duplicate_sheet_titles(tmp_path: Path):
    concept = _concept_layout()
    result = render_concept_2d_package(concept, tmp_path, project_name="Nhà phố concept", require_dwg=False)
    first_sheet, second_sheet, *remaining = result.drawing_package.sheets
    broken_package = replace(
        result.drawing_package,
        sheets=(first_sheet, replace(second_sheet, title=first_sheet.title), *remaining),
    )

    gates = validate_drawing_package_model(broken_package, concept)

    assert any(gate.code == "CONCEPT_SHEET_IDENTIFIERS" and gate.status == "fail" for gate in gates)


def test_live_adapter_package_source_contains_full_concept_sheet_roles():
    brief = complete_brief_payload()
    brief["lot"] = {"width_m": 5, "depth_m": 20, "orientation": "south"}
    brief["floors"] = 3
    geometry = build_geometry_v2(brief)

    result = adapt_live_design_version_to_concept_source(
        project_id="live-package-source",
        project_name="Live Package Source",
        brief_json=brief,
        geometry_json=geometry,
        resolved_style_params={"style_id": "minimal_warm", "drawing_notes": ["Live package source note."]},
        version_id="live-version",
    )

    assert result.is_ready
    package = result.source.drawing_package
    assert {
        "cover_index",
        "site",
        "floorplan",
        "elevations",
        "sections",
        "room_area_schedule",
        "door_window_schedule",
        "assumptions_style_notes",
    } <= {sheet.kind for sheet in package.sheets}
    assert package.qa_bounds["lot_width_m"] == 5
    assert package.qa_bounds["lot_depth_m"] == 20
    assert package.qa_bounds["floor_count"] == 3
