from __future__ import annotations

import re
from pathlib import Path

import ezdxf
import fitz

from app.services.professional_deliverables.aia_layers import REQUIRED_RECOGNITION_LAYERS
from app.services.professional_deliverables.drawing_contract import DrawingProject
from app.services.professional_deliverables.pdf_generator import (
    CONTENT_BOTTOM,
    CONTENT_TOP,
    PAGE_SIZE,
    SCALE_1_100_PT_PER_M,
    format_dimension_m,
    plan_layout,
)
from app.services.professional_deliverables.validators import GateResult


def _pdf_text(path: Path) -> str:
    with fitz.open(path) as doc:
        return "\n".join(page.get_text("text") for page in doc)


def _dimension_values(project: DrawingProject) -> set[float]:
    return {round(project.lot_width_m, 2), round(project.lot_depth_m, 2)}


def _stale_golden_hits(text: str, project: DrawingProject) -> list[str]:
    hits: list[str] = []
    text_lines = {line.strip() for line in text.splitlines()}
    actual = _dimension_values(project)
    for value in (5.0, 15.0):
        if round(value, 2) not in actual and format_dimension_m(value) in text_lines:
            hits.append(format_dimension_m(value))
    if (round(5.0, 2), round(15.0, 2)) != (round(project.lot_width_m, 2), round(project.lot_depth_m, 2)):
        for phrase in ("Ranh đất 5 m x 15 m", "Ranh dat 5 m x 15 m"):
            if phrase in text:
                hits.append(phrase)
    return hits


def validate_pdf_page_count(path: Path, expected_pages: int) -> GateResult:
    with fitz.open(path) as doc:
        count = doc.page_count
    if count != expected_pages:
        return GateResult("PDF_PAGE_COUNT", "fail", f"expected {expected_pages} pages, found {count}")
    return GateResult("PDF_PAGE_COUNT", "pass", f"{count} pages")


def validate_pdf_dynamic_dimensions(path: Path, project: DrawingProject) -> GateResult:
    text = _pdf_text(path)
    expected = [format_dimension_m(project.lot_width_m), format_dimension_m(project.lot_depth_m)]
    missing = [label for label in expected if label not in text]
    if missing:
        return GateResult("PDF_DYNAMIC_DIMENSIONS", "fail", f"missing dimension labels: {missing}")
    return GateResult("PDF_DYNAMIC_DIMENSIONS", "pass", f"found {', '.join(expected)}")


def validate_pdf_no_stale_golden_labels(path: Path, project: DrawingProject) -> GateResult:
    hits = _stale_golden_hits(_pdf_text(path), project)
    if hits:
        return GateResult("PDF_NO_STALE_GOLDEN_LABELS", "fail", "stale labels found: " + ", ".join(hits))
    return GateResult("PDF_NO_STALE_GOLDEN_LABELS", "pass", "no stale non-source golden dimensions found")


def validate_pdf_floor_count(path: Path, project: DrawingProject) -> GateResult:
    minimum = project.storeys + 3
    with fitz.open(path) as doc:
        count = doc.page_count
    if count < minimum:
        return GateResult("PDF_FLOOR_COUNT", "fail", f"expected at least {project.storeys} floor plan sheets plus site/elevation/section, found {count} pages")
    return GateResult("PDF_FLOOR_COUNT", "pass", f"{project.storeys} floor plan sheets represented in {count} PDF pages")


def validate_pdf_room_labels_areas(path: Path, project: DrawingProject) -> GateResult:
    text = _pdf_text(path)
    missing: list[str] = []
    for room in project.rooms:
        if room.name not in text:
            missing.append(room.name)
        area_label = f"{room.display_area_m2:.1f} m²"
        if area_label not in text:
            missing.append(area_label)
    if missing:
        return GateResult("PDF_ROOM_LABELS_AREAS", "fail", "missing labels: " + ", ".join(missing[:10]))
    return GateResult("PDF_ROOM_LABELS_AREAS", "pass", f"{len(project.rooms)} room labels and area labels found")


