from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from datetime import date
from typing import Any, Literal

from app.services.design_intelligence.concept_model import (
    ArchitecturalConceptModel,
    ConceptBuildableArea,
    ConceptFacade,
    ConceptFixture,
    ConceptLevel,
    ConceptModelValidationError,
    ConceptOpening,
    ConceptRoom,
    ConceptSectionLine,
    ConceptSite,
    ConceptStair,
    ConceptWall,
    Point,
    validate_concept_model,
)
from app.services.design_intelligence.drawing_package_model import DrawingPackageModel, compile_drawing_package
from app.services.design_intelligence.provenance import DecisionValue, ai_proposal, reviewer_override, rule_default, user_fact
from app.services.geometry import LAYER_2_SCHEMA
from app.services.professional_deliverables.drawing_contract import DrawingProject, Fixture, Opening, Room, WallSegment
from app.services.professional_deliverables.geometry_adapter import GeometryAdapterError, geometry_to_drawing_project


AdapterStatus = Literal["ready", "unsupported", "blocked"]


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
    "ban ve thi cong",
    "ho so xin phep",
    "thiet ke ket cau",
    "thiet ke dien nuoc",
    "dat quy chuan",
)


@dataclass(frozen=True)
class ProductConceptAdapterBlocker:
    code: str
    message: str
    field: str | None = None
    technical_detail: str | None = None

    def as_dict(self) -> dict[str, str | None]:
        return {
            "code": self.code,
            "message": self.message,
            "field": self.field,
            "technical_detail": self.technical_detail,
        }


@dataclass(frozen=True)
class ProductConceptPackageSource:
    project_id: str
    project_name: str
    version_id: str | None
    concept_model: ArchitecturalConceptModel
    drawing_project: DrawingProject
    drawing_package: DrawingPackageModel
    provenance: dict[str, Any]


@dataclass(frozen=True)
class ProductConceptAdapterResult:
    status: AdapterStatus
    source: ProductConceptPackageSource | None = None
    blocker_reasons: tuple[ProductConceptAdapterBlocker, ...] = ()
    fallback_required: bool = False
    fallback_reason: str | None = None

    @property
    def is_ready(self) -> bool:
        return self.status == "ready" and self.source is not None

    @property
    def concept_model(self) -> ArchitecturalConceptModel | None:
        return self.source.concept_model if self.source else None

    @property
    def drawing_project(self) -> DrawingProject | None:
        return self.source.drawing_project if self.source else None

    @property
    def drawing_package(self) -> DrawingPackageModel | None:
        return self.source.drawing_package if self.source else None


def adapt_live_design_version_to_concept_source(
    *,
    project_id: str,
    project_name: str,
    brief_json: dict[str, Any] | None,
    geometry_json: dict[str, Any] | None,
    resolved_style_params: dict[str, Any] | None = None,
    generation_metadata: dict[str, Any] | None = None,
    issue_date: date | None = None,
    version_id: str | None = None,
) -> ProductConceptAdapterResult:
    if not isinstance(geometry_json, dict) or not geometry_json:
        return _blocked("missing_geometry", "DesignVersion.geometry_json is required for Concept 2D package adaptation.", "geometry_json")

    schema = geometry_json.get("$schema")
    if schema != LAYER_2_SCHEMA:
        return _unsupported(
            "unsupported_geometry_schema",
            f"Only {LAYER_2_SCHEMA} can be adapted to the Concept 2D package contract.",
            "geometry_json.$schema",
            technical_detail=str(schema),
        )

    try:
        drawing_project = geometry_to_drawing_project(
            project_id=project_id,
            project_name=project_name,
            brief_json=brief_json,
            geometry_json=geometry_json,
            issue_date=issue_date,
            version_id=version_id,
        )
        concept_model = _concept_model_from_live_geometry(
            project_id=project_id,
            project_name=project_name,
            version_id=version_id or drawing_project.version_id,
            brief_json=brief_json,
            geometry_json=geometry_json,
            resolved_style_params=resolved_style_params,
            generation_metadata=generation_metadata,
            drawing_project=drawing_project,
        )
        validate_concept_model(concept_model)
    except GeometryAdapterError as exc:
        return _blocked("geometry_contract_blocked", "Selected geometry cannot satisfy the Concept 2D package source contract.", "geometry_json", str(exc))
    except (ConceptModelValidationError, ValueError, TypeError, KeyError) as exc:
        return _blocked("concept_contract_blocked", "Selected geometry could not be converted into a valid concept source model.", "geometry_json", str(exc))

    drawing_package = compile_drawing_package(concept_model)
    provenance = _provenance(
        project_id=project_id,
        project_name=project_name,
        version_id=version_id or drawing_project.version_id,
        geometry_json=geometry_json,
        drawing_project=drawing_project,
        concept_model=concept_model,
    )
    return ProductConceptAdapterResult(
        status="ready",
        source=ProductConceptPackageSource(
            project_id=project_id,
            project_name=project_name,
            version_id=version_id or drawing_project.version_id,
            concept_model=concept_model,
            drawing_project=drawing_project,
            drawing_package=drawing_package,
            provenance=provenance,
        ),
    )


