from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

from app.services.design_intelligence.concept_model import ArchitecturalConceptModel, ConceptWall, Point
from app.services.design_intelligence.drawing_package_model import DrawingPackageModel, compile_drawing_package
from app.services.professional_deliverables.demo import Sprint1BundleResult, generate_project_2d_bundle
from app.services.professional_deliverables.drawing_contract import DrawingProject, Fixture, Opening, Room, SheetSpec, WallSegment
from app.services.professional_deliverables.style_knowledge import StyleKnowledgeBase, StyleKnowledgeError


@dataclass(frozen=True)
class Concept2DRenderResult:
    drawing_package: DrawingPackageModel
    drawing_project: DrawingProject
    bundle: Sprint1BundleResult


def render_concept_2d_package(
    concept_model: ArchitecturalConceptModel,
    output_root: Path,
    *,
    project_name: str = "AI Concept 2D",
    require_dwg: bool = False,
) -> Concept2DRenderResult:
    package = compile_drawing_package(concept_model)
    drawing_project = concept_model_to_drawing_project(concept_model, project_name=project_name)
    bundle = generate_project_2d_bundle(
        drawing_project,
        output_root,
        require_dwg=require_dwg,
        sheets=concept_sheet_specs(package),
        concept_package_metadata=_standalone_concept_package_metadata(package),
    )
    return Concept2DRenderResult(drawing_package=package, drawing_project=drawing_project, bundle=bundle)


def concept_model_to_drawing_project(concept_model: ArchitecturalConceptModel, *, project_name: str = "AI Concept 2D") -> DrawingProject:
    rooms = tuple(
        Room(
            id=room.id,
            floor=_floor_number(room.level_id),
            name=room.label_vi,
            polygon=tuple(room.polygon.value),
            original_type=room.room_type,
            area_m2=float(room.area_m2.value),
            category=room.priority.value,
        )
        for room in concept_model.rooms
    )
    walls = tuple(
        WallSegment(
            floor=_floor_number(wall.level_id),
            start=wall.start.value,
            end=wall.end.value,
            id=wall.id,
            thickness_m=float(wall.thickness_m.value),
            height_m=float(wall.height_m.value),
            is_exterior=wall.exterior,
            layer="A-WALL",
        )
        for wall in concept_model.walls
    )
    wall_lookup = {wall.id: wall for wall in concept_model.walls}
    openings = tuple(_to_drawing_opening(opening, wall_lookup) for opening in concept_model.openings)
    fixtures = tuple(
        Fixture(
            floor=_floor_number(fixture.level_id),
            kind=_fixture_kind(fixture.fixture_type),
            center=fixture.position.value,
            size=fixture.dimensions_m.value,
            label=fixture.label_vi,
            id=fixture.id,
            source_type=fixture.fixture_type,
            room_id=fixture.room_id,
        )
        for fixture in concept_model.fixtures
    )
    site_boundary = tuple(concept_model.site.boundary.value)
    return DrawingProject(
        project_id=concept_model.project_id,
        project_name=project_name,
        lot_width_m=float(concept_model.site.width_m.value),
        lot_depth_m=float(concept_model.site.depth_m.value),
        storeys=len(concept_model.levels),
        style=_style_display_label(concept_model),
        issue_date=date.today(),
        version_id=str(concept_model.metadata.get("child_version_id") or concept_model.metadata.get("version_id") or "") or None,
        revision_label=_revision_label(concept_model),
        rooms=rooms,
        walls=walls,
        openings=openings,
        fixtures=fixtures,
        roof_outline=site_boundary,
        site_boundary=site_boundary,
        lot_area_m2=float(concept_model.site.area_m2.value),
        concept_note="Bản vẽ khái niệm - không dùng cho thi công",
        brief_summary=concept_model.source_brief,
        level_metadata=tuple(level.__dict__ for level in concept_model.levels),
        style_metadata=_style_metadata(concept_model),
    )


def _concept_sheet_specs(package: DrawingPackageModel) -> tuple[SheetSpec, ...]:
    return concept_sheet_specs(package)