def validate_pdf_dimension_chains(path: Path, project: DrawingProject) -> GateResult:
    text = _pdf_text(path)
    expected = {format_dimension_m(project.lot_width_m), format_dimension_m(project.lot_depth_m), "1 m"}
    missing = sorted(label for label in expected if label not in text)
    if missing:
        return GateResult("PDF_DIMENSION_CHAINS", "fail", f"missing dimension chain labels: {missing}")
    return GateResult("PDF_DIMENSION_CHAINS", "pass", "overall lot dimension chains and scale segment found")


def validate_pdf_room_dimension_labels(path: Path, project: DrawingProject) -> GateResult:
    text = _pdf_text(path)
    expected: list[str] = []
    for room in project.rooms:
        min_x, min_y, max_x, max_y = _bounds(room.polygon)
        expected.append(f"{format_dimension_m(max_x - min_x)} x {format_dimension_m(max_y - min_y)}")
    found = [label for label in expected if label in text]
    minimum = max(1, int(len(expected) * 0.7))
    if len(found) < minimum:
        missing = [label for label in expected if label not in text]
        return GateResult("PDF_ROOM_DIMENSION_LABELS", "fail", f"found {len(found)}/{len(expected)} room dimension labels; missing {missing[:8]}")
    return GateResult("PDF_ROOM_DIMENSION_LABELS", "pass", f"{len(found)}/{len(expected)} room dimension labels found")


def validate_pdf_no_raw_internal_strings(path: Path) -> GateResult:
    hits = _raw_internal_hits(_pdf_text(path))
    if hits:
        return GateResult("PDF_NO_RAW_INTERNAL_STRINGS", "fail", "raw/internal strings found: " + ", ".join(hits[:8]))
    return GateResult("PDF_NO_RAW_INTERNAL_STRINGS", "pass", "no raw dict/json/internal operation strings found")


def validate_pdf_section_height_labels(path: Path) -> GateResult:
    text = _pdf_text(path)
    section_text = text.split("Mặt cắt concept", 1)[-1] if "Mặt cắt concept" in text else text
    if "3.30 m" not in section_text or "3.00 m" not in section_text:
        return GateResult("PDF_SECTION_HEIGHT_LABELS", "fail", "section missing floor-to-floor and clear-height dimension labels")
    return GateResult("PDF_SECTION_HEIGHT_LABELS", "pass", "section includes floor-to-floor and clear-height labels")


def validate_pdf_style_material_notes(path: Path) -> GateResult:
    text = _pdf_text(path).lower()
    missing: list[str] = []
    for token in ("style id:", "mặt tiền", "vật liệu"):
        if token not in text:
            missing.append(token)
    style_label_present = any(token.lower() in text for token in ("Modern Minimalist", "Modern Tropical", "Indochine Soft"))
    if not style_label_present:
        missing.append("customer-readable bilingual style label")
    if missing:
        return GateResult("PDF_STYLE_MATERIAL_NOTES", "fail", "missing style/material notes: " + ", ".join(missing))
    return GateResult("PDF_STYLE_MATERIAL_NOTES", "pass", "style label, facade strategy, and material notes are visible")


def validate_pdf_elevation_visual_density(path: Path, *, minimum_ratio: float = 0.045) -> GateResult:
    sparse_pages: list[str] = []
    with fitz.open(path) as doc:
        for index, page in enumerate(doc, start=1):
            text = page.get_text("text")
            if "Mặt đứng concept" not in text:
                continue
            ratio = _nonwhite_ratio(page)
            if ratio < minimum_ratio:
                sparse_pages.append(f"page {index}: {ratio:.3f}")
    if sparse_pages:
        return GateResult("PDF_ELEVATION_VISUAL_DENSITY", "fail", "sparse elevation pages: " + ", ".join(sparse_pages))
    return GateResult("PDF_ELEVATION_VISUAL_DENSITY", "pass", f"elevation pages meet density threshold {minimum_ratio:.3f}")


def validate_pdf_no_title_overlap(project: DrawingProject) -> GateResult:
    x, y, scale = plan_layout(project)
    top = y + project.lot_depth_m * scale
    if y < CONTENT_BOTTOM - 0.5 or top > CONTENT_TOP + 0.5:
        return GateResult("PDF_NO_TITLE_OVERLAP", "fail", f"plan viewport y={y:.1f}, top={top:.1f}, allowed={CONTENT_BOTTOM:.1f}-{CONTENT_TOP:.1f}")
    if x < 0 or x + project.lot_width_m * scale > PAGE_SIZE[0]:
        return GateResult("PDF_NO_TITLE_OVERLAP", "fail", f"plan viewport x={x:.1f} is outside page width")
    return GateResult("PDF_NO_TITLE_OVERLAP", "pass", "plan viewport fits above title block")


