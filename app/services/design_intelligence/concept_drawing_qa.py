from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import fitz

from app.services.design_intelligence.concept_model import ArchitecturalConceptModel
from app.services.design_intelligence.drawing_package_model import DrawingPackageModel
from app.services.professional_deliverables.demo import Sprint1BundleResult


@dataclass(frozen=True)
class ConceptDrawingGate:
    code: str
    status: str
    detail: str


def validate_drawing_package_model(package: DrawingPackageModel, concept_model: ArchitecturalConceptModel) -> tuple[ConceptDrawingGate, ...]:
    gates = [
        _gate(
            "CONCEPT_SHEET_COVERAGE",
            _has_sheet_kinds(package, {"cover_index", "site", "floorplan", "elevations", "sections", "room_area_schedule", "door_window_schedule", "assumptions_style_notes"}),
            "Package includes required concept sheet roles",
        ),
        _gate("CONCEPT_DIMENSIONS_FROM_GEOMETRY", _dimensions_match_site(package, concept_model), "Dimensions match concept site geometry"),
        _gate("CONCEPT_ROOM_SCHEDULE", _schedule_has_rows(package, "room_area", len(concept_model.rooms)), "Room/area schedule is populated"),
        _gate("CONCEPT_OPENING_SCHEDULE", _schedule_has_rows(package, "door_window", len(concept_model.openings)), "Door/window schedule is populated"),
        _gate("CONCEPT_ASSUMPTIONS_VISIBLE", any(sheet.assumption_notes for sheet in package.sheets), "Assumptions are visible in package model"),
        _gate("CONCEPT_ONLY_STATUS", "not for construction" in package.concept_status_note.lower(), "Concept-only status is explicit"),
    ]
    return tuple(gates)


def validate_rendered_concept_bundle(result: Sprint1BundleResult, package: DrawingPackageModel | None = None) -> tuple[ConceptDrawingGate, ...]:
    gates = [
        ConceptDrawingGate(
            code=f"RENDER_{gate.name.upper().replace(' ', '_').replace('-', '_')}",
            status="pass" if gate.status in {"pass", "skipped"} else "fail",
            detail=gate.detail,
        )
        for gate in result.gate_results
    ]
    if package is not None:
        gates.extend(validate_physical_sheet_presence(package, result))
    return tuple(gates)


def validate_physical_sheet_presence(package: DrawingPackageModel, result: Sprint1BundleResult) -> tuple[ConceptDrawingGate, ...]:
    with fitz.open(result.pdf_path) as doc:
        page_count = doc.page_count
        pdf_text = "\n".join(page.get_text("text") for page in doc)
    expected_dxf = {_sheet_filename(sheet.number, sheet.kind) for sheet in package.sheets}
    actual_dxf = {path.name for path in result.dxf_paths}
    missing_dxf = sorted(expected_dxf - actual_dxf)
    required_titles = [sheet.title for sheet in package.sheets]
    missing_titles = [title for title in required_titles if title not in pdf_text]
    return (
        _gate("CONCEPT_PDF_PHYSICAL_SHEETS", page_count == len(package.sheets), f"PDF pages={page_count}, package sheets={len(package.sheets)}"),
        _gate("CONCEPT_DXF_PHYSICAL_SHEETS", not missing_dxf, "missing DXF sheets: " + ", ".join(missing_dxf) if missing_dxf else f"{len(actual_dxf)} DXF sheets present"),
        _gate("CONCEPT_PDF_SHEET_TITLES", not missing_titles, "missing PDF sheet titles: " + ", ".join(missing_titles[:8]) if missing_titles else "all package sheet titles present in PDF"),
    )


def concept_qa_passed(gates: tuple[ConceptDrawingGate, ...]) -> bool:
    return all(gate.status == "pass" for gate in gates)


def _gate(code: str, passed: bool, detail: str) -> ConceptDrawingGate:
    return ConceptDrawingGate(code=code, status="pass" if passed else "fail", detail=detail)


def _has_sheet_kinds(package: DrawingPackageModel, expected: set[str]) -> bool:
    return expected <= {sheet.kind for sheet in package.sheets}


def _dimensions_match_site(package: DrawingPackageModel, concept_model: ArchitecturalConceptModel) -> bool:
    values = {dimension.label: dimension.value_m for sheet in package.sheets for dimension in sheet.dimensions}
    return values.get("lot_width") == concept_model.site.width_m.value and values.get("lot_depth") == concept_model.site.depth_m.value


def _schedule_has_rows(package: DrawingPackageModel, schedule_type: str, minimum: int) -> bool:
    for sheet in package.sheets:
        for schedule in sheet.schedules:
            if schedule.schedule_type == schedule_type:
                return len(schedule.rows) >= minimum
    return False


def _sheet_filename(number: str, kind: str) -> str:
    if kind == "cover_index":
        return "A-000-cover-index.dxf"
    if kind == "site":
        return "A-100-site.dxf"
    if kind == "floorplan":
        return f"{number}-floorplan.dxf"
    if kind == "elevations":
        return "A-201-elevations.dxf"
    if kind == "sections":
        return "A-301-sections.dxf"
    if kind == "room_area_schedule":
        return "A-601-room-area-schedule.dxf"
    if kind == "door_window_schedule":
        return "A-602-door-window-schedule.dxf"
    if kind == "assumptions_style_notes":
        return "A-603-assumptions-style-notes.dxf"
    return f"{number.lower()}-{kind}.dxf"