def _concept_model_from_live_geometry(
    *,
    project_id: str,
    project_name: str,
    version_id: str | None,
    brief_json: dict[str, Any] | None,
    geometry_json: dict[str, Any],
    resolved_style_params: dict[str, Any] | None,
    generation_metadata: dict[str, Any] | None,
    drawing_project: DrawingProject,
) -> ArchitecturalConceptModel:
    level_id_by_floor, source_level_ids, raw_levels = _level_maps(geometry_json, drawing_project.storeys)
    default_assumptions: list[str] = []
    style_contract = _resolve_style_contract(brief_json, resolved_style_params, generation_metadata, geometry_json)
    site_boundary = drawing_project.site_polygon
    buildable_polygon = _buildable_polygon(drawing_project)
    section_lines = _section_lines(geometry_json)
    levels = _levels(raw_levels, drawing_project, level_id_by_floor, source_level_ids)
    rooms = _rooms(drawing_project.rooms, level_id_by_floor)
    walls = _walls(drawing_project.walls, level_id_by_floor, default_assumptions)
    openings = _openings(drawing_project.openings, level_id_by_floor, default_assumptions)
    stairs = _stairs(geometry_json, source_level_ids)
    fixtures = _fixtures(drawing_project.fixtures, level_id_by_floor)
    assumptions = _adapter_assumptions(style_contract, default_assumptions)

    model = ArchitecturalConceptModel(
        project_id=project_id,
        source_brief=_brief_summary(brief_json),
        concept_status_note="Professional Concept 2D Package - concept only, not for construction.",
        site=ConceptSite(
            boundary=_selected(site_boundary, "Site boundary is preserved from selected DesignVersion.geometry_json."),
            width_m=_selected(float(drawing_project.lot_width_m), "Lot width is preserved from selected DesignVersion.geometry_json."),
            depth_m=_selected(float(drawing_project.lot_depth_m), "Lot depth is preserved from selected DesignVersion.geometry_json."),
            area_m2=_selected(float(drawing_project.display_lot_area_m2), "Lot area is preserved or derived from selected DesignVersion.geometry_json."),
            orientation=_selected(drawing_project.orientation, "Orientation is preserved from selected DesignVersion.geometry_json.") if drawing_project.orientation else None,
            access_edge=_selected("front", "Access edge is derived from selected DesignVersion.geometry_json access/front edge."),
        ),
        buildable_area=ConceptBuildableArea(
            polygon=_selected(buildable_polygon, "Buildable polygon is derived from selected geometry boundary and setbacks."),
            front_setback_m=_selected(_setback_value(drawing_project.setbacks, "front_m"), "Front setback is preserved from selected geometry when present."),
            rear_setback_m=_selected(_setback_value(drawing_project.setbacks, "back_m", "rear_m"), "Rear setback is preserved from selected geometry when present."),
            side_setback_m=_selected(_max_side_setback(drawing_project.setbacks), "Side setback is preserved from selected geometry when present."),
        ),
        levels=levels,
        rooms=rooms,
        walls=walls,
        openings=openings,
        stairs=stairs,
        fixtures=fixtures,
        style=style_contract["style_decision"],
        facade=ConceptFacade(
            style_id=style_contract["style_decision"],
            strategy=ai_proposal(
                style_contract["facade_intent"],
                "Facade intent is copied from live style metadata or project brief and remains concept-only.",
                confidence=style_contract["confidence"],
            ),
        ),
        section_lines=section_lines,
        assumptions=assumptions,
        metadata={
            "live_product_contract": {
                "adapter": "product_concept_adapter",
                "project_name": project_name,
                "version_id": version_id,
                "geometry_authority": "DesignVersion.geometry_json",
                "geometry_schema": geometry_json.get("$schema"),
                "concept_only": True,
                "source_level_ids": source_level_ids,
                "north_angle_degrees": drawing_project.north_angle_degrees,
                "room_count": len(drawing_project.rooms),
                "wall_count": len(drawing_project.walls),
                "opening_count": len(drawing_project.openings),
                "fixture_count": len(drawing_project.fixtures),
            },
            "style_metadata": style_contract["metadata"],
        },
    )
    return model