def validate_pdf_page_render_nonblank(path: Path) -> GateResult:
    blank_pages: list[int] = []
    with fitz.open(path) as doc:
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
    if blank_pages:
        return GateResult("PDF_PAGE_RENDER_NONBLANK", "fail", f"blank or near-blank rendered pages: {blank_pages}")
    return GateResult("PDF_PAGE_RENDER_NONBLANK", "pass", "all PDF pages render with visible content")


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


def validate_pdf_sheet_title_blocks(path: Path, sheets: tuple | list) -> GateResult:
    missing: list[str] = []
    with fitz.open(path) as doc:
        if doc.page_count != len(sheets):
            return GateResult("PDF_SHEET_TITLE_BLOCKS", "fail", f"PDF pages={doc.page_count}, sheets={len(sheets)}")
        for index, sheet in enumerate(sheets):
            text = doc[index].get_text("text")
            number = getattr(sheet, "number", "")
            title = getattr(sheet, "title", "")
            if number not in text or title not in text:
                missing.append(f"{number} {title}".strip())
    if missing:
        return GateResult("PDF_SHEET_TITLE_BLOCKS", "fail", "missing title block tokens: " + ", ".join(missing[:8]))
    return GateResult("PDF_SHEET_TITLE_BLOCKS", "pass", f"{len(sheets)} sheets carry page title block tokens")


def validate_pdf_concept_scope_text(path: Path) -> GateResult:
    text = _pdf_text(path).lower()
    unsafe_claims = (
        "issued for construction",
        "permit approved",
        "permit drawings",
        "structural design",
        "mep design",
        "code compliant",
        "construction ready",
        "bản vẽ thi công",
        "hồ sơ xin phép",
        "thiết kế kết cấu",
        "thiết kế điện nước",
    )
    hits = [claim for claim in unsafe_claims if claim in text]
    if hits:
        return GateResult("PDF_CONCEPT_SCOPE_TEXT", "fail", "unsafe scope claims found: " + ", ".join(hits))
    if "not for construction" not in text and "không dùng cho thi công" not in text:
        return GateResult("PDF_CONCEPT_SCOPE_TEXT", "fail", "concept-only disclaimer missing")
    return GateResult("PDF_CONCEPT_SCOPE_TEXT", "pass", "concept-only disclaimer present without readiness claims")


def validate_pdf_elevation_layout(project: DrawingProject) -> GateResult:
    height = project.storeys * 3.3 + 0.8
    available_frame_width = (PAGE_SIZE[0] - 2 * 28.0 - 82) / 2
    available_frame_height = (CONTENT_TOP - CONTENT_BOTTOM - 78) / 2
    max_width_m = max(project.lot_width_m, project.lot_depth_m, 1.0)
    scale = min(SCALE_1_100_PT_PER_M, available_frame_width / max_width_m, available_frame_height / max(height, 1.0))
    if max_width_m * scale > available_frame_width + 0.5 or height * scale > available_frame_height + 0.5:
        return GateResult("PDF_ELEVATION_LAYOUT", "fail", "elevation frames exceed available sheet cells")
    return GateResult("PDF_ELEVATION_LAYOUT", "pass", f"elevation frames fit at {scale:.2f} pt/m")


def validate_pdf_site_boundary_match(project: DrawingProject) -> GateResult:
    x, y, scale = plan_layout(project)
    if x < 0 or y < CONTENT_BOTTOM - 0.5:
        return GateResult("PDF_SITE_BOUNDARY_MATCH", "fail", "site boundary cannot fit the PDF viewport")
    return GateResult("PDF_SITE_BOUNDARY_MATCH", "pass", f"site boundary {project.lot_width_m:.2f}m x {project.lot_depth_m:.2f}m fits PDF viewport")


def _dxf_text(doc) -> str:
    texts: list[str] = []
    for entity in doc.modelspace():
        if entity.dxftype() == "TEXT":
            texts.append(str(entity.dxf.text))
        elif entity.dxftype() == "MTEXT":
            texts.append(entity.plain_text())
    return "\n".join(texts)


