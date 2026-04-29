from __future__ import annotations

import json
from pathlib import Path

import ezdxf
import fitz
import pytest

from app.services.geometry import LAYER_2_SCHEMA
from app.services.professional_deliverables.artifact_quality_report import build_2d_artifact_readiness
from app.services.professional_deliverables.demo import generate_project_2d_bundle
from app.services.professional_deliverables.drawing_quality_gates import (
    validate_dxf_entity_richness,
    validate_dxf_modelspace_nonempty,
    validate_dxf_sheet_parity,
    validate_dxf_sheet_title_blocks,
    validate_pdf_elevation_layout,
    validate_pdf_no_title_overlap,
    validate_pdf_plan_viewport_usage,
    validate_pdf_room_label_non_overlap,
    validate_pdf_sheet_title_blocks,
)
from app.services.professional_deliverables.geometry_adapter import geometry_to_drawing_project
from app.services.professional_deliverables.sheet_assembler import assemble_sheet_set
from app.services.professional_deliverables.validators import GateResult


def _rect(x1: float, y1: float, x2: float, y2: float) -> list[list[float]]:
    return [[x1, y1], [x2, y1], [x2, y2], [x1, y2]]


def _walls(level: str, width: float, depth: float) -> list[dict]:
    return [
        {"id": f"wall-{level}-front", "level": level, "start": [0, 0], "end": [width, 0], "thickness_m": 0.2, "height_m": 3.3, "exterior": True},
        {"id": f"wall-{level}-right", "level": level, "start": [width, 0], "end": [width, depth], "thickness_m": 0.2, "height_m": 3.3, "exterior": True},
        {"id": f"wall-{level}-back", "level": level, "start": [width, depth], "end": [0, depth], "thickness_m": 0.2, "height_m": 3.3, "exterior": True},
        {"id": f"wall-{level}-left", "level": level, "start": [0, depth], "end": [0, 0], "thickness_m": 0.2, "height_m": 3.3, "exterior": True},
        {"id": f"wall-{level}-mid-a", "level": level, "start": [0, depth * 0.34], "end": [width, depth * 0.34], "thickness_m": 0.12, "height_m": 3.3},
        {"id": f"wall-{level}-mid-b", "level": level, "start": [0, depth * 0.64], "end": [width, depth * 0.64], "thickness_m": 0.12, "height_m": 3.3},
    ]


def _geometry(width: float = 7.0, depth: float = 25.0) -> dict:
    return {
        "$schema": LAYER_2_SCHEMA,
        "version_id": "quality-test-version",
        "site": {
            "boundary": _rect(0, 0, width, depth),
            "orientation_north_deg": 180,
            "area_m2": width * depth,
        },
        "levels": [
            {"id": "L1", "type": "floor", "elevation_m": 0, "floor_to_floor_height_m": 3.3, "clear_height_m": 3.0, "slab_thickness_m": 0.15},
            {"id": "L2", "type": "floor", "elevation_m": 3.3, "floor_to_floor_height_m": 3.3, "clear_height_m": 3.0, "slab_thickness_m": 0.15},
        ],
        "rooms": [
            {"id": "r-living", "level": "L1", "type": "living", "polygon": _rect(0.3, 0.3, width - 0.3, depth * 0.32), "area_m2": 44.8},
            {"id": "r-kitchen", "level": "L1", "type": "kitchen", "polygon": _rect(0.3, depth * 0.36, width - 0.3, depth * 0.62), "area_m2": 37.9},
            {"id": "r-bath", "level": "L1", "type": "bathroom", "polygon": _rect(width - 2.2, depth * 0.66, width - 0.3, depth * 0.78), "area_m2": 5.7},
            {"id": "r-bedroom", "level": "L2", "type": "bedroom", "name": "Bedroom 1", "polygon": _rect(0.3, 0.3, width - 0.3, depth * 0.36), "area_m2": 52.5},
            {"id": "r-worship", "level": "L2", "type": "worship", "polygon": _rect(0.3, depth * 0.42, width - 0.3, depth * 0.62), "area_m2": 30.2},
        ],
        "walls": _walls("L1", width, depth) + _walls("L2", width, depth),
        "openings": [
            {"id": "d-main", "level": "L1", "type": "door", "wall_id": "wall-L1-front", "position_along_wall_m": width / 2, "width_m": 1.2, "height_m": 2.4, "schedule_mark": "D01"},
            {"id": "w-living", "level": "L1", "type": "window", "wall_id": "wall-L1-right", "position_along_wall_m": depth * 0.18, "width_m": 1.4, "height_m": 1.2, "sill_height_m": 0.9, "schedule_mark": "W01"},
            {"id": "d-bed", "level": "L2", "type": "door", "wall_id": "wall-L2-front", "position_along_wall_m": width / 2, "width_m": 1.0, "height_m": 2.2, "schedule_mark": "D11"},
            {"id": "w-bed", "level": "L2", "type": "window", "wall_id": "wall-L2-back", "position_along_wall_m": width / 2, "width_m": 1.6, "height_m": 1.2, "sill_height_m": 0.9, "schedule_mark": "W11"},
        ],
        "fixtures": [
            {"id": "fx-sofa", "level": "L1", "type": "sofa", "position": [width / 2, 4.0], "dimensions": {"width_m": 2.0, "depth_m": 0.9}},
            {"id": "fx-sink", "level": "L1", "type": "sink", "position": [width - 1.0, depth * 0.7], "dimensions": {"width_m": 0.7, "depth_m": 0.5}},
            {"id": "fx-bed", "level": "L2", "type": "bed", "position": [width / 2, 5.0], "dimensions": {"width_m": 2.0, "depth_m": 1.8}},
        ],
        "roof": {"terrace_zones": [{"polygon": _rect(0, 0, width, depth)}]},
        "dimensions_config": {"overall": [{"label": "site", "width_m": width, "depth_m": depth}]},
    }