def _level_maps(geometry_json: dict[str, Any], storeys: int) -> tuple[dict[int, str], dict[str, str], list[dict[str, Any]]]:
    raw_levels = [level for level in geometry_json.get("levels", []) if isinstance(level, dict) and level.get("type") == "floor"]
    if len(raw_levels) != storeys:
        raw_levels = raw_levels[:storeys]
    level_id_by_floor = {floor: f"L{floor}" for floor in range(1, storeys + 1)}
    source_level_ids = {f"L{index}": str(level.get("id") or f"L{index}") for index, level in enumerate(raw_levels, start=1)}
    return level_id_by_floor, source_level_ids, raw_levels


def _levels(raw_levels: list[dict[str, Any]], drawing_project: DrawingProject, level_id_by_floor: dict[int, str], source_level_ids: dict[str, str]) -> tuple[ConceptLevel, ...]:
    levels: list[ConceptLevel] = []
    metadata_by_floor = {
        int(item.get("floor_number")): item
        for item in drawing_project.level_metadata
        if isinstance(item, dict) and item.get("floor_number") is not None
    }
    for floor in range(1, drawing_project.storeys + 1):
        raw = raw_levels[floor - 1] if floor - 1 < len(raw_levels) else {}
        meta = metadata_by_floor.get(floor, {})
        concept_level_id = level_id_by_floor[floor]
        source_level_id = source_level_ids.get(concept_level_id) or str(raw.get("id") or concept_level_id)
        floor_to_floor = _number(raw, "floor_to_floor_height_m", "floor_to_floor_m", default=_number(meta, "floor_to_floor_height_m", default=3.3))
        clear_height = _number(raw, "clear_height_m", "ceiling_height_m", default=_number(meta, "clear_height_m", default=max(floor_to_floor - 0.3, 2.4)))
        levels.append(
            ConceptLevel(
                id=concept_level_id,
                floor_number=floor,
                name=str(raw.get("name") or f"Floor {floor}"),
                finished_floor_elevation_m=_selected(_number(raw, "finished_floor_elevation_m", "elevation_m", default=_number(meta, "finished_floor_elevation_m", default=0.0)), f"Floor {floor} elevation is preserved from source level {source_level_id}."),
                floor_to_floor_height_m=_selected(floor_to_floor, f"Floor {floor} height is preserved from source level {source_level_id} when present."),
                clear_height_m=_selected(clear_height, f"Floor {floor} clear height is preserved from source level {source_level_id} when present."),
            )
        )
    return tuple(levels)


def _rooms(rooms: tuple[Room, ...], level_id_by_floor: dict[int, str]) -> tuple[ConceptRoom, ...]:
    return tuple(
        ConceptRoom(
            id=room.id,
            level_id=level_id_by_floor[room.floor],
            room_type=room.original_type or room.category or "room",
            label_vi=room.name,
            polygon=_selected(room.polygon, f"Room {room.id} polygon is preserved from selected geometry."),
            area_m2=_selected(float(room.display_area_m2), f"Room {room.id} area is preserved or derived from selected geometry."),
            priority=_selected(room.category or "live_geometry", f"Room {room.id} category is preserved from selected geometry when present."),
        )
        for room in rooms
    )