def concept_sheet_specs(package: DrawingPackageModel) -> tuple[SheetSpec, ...]:
    sheets: list[SheetSpec] = []
    for sheet in package.sheets:
        if sheet.kind == "cover_index":
            sheets.append(SheetSpec(sheet.number, sheet.title, "A-000-cover-index", "cover_index", scale=sheet.scale))
        elif sheet.kind == "site":
            sheets.append(SheetSpec(sheet.number, sheet.title, "A-100-site", "site", scale=sheet.scale))
        elif sheet.kind == "floorplan":
            floor = int(sheet.number.split("-F")[-1])
            sheets.append(SheetSpec(sheet.number, sheet.title, f"{sheet.number}-floorplan", "floorplan", floor=floor, scale=sheet.scale))
        elif sheet.kind == "elevations":
            sheets.append(SheetSpec(sheet.number, sheet.title, "A-201-elevations", "elevations", scale=sheet.scale))
        elif sheet.kind == "sections":
            sheets.append(SheetSpec(sheet.number, sheet.title, "A-301-sections", "sections", scale=sheet.scale))
        elif sheet.kind == "room_area_schedule":
            sheets.append(SheetSpec(sheet.number, sheet.title, "A-601-room-area-schedule", "room_area_schedule", scale=sheet.scale))
        elif sheet.kind == "door_window_schedule":
            sheets.append(SheetSpec(sheet.number, sheet.title, "A-602-door-window-schedule", "door_window_schedule", scale=sheet.scale))
        elif sheet.kind == "assumptions_style_notes":
            sheets.append(SheetSpec(sheet.number, sheet.title, "A-901-assumptions-style-notes", "assumptions_style_notes", scale=sheet.scale))
    return tuple(sheets)


def _standalone_concept_package_metadata(package: DrawingPackageModel) -> dict:
    sheets = [
        {
            "sheet_number": sheet.number,
            "sheet_title": sheet.title,
            "sheet_kind": sheet.kind,
            "readiness": "ready",
            "state": "ready",
            "filename": spec.filename_stem + ".dxf",
        }
        for sheet, spec in zip(package.sheets, concept_sheet_specs(package), strict=True)
    ]
    metadata = {
        "enabled": True,
        "readiness": "ready",
        "readiness_label": "Concept 2D technical-ready; market presentation depends on visual QA gates.",
        "technical_ready": True,
        "concept_review_ready": True,
        "market_presentation_ready": False,
        "construction_ready": False,
        "fallback_reason": None,
        "source": "standalone_concept_renderer",
        "sheet_count": len(sheets),
        "sheets": sheets,
        "qa_bounds": package.qa_bounds,
    }
    if package.qa_bounds.get("revision"):
        metadata["revision"] = package.qa_bounds["revision"]
    return metadata


