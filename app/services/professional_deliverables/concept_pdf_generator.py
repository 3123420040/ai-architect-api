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
        style=str(concept_model.style.value) if concept_model.style else "concept",
        issue_date=date.today(),
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
            sheets.append(SheetSpec(sheet.number, sheet.title, "A-603-assumptions-style-notes", "assumptions_style_notes", scale=sheet.scale))
    return tuple(sheets)


def _style_metadata(concept_model: ArchitecturalConceptModel) -> dict:
    style_id = str(concept_model.style.value) if concept_model.style else None
    live_style = _live_style_metadata(concept_model)
    metadata = {
        "style_id": style_id,
        "style_display_name": live_style.get("style_name") or live_style.get("display_name"),
        "facade_strategy": live_style.get("facade_strategy") or live_style.get("facade_intent") or (concept_model.facade.strategy.value if concept_model.facade else None),
        "facade_intent": live_style.get("facade_intent"),
        "assumptions": tuple(assumption.customer_visible_explanation for assumption in concept_model.assumptions),
        "drawing_notes": _as_tuple(live_style.get("drawing_notes") or live_style.get("style_notes")),
        "material_palette": live_style.get("material_palette") if isinstance(live_style.get("material_palette"), dict) else {},
    }
    if not style_id:
        return metadata
    try:
        profile = StyleKnowledgeBase.load_default().get(style_id)
    except StyleKnowledgeError:
        return metadata
    return {
        **metadata,
        "style_display_name": metadata.get("style_display_name") or profile.display_name,
        "facade_intent": metadata.get("facade_intent") or profile.facade_intent,
        "drawing_notes": metadata.get("drawing_notes") or profile.drawing_notes,
        "material_palette": metadata.get("material_palette") or profile.material_palette,
        "drawing_rules": profile.drawing_rules,
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
        operation=str(opening.operation.value),
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


def _as_tuple(value) -> tuple:
    if isinstance(value, tuple):
        return value
    if isinstance(value, list):
        return tuple(item for item in value if item)
    if isinstance(value, str) and value.strip():
        return (value.strip(),)
    return ()