def _walls(walls: tuple[WallSegment, ...], level_id_by_floor: dict[int, str], default_assumptions: list[str]) -> tuple[ConceptWall, ...]:
    concept_walls: list[ConceptWall] = []
    for index, wall in enumerate(walls, start=1):
        thickness = wall.thickness_m
        if thickness is None:
            thickness = 0.2 if wall.is_exterior else 0.12
            default_assumptions.append("Wall thickness is defaulted only where selected geometry omitted wall thickness.")
        height = wall.height_m
        if height is None:
            height = 3.0
            default_assumptions.append("Wall height is defaulted only where selected geometry omitted wall height.")
        wall_id = wall.id or f"WALL-{index:03d}"
        concept_walls.append(
            ConceptWall(
                id=wall_id,
                level_id=level_id_by_floor[wall.floor],
                start=_selected(wall.start, f"Wall {wall_id} start point is preserved from selected geometry."),
                end=_selected(wall.end, f"Wall {wall_id} end point is preserved from selected geometry."),
                thickness_m=_selected(float(thickness), f"Wall {wall_id} thickness comes from selected geometry or visible adapter default."),
                height_m=_selected(float(height), f"Wall {wall_id} height comes from selected geometry or visible adapter default."),
                wall_type=wall.structural_category or ("exterior" if wall.is_exterior else "interior"),
                exterior=bool(wall.is_exterior),
            )
        )
    return tuple(concept_walls)


def _openings(openings: tuple[Opening, ...], level_id_by_floor: dict[int, str], default_assumptions: list[str]) -> tuple[ConceptOpening, ...]:
    concept_openings: list[ConceptOpening] = []
    for index, opening in enumerate(openings, start=1):
        opening_id = opening.id or opening.label or f"OPN-{index:03d}"
        width = opening.width_m
        if width is None:
            width = _distance(opening.start, opening.end) or 0.9
            default_assumptions.append("Opening width is derived from selected opening span where the schedule width is omitted.")
        height = opening.height_m
        if height is None:
            height = 2.1 if opening.kind == "door" else 1.2
            default_assumptions.append("Opening height is defaulted only where selected geometry omitted opening height.")
        concept_openings.append(
            ConceptOpening(
                id=opening_id,
                level_id=level_id_by_floor[opening.floor],
                wall_id=opening.wall_id or "",
                opening_type=opening.kind,
                width_m=_selected(float(width), f"Opening {opening_id} width is preserved or derived from selected geometry."),
                height_m=_selected(float(height), f"Opening {opening_id} height is preserved from selected geometry when present."),
                sill_height_m=_selected(float(opening.sill_height_m), f"Opening {opening_id} sill height is preserved from selected geometry.") if opening.sill_height_m is not None else None,
                operation=_selected(opening.operation or "unspecified", f"Opening {opening_id} operation is preserved from selected geometry when present."),
                start=_selected(opening.start, f"Opening {opening_id} start point is preserved from selected geometry."),
                end=_selected(opening.end, f"Opening {opening_id} end point is preserved from selected geometry."),
            )
        )
    return tuple(concept_openings)


def _fixtures(fixtures: tuple[Fixture, ...], level_id_by_floor: dict[int, str]) -> tuple[ConceptFixture, ...]:
    return tuple(
        ConceptFixture(
            id=fixture.id or f"FIX-{index:03d}",
            level_id=level_id_by_floor[fixture.floor],
            room_id=fixture.room_id,
            fixture_type=fixture.source_type or fixture.kind,
            position=_selected(fixture.center, f"Fixture {fixture.id or index} position is preserved from selected geometry."),
            dimensions_m=_selected(fixture.size, f"Fixture {fixture.id or index} dimensions are preserved from selected geometry."),
            label_vi=fixture.label,
        )
        for index, fixture in enumerate(fixtures, start=1)
    )