def _style_metadata(concept_model: ArchitecturalConceptModel) -> dict:
    style_id = str(concept_model.style.value) if concept_model.style else None
    live_style = _live_style_metadata(concept_model)
    facade_material_notes = _facade_material_notes(concept_model)
    metadata = {
        "style_id": style_id,
        "style_display_name": live_style.get("style_name") or live_style.get("display_name"),
        "customer_style_label": _style_display_label(concept_model),
        "facade_strategy": live_style.get("facade_strategy") or live_style.get("facade_intent") or (concept_model.facade.strategy.value if concept_model.facade else None),
        "facade_intent": live_style.get("facade_intent"),
        "assumptions": tuple(
            dict.fromkeys(
                (
                    *(assumption.customer_visible_explanation for assumption in concept_model.assumptions),
                    *_revision_notes(concept_model),
                )
            )
        ),
        "drawing_notes": _as_tuple(live_style.get("drawing_notes") or live_style.get("style_notes")),
        "material_palette": live_style.get("material_palette") if isinstance(live_style.get("material_palette"), dict) else {},
        "material_assumptions": _as_tuple(live_style.get("material_assumptions")) or facade_material_notes,
        "facade_rules": live_style.get("facade_rules") if isinstance(live_style.get("facade_rules"), dict) else {},
        "facade_expression": live_style.get("facade_expression") if isinstance(live_style.get("facade_expression"), dict) else {},
        "suppressed_style_features": tuple(live_style.get("suppressed_style_features") or ()),
        "reference_style_hints": tuple(live_style.get("reference_style_hints") or ()),
        "reference_descriptor_signals": tuple(live_style.get("reference_descriptor_signals") or ()),
        "dislike_signals": tuple(live_style.get("dislike_signals") or ()),
        "style_provenance": live_style.get("style_provenance") if isinstance(live_style.get("style_provenance"), dict) else {},
    }
    if not style_id:
        return metadata
    try:
        profile = StyleKnowledgeBase.load_default().get(style_id)
    except StyleKnowledgeError:
        return metadata
    drawing_notes = tuple(
        dict.fromkeys(
            (
                *_as_tuple(metadata.get("drawing_notes")),
                *profile.drawing_notes,
                *facade_material_notes,
                *_feature_notes(metadata.get("suppressed_style_features")),
                *_feature_notes(metadata.get("reference_style_hints")),
            )
        )
    )
    material_assumptions = _as_tuple(metadata.get("material_assumptions")) or profile.material_assumptions
    provenance = dict(metadata.get("style_provenance") or {})
    provenance.setdefault("facade_expression", {"source": "style_profile", "style_id": profile.style_id, "assumption": True})
    provenance.setdefault("material_palette", {"source": "style_profile", "style_id": profile.style_id, "assumption": True})
    return {
        **metadata,
        "style_display_name": metadata.get("style_display_name") or profile.display_name,
        "facade_intent": metadata.get("facade_intent") or profile.facade_intent,
        "drawing_notes": drawing_notes,
        "material_palette": metadata.get("material_palette") or profile.material_palette,
        "material_assumptions": material_assumptions,
        "drawing_rules": profile.drawing_rules,
        "facade_rules": metadata.get("facade_rules") or profile.facade_rules,
        "facade_expression": metadata.get("facade_expression") or profile.facade_expression,
        "style_provenance": provenance,
    }


def _to_drawing_opening(opening, wall_lookup: dict[str, ConceptWall]) -> Opening:
    wall = wall_lookup[opening.wall_id]
    width = float(opening.width_m.value)
    if opening.start and opening.end:
        start, end = opening.start.value, opening.end.value
    else:
        start, end = _centered_span(wall.start.value, wall.end.value, width)
    return Opening(
        floor=_floor_number(opening.level_id),
        kind="window" if opening.opening_type == "window" else "door",
        start=start,
        end=end,
        label=opening.id.upper(),
        id=opening.id,
        wall_id=opening.wall_id,
        width_m=width,
        height_m=float(opening.height_m.value),
        sill_height_m=float(opening.sill_height_m.value) if opening.sill_height_m else None,
        operation=_operation_display_label(opening.operation.value),
    )


def _centered_span(start: Point, end: Point, width: float) -> tuple[Point, Point]:
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    length = (dx * dx + dy * dy) ** 0.5
    if length <= 0:
        return start, end
    span = min(width, length)
    offset = (length - span) / 2.0
    ux = dx / length
    uy = dy / length
    return ((start[0] + ux * offset, start[1] + uy * offset), (start[0] + ux * (offset + span), start[1] + uy * (offset + span)))


def _floor_number(level_id: str) -> int:
    return int(str(level_id).replace("L", ""))


def _fixture_kind(fixture_type: str) -> str:
    if fixture_type in {"toilet", "sink", "basin"}:
        return "plumbing"
    if fixture_type in {"plant", "tree"}:
        return "plant"
    return "furniture"


def _live_style_metadata(concept_model: ArchitecturalConceptModel) -> dict:
    metadata = concept_model.metadata.get("style_metadata") if isinstance(concept_model.metadata, dict) else None
    return metadata if isinstance(metadata, dict) else {}