@pytest.fixture()
def quality_bundle(tmp_path: Path):
    project = geometry_to_drawing_project(
        project_id="quality-project",
        project_name="Nhà phố kiểm thử",
        brief_json={"summary": "Nhà phố 7m x 25m"},
        geometry_json=_geometry(),
        version_id="quality-version",
    )
    return project, generate_project_2d_bundle(project, tmp_path, require_dwg=False)


def _pdf_text(path: Path) -> str:
    with fitz.open(path) as doc:
        return "\n".join(page.get_text("text") for page in doc)


def test_pdf_uses_actual_lot_dimensions_for_project_geometry(quality_bundle):
    _project, result = quality_bundle
    text = _pdf_text(result.pdf_path)

    assert "7.00 m" in text
    assert "25.00 m" in text
    assert "Ranh đất 7 m x 25 m" in text


def test_pdf_does_not_contain_stale_golden_dimensions(quality_bundle):
    _project, result = quality_bundle
    text = _pdf_text(result.pdf_path)
    lines = {line.strip() for line in text.splitlines()}

    assert "Ranh đất 5 m x 15 m" not in text
    assert "5.00 m" not in lines
    assert "15.00 m" not in lines


def test_pdf_renders_pages_nonblank(quality_bundle):
    _project, result = quality_bundle
    with fitz.open(result.pdf_path) as doc:
        assert doc.page_count == 5
        for page in doc:
            pix = page.get_pixmap(matrix=fitz.Matrix(0.18, 0.18), alpha=False)
            assert any(value < 245 for value in pix.samples)


def test_pdf_room_labels_and_areas_present(quality_bundle):
    _project, result = quality_bundle
    text = _pdf_text(result.pdf_path)

    assert "Phòng khách" in text
    assert "Bếp và ăn" in text
    assert "Phòng ngủ 1" in text
    assert "44.8 m²" in text
    assert "52.5 m²" in text


def test_pdf_elevation_frames_do_not_overlap(quality_bundle):
    project, _result = quality_bundle

    assert validate_pdf_no_title_overlap(project).status == "pass"
    assert validate_pdf_elevation_layout(project).status == "pass"


def test_pdf_viewport_sheet_titles_and_room_label_non_overlap_signals_pass(quality_bundle):
    project, result = quality_bundle
    sheets = assemble_sheet_set(project)

    assert validate_pdf_sheet_title_blocks(result.pdf_path, sheets).status == "pass"
    assert validate_pdf_plan_viewport_usage(project).status == "pass"
    assert validate_pdf_room_label_non_overlap(project).status == "pass"


def test_dxf_uses_actual_lot_dimensions_for_project_geometry(quality_bundle):
    _project, result = quality_bundle
    site_doc = ezdxf.readfile(result.two_d_dir / "A-100-site.dxf")
    text = "\n".join(entity.dxf.text for entity in site_doc.modelspace() if entity.dxftype() == "TEXT")

    assert "7.00 m" in text
    assert "25.00 m" in text
    assert "Ranh đất 7 m x 25 m" in text


def test_dxf_extents_match_site_boundary(quality_bundle):
    project, result = quality_bundle
    site_doc = ezdxf.readfile(result.two_d_dir / "A-100-site.dxf")
    site = next(entity for entity in site_doc.modelspace() if entity.dxftype() == "LWPOLYLINE" and entity.dxf.layer == "L-SITE")
    points = list(site.get_points("xy"))
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]

    assert max(xs) - min(xs) == pytest.approx(project.lot_width_m)
    assert max(ys) - min(ys) == pytest.approx(project.lot_depth_m)


def test_dxf_required_layers_and_units(quality_bundle):
    _project, result = quality_bundle
    doc = ezdxf.readfile(result.two_d_dir / "A-100-site.dxf")
    layers = {layer.dxf.name for layer in doc.layers}

    assert doc.header["$INSUNITS"] == 6
    assert {"A-WALL", "A-DOOR", "A-GLAZ", "A-AREA", "A-ANNO-DIMS", "L-SITE"} <= layers