def _stairs(geometry_json: dict[str, Any], source_level_ids: dict[str, str]) -> tuple[ConceptStair, ...]:
    concept_by_source = {source_id: concept_id for concept_id, source_id in source_level_ids.items()}
    stairs: list[ConceptStair] = []
    for index, stair in enumerate(geometry_json.get("stairs", []) or [], start=1):
        if not isinstance(stair, dict):
            continue
        raw_polygon = stair.get("footprint") or stair.get("position")
        if not raw_polygon:
            continue
        level_from = concept_by_source.get(str(stair.get("from_level"))) or concept_by_source.get(str(stair.get("level"))) or "L1"
        level_to = concept_by_source.get(str(stair.get("to_level"))) or level_from
        geometry = stair.get("geometry") if isinstance(stair.get("geometry"), dict) else {}
        stairs.append(
            ConceptStair(
                id=str(stair.get("id") or f"STAIR-{index:03d}"),
                level_from=level_from,
                level_to=level_to,
                footprint=_selected(_polygon(raw_polygon), "Stair footprint is preserved from selected geometry."),
                width_m=_selected(float(geometry.get("width_m") or stair.get("width_m") or 1.0), "Stair width is preserved from selected geometry when present."),
                strategy=_selected(str(stair.get("type") or "stair"), "Stair strategy is copied from selected geometry when present."),
            )
        )
    return tuple(stairs)


def _section_lines(geometry_json: dict[str, Any]) -> tuple[ConceptSectionLine, ...]:
    markers = geometry_json.get("markers") if isinstance(geometry_json.get("markers"), dict) else {}
    sections = markers.get("sections") if isinstance(markers, dict) else None
    lines: list[ConceptSectionLine] = []
    for index, section in enumerate(sections or [], start=1):
        if not isinstance(section, dict) or not section.get("start") or not section.get("end"):
            continue
        section_id = str(section.get("id") or f"SEC-{index:03d}")
        lines.append(
            ConceptSectionLine(
                id=section_id,
                label=str(section.get("label") or section_id),
                start=_selected(_point(section["start"]), f"Section line {section_id} start point is preserved from selected geometry."),
                end=_selected(_point(section["end"]), f"Section line {section_id} end point is preserved from selected geometry."),
                intent=_selected(str(section.get("direction") or "section"), f"Section line {section_id} intent is preserved from selected geometry when present."),
            )
        )
    return tuple(lines)


def _resolve_style_contract(
    brief_json: dict[str, Any] | None,
    resolved_style_params: dict[str, Any] | None,
    generation_metadata: dict[str, Any] | None,
    geometry_json: dict[str, Any],
) -> dict[str, Any]:
    brief = brief_json or {}
    resolved = resolved_style_params or {}
    generation = generation_metadata or {}
    decision = generation.get("decision_metadata") if isinstance(generation.get("decision_metadata"), dict) else {}
    strategy = generation.get("option_strategy_profile") if isinstance(generation.get("option_strategy_profile"), dict) else {}
    style_sources = (resolved, generation, decision, strategy, brief, geometry_json.get("project_info") or {})
    style_id, style_origin = _first_text_with_origin(
        style_sources,
        ("style_id", "selected_style_id", "profile_id", "style_profile_id", "style", "style_name"),
    )
    if not style_id:
        style_id = "live_selected_geometry"
        style_origin = "adapter_default"

    style_name = _first_text((resolved, generation, decision, strategy, brief), ("display_name", "style_display_name", "name", "title_vi", "style_label")) or style_id
    facade_intent = _first_text(style_sources, ("facade_intent", "facade_strategy", "facade_strategy_vi", "massing", "option_summary_vi"))
    if not facade_intent:
        facade_intent = "Facade intent follows live style metadata and selected geometry."
    style_notes = _safe_notes(
        (
            *_text_items(resolved.get("style_notes") or resolved.get("drawing_notes") or resolved.get("notes")),
            *_text_items(generation.get("style_notes") or generation.get("drawing_notes")),
            *_text_items(decision.get("fit_reasons")),
            *_text_items(decision.get("strengths")),
        )
    )
    if not style_notes:
        style_notes = (f"Style source: {style_name}.",)
    assumptions = _safe_notes(
        (
            *_text_items(resolved.get("assumptions") or resolved.get("assumption_notes")),
            *_text_items(generation.get("assumptions") or generation.get("assumption_notes")),
            *_text_items(decision.get("caveats")),
            *_text_items(generation.get("degraded_reasons")),
        )
    )
    confidence = _confidence(resolved, generation, decision)
    if style_origin == "brief":
        style_decision: DecisionValue = user_fact(style_id, "Style is copied from Project.brief_json.")
    else:
        style_decision = ai_proposal(style_id, "Style is copied from live resolved style metadata or generation metadata.", confidence=confidence)
    metadata = {
        "style_id": style_id,
        "style_name": style_name,
        "style_origin": style_origin,
        "style_notes": style_notes,
        "drawing_notes": style_notes,
        "facade_intent": facade_intent,
        "facade_strategy": facade_intent,
        "assumptions": assumptions,
        "material_palette": resolved.get("material_palette") if isinstance(resolved.get("material_palette"), dict) else {},
    }
    return {
        "style_decision": style_decision,
        "facade_intent": facade_intent,
        "confidence": confidence,
        "assumptions": assumptions,
        "metadata": metadata,
    }