def _revision_label(concept_model: ArchitecturalConceptModel) -> str | None:
    summary = concept_model.metadata.get("revision_summary") if isinstance(concept_model.metadata, dict) else None
    if not isinstance(summary, dict):
        return None
    parent = summary.get("parent_version_id")
    child = summary.get("child_version_id")
    if parent and child:
        return f"Revision from {parent} to {child}"
    return "Client revision"


def _revision_notes(concept_model: ArchitecturalConceptModel) -> tuple[str, ...]:
    metadata = concept_model.metadata if isinstance(concept_model.metadata, dict) else {}
    changelog = tuple(str(item) for item in metadata.get("customer_changelog") or () if str(item).strip())
    summary = metadata.get("revision_summary") if isinstance(metadata.get("revision_summary"), dict) else {}
    changed_fields = tuple(str(item) for item in summary.get("changed_fields") or () if str(item).strip())
    notes = [f"Revision change: {item}" for item in changelog]
    if changed_fields:
        notes.append("Revision trace: changed fields - " + ", ".join(changed_fields[:8]))
    if summary:
        notes.append("Revision preservation: original lot geometry, floor count, required rooms, and concept-only status remain traceable unless explicitly changed.")
    return tuple(dict.fromkeys(notes))


def _as_tuple(value) -> tuple:
    if isinstance(value, tuple):
        return value
    if isinstance(value, list):
        return tuple(item for item in value if item)
    if isinstance(value, str) and value.strip():
        return (value.strip(),)
    return ()


def _facade_material_notes(concept_model: ArchitecturalConceptModel) -> tuple[str, ...]:
    if not concept_model.facade:
        return ()
    return tuple(note.customer_visible_explanation for note in concept_model.facade.material_notes)


def _feature_notes(value) -> tuple[str, ...]:
    notes: list[str] = []
    for item in value or ():
        if not isinstance(item, dict):
            continue
        note = item.get("drawing_note") or item.get("note") or item.get("material_note")
        if note:
            notes.append(str(note))
    return tuple(notes)


def _style_display_label(concept_model: ArchitecturalConceptModel) -> str:
    style_id = str(concept_model.style.value) if concept_model.style else ""
    live_style = _live_style_metadata(concept_model)
    explicit = live_style.get("customer_style_label") or live_style.get("style_display_name") or live_style.get("style_name")
    try:
        profile = StyleKnowledgeBase.load_default().get(style_id)
    except StyleKnowledgeError:
        if explicit:
            return str(explicit)
        return style_id.replace("_", " ").title() if style_id else "Concept style"
    english = {
        "minimal_warm": "Modern Minimalist",
        "modern_tropical": "Modern Tropical",
        "indochine_soft": "Indochine Soft",
    }.get(profile.style_id, profile.display_name)
    return f"{english} / {profile.display_name}"


def _operation_display_label(value) -> str:
    if value is None:
        return "concept"
    if isinstance(value, dict):
        operation_type = str(value.get("type") or value.get("operation") or value.get("mode") or "").strip()
        hinge_side = str(value.get("hinge_side") or value.get("swing") or "").strip()
        parts: list[str] = []
        if operation_type == "sliding" or value.get("sliding"):
            parts.append("trượt")
        elif operation_type in {"swing", "hinged"}:
            parts.append("mở quay")
        elif operation_type == "fixed":
            parts.append("cố định")
        elif operation_type:
            parts.append(operation_type.replace("_", " "))
        if hinge_side in {"left", "right"}:
            parts.append("bản lề trái" if hinge_side == "left" else "bản lề phải")
        return ", ".join(parts) or "concept"
    text = str(value).strip()
    if not text:
        return "concept"
    return {
        "sliding": "trượt",
        "swing": "mở quay",
        "hinged": "mở quay",
        "fixed": "cố định",
        "fixed_or_sliding": "cố định hoặc trượt",
        "sliding_or_swing": "trượt hoặc mở quay",
        "shaded_louver": "lam che nắng",
        "vent_louver": "ô thoáng thông gió",
        "screened_reduced_glass": "màn/lam giảm kính",
        "shuttered_screen": "shutter/màn nhẹ",
        "unspecified": "concept",
    }.get(text, text.replace("_", " "))