def test_dxf_room_labels_and_openings_present(quality_bundle):
    _project, result = quality_bundle
    floor_doc = ezdxf.readfile(result.two_d_dir / "A-101-F1-floorplan.dxf")
    text = "\n".join(entity.dxf.text for entity in floor_doc.modelspace() if entity.dxftype() == "TEXT")
    layers = [getattr(entity.dxf, "layer", "") for entity in floor_doc.modelspace()]

    assert "Phòng khách" in text
    assert "44.8 m²" in text
    assert "A-DOOR" in layers
    assert "A-GLAZ" in layers


def test_dxf_sheet_parity_title_blocks_and_entity_richness_pass(quality_bundle):
    project, result = quality_bundle
    sheets = assemble_sheet_set(project)

    assert validate_dxf_sheet_parity(result.dxf_paths, sheets).status == "pass"
    assert validate_dxf_modelspace_nonempty(result.dxf_paths).status == "pass"
    assert validate_dxf_sheet_title_blocks(result.dxf_paths, sheets).status == "pass"
    assert validate_dxf_entity_richness(result.dxf_paths, sheets).status == "pass"


def test_quality_report_contains_artifact_readiness(quality_bundle):
    _project, result = quality_bundle

    assert result.artifact_quality_report_json is not None
    payload = json.loads(result.artifact_quality_report_json.read_text(encoding="utf-8"))
    roles = {artifact["artifact_role"]: artifact for artifact in payload["artifacts"]}

    assert roles["pdf"]["state"] == "ready"
    assert roles["pdf"]["customer_ready"] is True
    assert roles["pdf"]["visual_qa"] is True
    assert roles["dxf"]["state"] == "ready"
    assert roles["dwg"]["state"] == "skipped"
    assert {"exists", "format_valid", "semantic_valid", "visual_qa", "customer_ready"} <= set(roles["pdf"])
    assert "PDF_PLAN_VIEWPORT_USAGE" in roles["pdf"]["gates"]
    assert "PDF_ROOM_LABEL_NON_OVERLAP" in roles["pdf"]["gates"]
    assert "DXF_SHEET_PARITY" in roles["dxf"]["gates"]


def test_visual_qa_failure_prevents_market_customer_readiness(tmp_path: Path):
    pdf_path = tmp_path / "bundle.pdf"
    dxf_path = tmp_path / "A-100-site.dxf"
    pdf_path.write_bytes(b"%PDF-visual-fail-placeholder")
    dxf_path.write_bytes(b"0\nEOF\n")

    readiness = build_2d_artifact_readiness(
        pdf_path=pdf_path,
        dxf_paths=(dxf_path,),
        dwg_paths=(),
        gate_results=(
            GateResult("PDF_PAGE_COUNT", "pass", "ok"),
            GateResult("PDF_SHEET_TITLE_BLOCKS", "pass", "ok"),
            GateResult("PDF_CONCEPT_SCOPE_TEXT", "pass", "ok"),
            GateResult("PDF_DYNAMIC_DIMENSIONS", "pass", "ok"),
            GateResult("PDF_SITE_BOUNDARY_MATCH", "pass", "ok"),
            GateResult("PDF_FLOOR_COUNT", "pass", "ok"),
            GateResult("PDF_ROOM_LABELS_AREAS", "pass", "ok"),
            GateResult("PDF_DIMENSION_CHAINS", "pass", "ok"),
            GateResult("PDF_NO_STALE_GOLDEN_LABELS", "pass", "ok"),
            GateResult("PDF_PLAN_VIEWPORT_USAGE", "fail", "too much whitespace"),
            GateResult("PDF_ROOM_LABEL_NON_OVERLAP", "pass", "ok"),
            GateResult("PDF_NO_TITLE_OVERLAP", "pass", "ok"),
            GateResult("PDF_PAGE_RENDER_NONBLANK", "pass", "ok"),
            GateResult("PDF_ELEVATION_LAYOUT", "pass", "ok"),
            GateResult("DXF_SHEET_PARITY", "pass", "ok"),
            GateResult("DXF_MODELSPACE_NONEMPTY", "pass", "ok"),
            GateResult("DXF_SHEET_TITLE_BLOCKS", "pass", "ok"),
            GateResult("DXF_OPENABLE", "pass", "ok"),
            GateResult("DXF_UNITS_METERS", "pass", "ok"),
            GateResult("DXF_REQUIRED_LAYERS", "pass", "ok"),
            GateResult("DXF_PROJECT_EXTENTS_MATCH", "pass", "ok"),
            GateResult("DXF_DIMENSIONS_MATCH", "pass", "ok"),
            GateResult("DXF_ROOM_LABELS_OPENINGS", "pass", "ok"),
            GateResult("DXF_NO_STALE_GOLDEN_LABELS", "pass", "ok"),
        ),
        dwg_skip_reason="ODA converter unavailable locally",
    )

    pdf = next(item for item in readiness if item.artifact_role == "pdf")
    assert pdf.technical_ready is True
    assert pdf.visual_qa is False
    assert pdf.customer_ready is False
    assert pdf.market_presentation_ready is False
    assert pdf.state == "partial"