def _adapter_assumptions(style_contract: dict[str, Any], default_assumptions: list[str]) -> tuple[DecisionValue, ...]:
    notes = [
        *style_contract["assumptions"],
        "Concept package source preserves selected-version geometry; non-geometric style notes remain concept assumptions.",
        *tuple(dict.fromkeys(default_assumptions)),
    ]
    safe_notes = _safe_notes(notes)
    return tuple(rule_default(note, note, confidence=0.76, needs_confirmation=True) for note in safe_notes)


def _provenance(
    *,
    project_id: str,
    project_name: str,
    version_id: str | None,
    geometry_json: dict[str, Any],
    drawing_project: DrawingProject,
    concept_model: ArchitecturalConceptModel,
) -> dict[str, Any]:
    return {
        "project_id": project_id,
        "project_name": project_name,
        "version_id": version_id,
        "geometry_authority": "DesignVersion.geometry_json",
        "geometry_schema": geometry_json.get("$schema"),
        "concept_status": "concept_only",
        "lot_width_m": drawing_project.lot_width_m,
        "lot_depth_m": drawing_project.lot_depth_m,
        "floor_count": drawing_project.storeys,
        "room_count": len(drawing_project.rooms),
        "wall_count": len(drawing_project.walls),
        "opening_count": len(drawing_project.openings),
        "fixture_count": len(drawing_project.fixtures),
        "sheet_count": len(concept_model.levels) + 7,
    }


def _blocked(code: str, message: str, field: str | None = None, technical_detail: str | None = None) -> ProductConceptAdapterResult:
    blocker = ProductConceptAdapterBlocker(code=code, message=message, field=field, technical_detail=technical_detail)
    return ProductConceptAdapterResult(
        status="blocked",
        blocker_reasons=(blocker,),
        fallback_required=True,
        fallback_reason=message,
    )


def _unsupported(code: str, message: str, field: str | None = None, technical_detail: str | None = None) -> ProductConceptAdapterResult:
    blocker = ProductConceptAdapterBlocker(code=code, message=message, field=field, technical_detail=technical_detail)
    return ProductConceptAdapterResult(
        status="unsupported",
        blocker_reasons=(blocker,),
        fallback_required=True,
        fallback_reason=message,
    )


def _selected(value: Any, explanation: str) -> DecisionValue:
    return reviewer_override(value, explanation, confidence=0.96, assumption=False)


def _brief_summary(brief_json: dict[str, Any] | None) -> str:
    brief = brief_json or {}
    for key in ("summary", "brief", "description", "original_text"):
        if brief.get(key):
            return str(brief[key])
    lot = brief.get("lot") if isinstance(brief.get("lot"), dict) else {}
    width = lot.get("width_m")
    depth = lot.get("depth_m")
    floors = brief.get("floors")
    style = brief.get("style")
    parts = []
    if width and depth:
        parts.append(f"lot {width}x{depth}m")
    if floors:
        parts.append(f"{floors} floors")
    if style:
        parts.append(f"style {style}")
    return ", ".join(parts) if parts else "Live selected design version"