def validate_dxf_openable(path: Path) -> GateResult:
    try:
        ezdxf.readfile(path)
    except Exception as exc:
        return GateResult("DXF_OPENABLE", "fail", f"{path.name}: {exc}")
    return GateResult("DXF_OPENABLE", "pass", f"{path.name} opens with ezdxf")


def validate_dxf_units_meters(path: Path) -> GateResult:
    doc = ezdxf.readfile(path)
    units = doc.header.get("$INSUNITS")
    if units != 6:
        return GateResult("DXF_UNITS_METERS", "fail", f"{path.name}: $INSUNITS={units}, expected 6")
    return GateResult("DXF_UNITS_METERS", "pass", f"{path.name}: meters")


def validate_dxf_required_layers(path: Path) -> GateResult:
    doc = ezdxf.readfile(path)
    layers = {layer.dxf.name for layer in doc.layers}
    missing = sorted(REQUIRED_RECOGNITION_LAYERS - layers)
    if missing:
        return GateResult("DXF_REQUIRED_LAYERS", "fail", f"{path.name}: missing {missing}")
    return GateResult("DXF_REQUIRED_LAYERS", "pass", f"{path.name}: required layers present")


def validate_dxf_project_extents_match(path: Path, project: DrawingProject, *, tolerance_m: float = 0.01) -> GateResult:
    doc = ezdxf.readfile(path)
    site_polylines = [
        entity
        for entity in doc.modelspace()
        if entity.dxftype() == "LWPOLYLINE" and entity.dxf.layer in {"L-SITE", "A-WALL"}
    ]
    if not site_polylines:
        return GateResult("DXF_PROJECT_EXTENTS_MATCH", "fail", f"{path.name}: no site boundary polyline found")
    points = list(site_polylines[0].get_points("xy"))
    xs = [float(point[0]) for point in points]
    ys = [float(point[1]) for point in points]
    width = max(xs) - min(xs)
    depth = max(ys) - min(ys)
    if abs(width - project.lot_width_m) > tolerance_m or abs(depth - project.lot_depth_m) > tolerance_m:
        return GateResult("DXF_PROJECT_EXTENTS_MATCH", "fail", f"{path.name}: extents {width:.2f}x{depth:.2f}m, expected {project.lot_width_m:.2f}x{project.lot_depth_m:.2f}m")
    return GateResult("DXF_PROJECT_EXTENTS_MATCH", "pass", f"{path.name}: extents match {width:.2f}x{depth:.2f}m")


def validate_dxf_dimensions_match(path: Path, project: DrawingProject) -> GateResult:
    text = _dxf_text(ezdxf.readfile(path))
    expected = [format_dimension_m(project.lot_width_m), format_dimension_m(project.lot_depth_m)]
    missing = [label for label in expected if label not in text]
    if missing:
        return GateResult("DXF_DIMENSIONS_MATCH", "fail", f"{path.name}: missing {missing}")
    return GateResult("DXF_DIMENSIONS_MATCH", "pass", f"{path.name}: dimensions match source")


def validate_dxf_room_dimensions(paths: Path | tuple[Path, ...] | list[Path], project: DrawingProject) -> GateResult:
    all_paths = (paths,) if isinstance(paths, Path) else tuple(paths)
    text = "\n".join(_dxf_text(ezdxf.readfile(path)) for path in all_paths)
    expected: list[str] = []
    for room in project.rooms:
        min_x, min_y, max_x, max_y = _bounds(room.polygon)
        expected.append(f"{format_dimension_m(max_x - min_x)} x {format_dimension_m(max_y - min_y)}")
    found = [label for label in expected if label in text]
    minimum = max(1, int(len(expected) * 0.7))
    if len(found) < minimum:
        return GateResult("DXF_ROOM_DIMENSIONS", "fail", f"found {len(found)}/{len(expected)} room dimension labels")
    return GateResult("DXF_ROOM_DIMENSIONS", "pass", f"{len(found)}/{len(expected)} room dimension labels found")


