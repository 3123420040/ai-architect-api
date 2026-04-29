from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import ezdxf
import fitz

from app.services.design_intelligence.concept_model import ArchitecturalConceptModel
from app.services.design_intelligence.drawing_package_model import DrawingPackageModel
from app.services.professional_deliverables.demo import Sprint1BundleResult


@dataclass(frozen=True)
class ConceptDrawingGate:
    code: str
    status: str
    detail: str


UNSAFE_SCOPE_CLAIMS = (
    "issued for construction",
    "permit approved",
    "permit drawings",
    "structural design",
    "mep design",
    "code compliant",
    "code compliance",
    "construction ready",
    "legal compliance",
    "geotechnical report",
    "bản vẽ thi công",
    "hồ sơ xin phép",
    "thiết kế kết cấu",
    "thiết kế điện nước",
    "đạt quy chuẩn",
)


def validate_drawing_package_model(package: DrawingPackageModel, concept_model: ArchitecturalConceptModel) -> tuple[ConceptDrawingGate, ...]:
    gates = [
        _gate(
            "CONCEPT_SHEET_COVERAGE",
            _has_sheet_kinds(package, {"cover_index", "site", "floorplan", "elevations", "sections", "room_area_schedule", "door_window_schedule", "assumptions_style_notes"}),
            "Package includes required concept sheet roles",
        ),
        _gate("CONCEPT_SHEET_IDENTIFIERS", _sheet_identifiers_are_unique(package), "Sheet numbers and titles are populated and unique"),
        _gate("CONCEPT_DIMENSIONS_FROM_GEOMETRY", _dimensions_match_site(package, concept_model), "Dimensions match concept site geometry"),
        _gate("CONCEPT_ROOM_SCHEDULE", _schedule_has_rows(package, "room_area", len(concept_model.rooms)), "Room/area schedule is populated"),
        _gate("CONCEPT_OPENING_SCHEDULE", _schedule_has_rows(package, "door_window", len(concept_model.openings)), "Door/window schedule is populated"),
        _gate("CONCEPT_SCHEDULE_COLUMNS", _schedule_columns_present(package), "Schedules include homeowner-readable columns"),
        _gate("CONCEPT_LABEL_READABILITY", _labels_are_readable(package), "Sheet labels are populated and concise"),
        _gate("CONCEPT_ASSUMPTIONS_VISIBLE", any(sheet.assumption_notes for sheet in package.sheets), "Assumptions are visible in package model"),
        _gate("CONCEPT_ONLY_STATUS", "not for construction" in package.concept_status_note.lower(), "Concept-only status is explicit"),
        _gate("CONCEPT_SAFE_SCOPE_TEXT", not _unsafe_scope_hits(package), _unsafe_scope_detail(package)),
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
    if not result.pdf_path.exists():
        return (
            _gate("CONCEPT_PDF_PHYSICAL_SHEETS", False, f"PDF missing: {result.pdf_path}"),
            _gate("CONCEPT_DXF_PHYSICAL_SHEETS", False, "PDF missing before DXF/title validation"),
        )
    with fitz.open(result.pdf_path) as doc:
        page_count = doc.page_count
        page_texts = [page.get_text("text") for page in doc]
        pdf_text = "\n".join(page_texts)
        blank_pages = _blank_pdf_pages(doc)
    expected_dxf = {_sheet_filename(sheet.number, sheet.kind) for sheet in package.sheets}
    actual_dxf = {path.name for path in result.dxf_paths if path.exists() and path.stat().st_size > 0}
    missing_dxf = sorted(expected_dxf - actual_dxf)
    required_titles = [sheet.title for sheet in package.sheets]
    missing_titles = [title for title in required_titles if title not in pdf_text]
    missing_title_blocks = [
        f"{sheet.number} {sheet.title}"
        for index, sheet in enumerate(package.sheets)
        if index >= len(page_texts) or sheet.number not in page_texts[index] or sheet.title not in page_texts[index]
    ]
    missing_dxf_title_blocks = _missing_dxf_title_blocks(package, result)
    empty_dxf = _empty_dxf_sheets(result)
    raw_hits = _raw_render_hits(pdf_text, result.dxf_paths)
    missing_room_dimensions = _missing_room_dimension_labels(package, pdf_text)
    style_note_missing = _style_note_missing(pdf_text)
    section_height_missing = "Mặt cắt concept" in pdf_text and ("3.30 m" not in pdf_text.split("Mặt cắt concept", 1)[-1] or "3.00 m" not in pdf_text.split("Mặt cắt concept", 1)[-1])
    sparse_elevations = _sparse_elevation_pages(result.pdf_path)
    return (
        _gate("CONCEPT_PDF_PHYSICAL_SHEETS", page_count == len(package.sheets), f"PDF pages={page_count}, package sheets={len(package.sheets)}"),
        _gate("CONCEPT_DXF_PHYSICAL_SHEETS", not missing_dxf, "missing DXF sheets: " + ", ".join(missing_dxf) if missing_dxf else f"{len(actual_dxf)} DXF sheets present"),
        _gate("CONCEPT_PDF_SHEET_TITLES", not missing_titles, "missing PDF sheet titles: " + ", ".join(missing_titles[:8]) if missing_titles else "all package sheet titles present in PDF"),
        _gate("CONCEPT_PDF_TITLE_BLOCKS", not missing_title_blocks, "missing title block tokens: " + ", ".join(missing_title_blocks[:6]) if missing_title_blocks else "every PDF page carries its sheet number and title"),
        _gate("CONCEPT_PDF_RENDER_ARTIFACTS", not blank_pages, f"blank or near-blank PDF pages: {blank_pages}" if blank_pages else "all PDF pages render with visible content"),
        _gate("CONCEPT_DXF_TITLE_BLOCKS", not missing_dxf_title_blocks, "missing DXF title block tokens: " + ", ".join(missing_dxf_title_blocks[:6]) if missing_dxf_title_blocks else "every DXF sheet carries its sheet number and title"),
        _gate("CONCEPT_DXF_RENDER_ARTIFACTS", not empty_dxf, "empty/unopenable DXF sheets: " + ", ".join(empty_dxf[:6]) if empty_dxf else "all DXF sheets contain modelspace entities"),
        _gate("CONCEPT_RENDER_NO_RAW_INTERNAL_STRINGS", not raw_hits, "raw/internal strings found: " + ", ".join(raw_hits[:8]) if raw_hits else "no raw dict/json/internal strings found"),
        _gate("CONCEPT_RENDER_ROOM_DIMENSIONS", not missing_room_dimensions, "missing room dimension labels: " + ", ".join(missing_room_dimensions[:8]) if missing_room_dimensions else "room-level dimension labels are rendered"),
        _gate("CONCEPT_RENDER_STYLE_MATERIAL_NOTES", not style_note_missing, "style/material notes are missing facade/material/customer label text" if style_note_missing else "style label, facade, and material notes are rendered"),
        _gate("CONCEPT_RENDER_SECTION_HEIGHTS", not section_height_missing, "section missing 3.30 m floor-to-floor and 3.00 m clear-height labels" if section_height_missing else "section height labels rendered"),
        _gate("CONCEPT_RENDER_ELEVATION_DENSITY", not sparse_elevations, "sparse elevation pages: " + ", ".join(sparse_elevations) if sparse_elevations else "elevation pages meet minimum visual density"),
        _gate("CONCEPT_RENDER_SCOPE_TEXT", not _unsafe_render_hits(pdf_text, result.dxf_paths), _unsafe_render_detail(pdf_text, result.dxf_paths)),
    )


def concept_qa_passed(gates: tuple[ConceptDrawingGate, ...]) -> bool:
    return all(gate.status == "pass" for gate in gates)


def _gate(code: str, passed: bool, detail: str) -> ConceptDrawingGate:
    return ConceptDrawingGate(code=code, status="pass" if passed else "fail", detail=detail)


def _has_sheet_kinds(package: DrawingPackageModel, expected: set[str]) -> bool:
    return expected <= {sheet.kind for sheet in package.sheets}


def _sheet_identifiers_are_unique(package: DrawingPackageModel) -> bool:
    numbers = [sheet.number.strip() for sheet in package.sheets]
    titles = [sheet.title.strip() for sheet in package.sheets]
    return all(numbers) and all(titles) and len(numbers) == len(set(numbers)) and len(titles) == len(set(titles))


def _dimensions_match_site(package: DrawingPackageModel, concept_model: ArchitecturalConceptModel) -> bool:
    values = {dimension.label: dimension.value_m for sheet in package.sheets for dimension in sheet.dimensions}
    return values.get("lot_width") == concept_model.site.width_m.value and values.get("lot_depth") == concept_model.site.depth_m.value


def _schedule_has_rows(package: DrawingPackageModel, schedule_type: str, minimum: int) -> bool:
    for sheet in package.sheets:
        for schedule in sheet.schedules:
            if schedule.schedule_type == schedule_type:
                return len(schedule.rows) >= minimum
    return False


def _schedule_columns_present(package: DrawingPackageModel) -> bool:
    expected_by_type = {
        "room_area": {"room_id", "level_id", "label_vi", "room_type", "room_type_vi", "width_m", "depth_m", "area_m2", "review_note"},
        "door_window": {"opening_id", "level_id", "type", "type_vi", "width_m", "height_m", "wall_id", "operation", "review_note"},
        "assumptions": {"note"},
    }
    found = {schedule.schedule_type: schedule for sheet in package.sheets for schedule in sheet.schedules}
    for schedule_type, required in expected_by_type.items():
        schedule = found.get(schedule_type)
        if schedule is None:
            return False
        for row in schedule.rows:
            if not required <= set(row):
                return False
    return True


def _labels_are_readable(package: DrawingPackageModel) -> bool:
    labels = [label for sheet in package.sheets for label in sheet.labels]
    if not labels:
        return False
    return all(label and len(label.strip()) >= 2 and len(label.strip()) <= 96 for label in labels)


def _iter_package_text(package: DrawingPackageModel) -> list[str]:
    values: list[str] = [package.concept_status_note, package.line_weight_profile, package.layer_profile]
    for sheet in package.sheets:
        values.extend([sheet.number, sheet.title, sheet.kind])
        values.extend(sheet.labels)
        values.extend(sheet.assumption_notes)
        values.extend(sheet.style_notes)
        for schedule in sheet.schedules:
            values.append(schedule.schedule_type)
            for row in schedule.rows:
                values.extend(str(value) for value in row.values())
    return values


def _unsafe_scope_hits(package: DrawingPackageModel) -> list[str]:
    text = "\n".join(_iter_package_text(package)).lower()
    return [claim for claim in UNSAFE_SCOPE_CLAIMS if claim in text]


def _unsafe_scope_detail(package: DrawingPackageModel) -> str:
    hits = _unsafe_scope_hits(package)
    if hits:
        return "unsafe scope claims found: " + ", ".join(hits)
    return "no construction, permit, MEP, or structural readiness claims found"


def _blank_pdf_pages(doc: fitz.Document) -> list[int]:
    blank_pages: list[int] = []
    for index, page in enumerate(doc, start=1):
        pix = page.get_pixmap(matrix=fitz.Matrix(0.18, 0.18), alpha=False)
        channels = pix.n
        samples = pix.samples
        non_white = 0
        for offset in range(0, len(samples), channels):
            pixel = samples[offset : offset + min(channels, 3)]
            if any(value < 245 for value in pixel):
                non_white += 1
        if non_white < 100:
            blank_pages.append(index)
    return blank_pages


def _dxf_text(doc: Any) -> str:
    texts: list[str] = []
    for entity in doc.modelspace():
        if entity.dxftype() == "TEXT":
            texts.append(str(entity.dxf.text))
        elif entity.dxftype() == "MTEXT":
            texts.append(entity.plain_text())
    return "\n".join(texts)


def _missing_dxf_title_blocks(package: DrawingPackageModel, result: Sprint1BundleResult) -> list[str]:
    paths = {path.name: path for path in result.dxf_paths if path.exists()}
    missing: list[str] = []
    for sheet in package.sheets:
        path = paths.get(_sheet_filename(sheet.number, sheet.kind))
        if path is None:
            missing.append(sheet.number)
            continue
        try:
            text = _dxf_text(ezdxf.readfile(path))
        except Exception:
            missing.append(sheet.number)
            continue
        if sheet.number not in text or sheet.title not in text:
            missing.append(f"{sheet.number} {sheet.title}")
    return missing


def _empty_dxf_sheets(result: Sprint1BundleResult) -> list[str]:
    empty: list[str] = []
    for path in result.dxf_paths:
        if not path.exists() or path.stat().st_size == 0:
            empty.append(path.name)
            continue
        try:
            doc = ezdxf.readfile(path)
        except Exception:
            empty.append(path.name)
            continue
        if not list(doc.modelspace()):
            empty.append(path.name)
    return empty


def _unsafe_render_hits(pdf_text: str, dxf_paths: tuple[Path, ...]) -> list[str]:
    render_text = pdf_text.lower()
    for path in dxf_paths:
        if not path.exists():
            continue
        try:
            render_text += "\n" + _dxf_text(ezdxf.readfile(path)).lower()
        except Exception:
            continue
    return [claim for claim in UNSAFE_SCOPE_CLAIMS if claim in render_text]


def _unsafe_render_detail(pdf_text: str, dxf_paths: tuple[Path, ...]) -> str:
    hits = _unsafe_render_hits(pdf_text, dxf_paths)
    if hits:
        return "unsafe rendered scope claims found: " + ", ".join(hits)
    return "rendered text stays concept-only"


def _raw_render_hits(pdf_text: str, dxf_paths: tuple[Path, ...]) -> list[str]:
    text = pdf_text
    for path in dxf_paths:
        if not path.exists():
            continue
        try:
            text += "\n" + _dxf_text(ezdxf.readfile(path))
        except Exception:
            continue
    hits: list[str] = []
    for pattern in ("{'type':", '"type":', "<DecisionValue", "source='", "assumption="):
        if pattern in text:
            hits.append(pattern)
    return hits


def _missing_room_dimension_labels(package: DrawingPackageModel, pdf_text: str) -> list[str]:
    labels: list[str] = []
    for sheet in package.sheets:
        if sheet.kind != "room_area_schedule":
            continue
        for schedule in sheet.schedules:
            if schedule.schedule_type != "room_area":
                continue
            for row in schedule.rows:
                width = row.get("width_m")
                depth = row.get("depth_m")
                if width is None or depth is None:
                    continue
                label = f"{float(width):.2f} m x {float(depth):.2f} m"
                if label not in pdf_text:
                    labels.append(label)
    return labels


def _style_note_missing(pdf_text: str) -> bool:
    text = pdf_text.lower()
    has_style = any(token.lower() in text for token in ("Modern Minimalist", "Modern Tropical", "Indochine Soft"))
    return not has_style or "mặt tiền" not in text or "vật liệu" not in text


def _sparse_elevation_pages(pdf_path: Path, *, minimum_ratio: float = 0.045) -> list[str]:
    sparse: list[str] = []
    with fitz.open(pdf_path) as doc:
        for index, page in enumerate(doc, start=1):
            if "Mặt đứng concept" not in page.get_text("text"):
                continue
            ratio = _nonwhite_ratio(page)
            if ratio < minimum_ratio:
                sparse.append(f"page {index}: {ratio:.3f}")
    return sparse


def _nonwhite_ratio(page: fitz.Page) -> float:
    pix = page.get_pixmap(matrix=fitz.Matrix(0.18, 0.18), alpha=False)
    channels = pix.n
    samples = pix.samples
    non_white = 0
    total = 0
    for offset in range(0, len(samples), channels):
        pixel = samples[offset : offset + min(channels, 3)]
        total += 1
        if any(value < 245 for value in pixel):
            non_white += 1
    return non_white / total if total else 0.0


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
        return "A-901-assumptions-style-notes.dxf"
    return f"{number.lower()}-{kind}.dxf"