def _buildable_polygon(project: DrawingProject) -> tuple[Point, ...]:
    front = _setback_value(project.setbacks, "front_m")
    rear = _setback_value(project.setbacks, "back_m", "rear_m")
    left = _setback_value(project.setbacks, "left_m")
    right = _setback_value(project.setbacks, "right_m")
    width = project.lot_width_m
    depth = project.lot_depth_m
    x1 = min(max(left, 0.0), width)
    x2 = max(min(width - max(right, 0.0), width), x1)
    y1 = min(max(front, 0.0), depth)
    y2 = max(min(depth - max(rear, 0.0), depth), y1)
    if x2 <= x1 or y2 <= y1:
        return project.site_polygon
    return ((x1, y1), (x2, y1), (x2, y2), (x1, y2))


def _setback_value(setbacks: dict | None, *keys: str) -> float:
    if not isinstance(setbacks, dict):
        return 0.0
    for key in keys:
        if setbacks.get(key) is not None:
            return float(setbacks[key])
    return 0.0


def _max_side_setback(setbacks: dict | None) -> float:
    return max(_setback_value(setbacks, "left_m"), _setback_value(setbacks, "right_m"))


def _number(payload: dict[str, Any], *keys: str, default: float) -> float:
    for key in keys:
        if payload.get(key) is not None:
            return float(payload[key])
    return float(default)


def _point(value: Any) -> Point:
    if not isinstance(value, (list, tuple)) or len(value) < 2:
        raise ValueError("Point requires x/y coordinates")
    return (float(value[0]), float(value[1]))


def _polygon(value: Any) -> tuple[Point, ...]:
    if not isinstance(value, (list, tuple)) or len(value) < 3:
        raise ValueError("Polygon requires at least three points")
    return tuple(_point(point) for point in value)


def _distance(start: Point, end: Point) -> float:
    return ((end[0] - start[0]) ** 2 + (end[1] - start[1]) ** 2) ** 0.5


def _first_text(sources: tuple[dict[str, Any], ...], keys: tuple[str, ...]) -> str | None:
    value, _origin = _first_text_with_origin(sources, keys)
    return value


def _first_text_with_origin(sources: tuple[dict[str, Any], ...], keys: tuple[str, ...]) -> tuple[str | None, str | None]:
    origins = ("resolved_style_params", "generation_metadata", "decision_metadata", "option_strategy_profile", "brief", "geometry")
    for origin, source in zip(origins, sources, strict=False):
        if not isinstance(source, dict):
            continue
        for key in keys:
            value = source.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip(), origin
    return None, None


def _text_items(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value.strip(),) if value.strip() else ()
    if isinstance(value, (list, tuple)):
        return tuple(str(item).strip() for item in value if str(item).strip())
    return ()


def _safe_notes(values: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    notes: list[str] = []
    for value in values:
        note = str(value).strip()
        if note and not _has_unsafe_scope_claim(note):
            notes.append(note)
    return tuple(dict.fromkeys(notes))


def _has_unsafe_scope_claim(value: str) -> bool:
    normalized = _normalize_ascii(value)
    return any(term in normalized for term in UNSAFE_SCOPE_CLAIMS)


def _normalize_ascii(value: str) -> str:
    normalized = unicodedata.normalize("NFD", value.lower()).replace("đ", "d")
    without_marks = "".join(character for character in normalized if unicodedata.category(character) != "Mn")
    return " ".join(without_marks.replace("-", " ").replace("_", " ").split())


def _confidence(*sources: dict[str, Any]) -> float:
    for source in sources:
        if not isinstance(source, dict):
            continue
        value = source.get("confidence") or source.get("style_confidence")
        if value is None:
            continue
        try:
            return max(0.0, min(1.0, float(value)))
        except (TypeError, ValueError):
            continue
    return 0.72