def validate_dxf_no_raw_internal_strings(paths: Path | tuple[Path, ...] | list[Path]) -> GateResult:
    all_paths = (paths,) if isinstance(paths, Path) else tuple(paths)
    text = "\n".join(_dxf_text(ezdxf.readfile(path)) for path in all_paths)
    hits = _raw_internal_hits(text)
    if hits:
        return GateResult("DXF_NO_RAW_INTERNAL_STRINGS", "fail", "raw/internal strings found: " + ", ".join(hits[:8]))
    return GateResult("DXF_NO_RAW_INTERNAL_STRINGS", "pass", "no raw dict/json/internal operation strings found")


def validate_dxf_room_labels_openings(paths: Path | tuple[Path, ...] | list[Path], project: DrawingProject) -> GateResult:
    all_paths = (paths,) if isinstance(paths, Path) else tuple(paths)
    text = ""
    opening_entities = []
    for path in all_paths:
        doc = ezdxf.readfile(path)
        text += "\n" + _dxf_text(doc)
        opening_entities.extend(
            entity
            for entity in doc.modelspace()
            if getattr(entity.dxf, "layer", "") in {"A-DOOR", "A-GLAZ", "A-DOOR-IDEN"}
        )
    missing_rooms = [room.name for room in project.rooms if room.name not in text]
    if missing_rooms or not opening_entities:
        return GateResult("DXF_ROOM_LABELS_OPENINGS", "fail", f"missing_rooms={missing_rooms[:8]}, opening_entities={len(opening_entities)}")
    return GateResult("DXF_ROOM_LABELS_OPENINGS", "pass", f"{len(project.rooms)} room labels and {len(opening_entities)} opening entities present")


def validate_dxf_sheet_title_blocks(paths: Path | tuple[Path, ...] | list[Path], sheets: tuple | list) -> GateResult:
    all_paths = (paths,) if isinstance(paths, Path) else tuple(paths)
    paths_by_name = {path.name: path for path in all_paths}
    missing: list[str] = []
    for sheet in sheets:
        filename = getattr(sheet, "dxf_filename", None)
        number = getattr(sheet, "number", "")
        title = getattr(sheet, "title", "")
        path = paths_by_name.get(filename) if filename else None
        if path is None or not path.exists():
            missing.append(number or str(filename))
            continue
        text = _dxf_text(ezdxf.readfile(path))
        if number not in text or title not in text:
            missing.append(f"{number} {title}".strip())
    if missing:
        return GateResult("DXF_SHEET_TITLE_BLOCKS", "fail", "missing title block tokens: " + ", ".join(missing[:8]))
    return GateResult("DXF_SHEET_TITLE_BLOCKS", "pass", f"{len(sheets)} DXF sheets carry title block tokens")


def validate_dxf_modelspace_nonempty(paths: Path | tuple[Path, ...] | list[Path]) -> GateResult:
    all_paths = (paths,) if isinstance(paths, Path) else tuple(paths)
    empty: list[str] = []
    for path in all_paths:
        doc = ezdxf.readfile(path)
        if not list(doc.modelspace()):
            empty.append(path.name)
    if empty:
        return GateResult("DXF_MODELSPACE_NONEMPTY", "fail", "empty modelspace sheets: " + ", ".join(empty[:8]))
    return GateResult("DXF_MODELSPACE_NONEMPTY", "pass", f"{len(all_paths)} DXF sheets contain entities")


def validate_dxf_no_stale_golden_labels(paths: Path | tuple[Path, ...] | list[Path], project: DrawingProject) -> GateResult:
    all_paths = (paths,) if isinstance(paths, Path) else tuple(paths)
    text = "\n".join(_dxf_text(ezdxf.readfile(path)) for path in all_paths)
    hits = _stale_golden_hits(text, project)
    if hits:
        return GateResult("DXF_NO_STALE_GOLDEN_LABELS", "fail", f"stale labels found: {', '.join(hits)}")
    return GateResult("DXF_NO_STALE_GOLDEN_LABELS", "pass", "no stale non-source golden dimensions found")


def _bounds(points: tuple[tuple[float, float], ...]) -> tuple[float, float, float, float]:
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return min(xs), min(ys), max(xs), max(ys)


def _raw_internal_hits(text: str) -> list[str]:
    patterns = (
        r"\{'type':",
        r'"type"\s*:',
        r"\{'operation':",
        r"<DecisionValue",
        r"source='",
        r"assumption=",
    )
    hits: list[str] = []
    for pattern in patterns:
        if re.search(pattern, text):
            hits.append(pattern)
    return hits
