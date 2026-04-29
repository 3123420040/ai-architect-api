from __future__ import annotations

from datetime import date
from math import hypot
from typing import Any

from app.services.geometry import LAYER_2_SCHEMA
from app.services.professional_deliverables.drawing_contract import (
    DrawingProject,
    Fixture,
    Opening,
    Room,
    WallSegment,
    validate_project_contract,
)
from app.services.professional_deliverables.deliverable_source_model import (
    ProfessionalDeliverableSourceModel,
    SourceLevelModel,
    SourceSiteModel,
)


class GeometryAdapterError(ValueError):
    pass


ROOM_LABELS = {
    "living": "Phòng khách",
    "living room": "Phòng khách",
    "kitchen": "Bếp và ăn",
    "kitchen + dining": "Bếp và ăn",
    "dining": "Phòng ăn",
    "bedroom": "Phòng ngủ",
    "bathroom": "Vệ sinh",
    "powder": "Vệ sinh",
    "laundry": "Giặt phơi",
    "laundry court": "Sân giặt phơi",
    "circulation": "Sảnh thang",
    "stair hall": "Sảnh thang",
    "landing": "Sảnh thang",
    "terrace": "Sân thượng",
    "roof terrace": "Sân thượng",
    "worship": "Phòng thờ",
    "worship room": "Phòng thờ",
    "family lounge": "Sinh hoạt chung",
}

FIXTURE_KINDS = {
    "sink": "plumbing",
    "basin": "plumbing",
    "toilet": "plumbing",
    "washing_machine": "plumbing",
    "kitchen_counter": "furniture",
    "cooktop": "furniture",
    "plant": "plant",
    "light": "light",
}


def _point(value: Any) -> tuple[float, float]:
    if not isinstance(value, (list, tuple)) or len(value) < 2:
        raise GeometryAdapterError("Geometry point is missing x/y coordinates")
    return (float(value[0]), float(value[1]))


def _polygon(value: Any) -> tuple[tuple[float, float], ...]:
    if not isinstance(value, list) or len(value) < 3:
        raise GeometryAdapterError("Geometry polygon must contain at least 3 points")
    return tuple(_point(point) for point in value)


def _bounds(points: tuple[tuple[float, float], ...]) -> tuple[float, float, float, float]:
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return min(xs), min(ys), max(xs), max(ys)


def _polygon_area(points: tuple[tuple[float, float], ...]) -> float:
    area = 0.0
    for index, point in enumerate(points):
        next_point = points[(index + 1) % len(points)]
        area += point[0] * next_point[1] - next_point[0] * point[1]
    return abs(area) / 2.0


def _polygon_perimeter(points: tuple[tuple[float, float], ...]) -> float:
    perimeter = 0.0
    for index, point in enumerate(points):
        next_point = points[(index + 1) % len(points)]
        perimeter += hypot(next_point[0] - point[0], next_point[1] - point[1])
    return perimeter


def _translate_point(point: tuple[float, float], min_x: float, min_y: float) -> tuple[float, float]:
    return (point[0] - min_x, point[1] - min_y)


def _translate_polygon(points: tuple[tuple[float, float], ...], min_x: float, min_y: float) -> tuple[tuple[float, float], ...]:
    return tuple(_translate_point(point, min_x, min_y) for point in points)


def _floor_for_level(level: str, level_map: dict[str, int]) -> int:
    try:
        return level_map[level]
    except KeyError as exc:
        raise GeometryAdapterError(f"Unsupported or missing floor level: {level}") from exc


def _room_label(room: dict[str, Any]) -> str:
    name = str(room.get("name") or room.get("name_en") or room.get("type") or "Phòng")
    room_type = str(room.get("type") or "").lower()
    key = name.lower()
    if room_type == "bedroom" and "bedroom" in key:
        suffix = key.replace("bedroom", "").strip()
        return f"Phòng ngủ {suffix.upper()}" if suffix else "Phòng ngủ"
    return ROOM_LABELS.get(key) or ROOM_LABELS.get(room_type) or name


def _opening_span(wall: dict[str, Any], position: float, width: float) -> tuple[tuple[float, float], tuple[float, float]]:
    start = _point(wall.get("start"))
    end = _point(wall.get("end"))
    length = hypot(end[0] - start[0], end[1] - start[1])
    if length <= 0:
        raise GeometryAdapterError(f"Wall {wall.get('id')} has zero length")
    half = width / 2
    a = max(0.0, min(length, position - half))
    b = max(0.0, min(length, position + half))
    ux = (end[0] - start[0]) / length
    uy = (end[1] - start[1]) / length
    return ((start[0] + ux * a, start[1] + uy * a), (start[0] + ux * b, start[1] + uy * b))


def _fixture_center_size(fixture: dict[str, Any]) -> tuple[tuple[float, float], tuple[float, float]]:
    if fixture.get("position"):
        center = _point(fixture["position"])
        dimensions = fixture.get("dimensions") or {}
        return center, (float(dimensions.get("width_m") or 0.7), float(dimensions.get("depth_m") or 0.7))
    poly = _polygon(fixture.get("polygon"))
    min_x, min_y, max_x, max_y = _bounds(poly)
    return ((min_x + max_x) / 2, (min_y + max_y) / 2), (max_x - min_x, max_y - min_y)


def _opening_operation_label(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, dict):
        operation_type = str(value.get("type") or value.get("operation") or value.get("mode") or "").strip()
        hinge_side = str(value.get("hinge_side") or value.get("swing") or "").strip()
        sliding = bool(value.get("sliding")) or operation_type == "sliding"
        parts: list[str] = []
        if sliding:
            parts.append("trượt")
        elif operation_type in {"swing", "hinged"}:
            parts.append("mở quay")
        elif operation_type == "fixed":
            parts.append("cố định")
        elif operation_type:
            parts.append(operation_type.replace("_", " "))
        if hinge_side in {"left", "right"}:
            parts.append("bản lề trái" if hinge_side == "left" else "bản lề phải")
        return ", ".join(parts) or None
    text = str(value).strip()
    if not text:
        return None
    return {
        "sliding": "trượt",
        "swing": "mở quay",
        "hinged": "mở quay",
        "fixed": "cố định",
        "fixed_or_sliding": "cố định hoặc trượt",
        "sliding_or_swing": "trượt hoặc mở quay",
        "shaded_louver": "ô thoáng lam che nắng",
        "vent_louver": "ô thoáng thông gió",
    }.get(text, text.replace("_", " "))


def _style(brief_json: dict | None, geometry: dict[str, Any]) -> str:
    return str((brief_json or {}).get("style") or geometry.get("project_info", {}).get("style") or "Modern Minimalist")


def _brief_summary(brief_json: dict | None) -> str | None:
    if not brief_json:
        return None
    for key in ("summary", "brief", "description", "original_text"):
        value = brief_json.get(key)
        if value:
            return str(value)
    return None


def build_professional_deliverable_source_model(
    *,
    project_id: str,
    project_name: str,
    brief_json: dict | None,
    geometry_json: dict | None,
    issue_date: date | None = None,
    version_id: str | None = None,
) -> ProfessionalDeliverableSourceModel:
    if not geometry_json:
        raise GeometryAdapterError("DesignVersion.geometry_json is required for professional deliverables")
    if geometry_json.get("$schema") != LAYER_2_SCHEMA:
        raise GeometryAdapterError("Only ai-architect-geometry-v2 is supported")

    site_boundary = _polygon(geometry_json.get("site", {}).get("boundary"))
    min_x, min_y, max_x, max_y = _bounds(site_boundary)
    normalized_site_boundary = _translate_polygon(site_boundary, min_x, min_y)
    site = geometry_json.get("site", {}) or {}
    raw_levels = [level for level in geometry_json.get("levels", []) if level.get("type") == "floor"]
    if not raw_levels:
        raise GeometryAdapterError("Geometry contains no floor levels")
    levels = tuple(
        SourceLevelModel(
            id=str(level["id"]),
            floor_number=index,
            finished_floor_elevation_m=float(level.get("elevation_m") or level.get("finished_floor_elevation_m") or 0),
            floor_to_floor_height_m=float(level["floor_to_floor_height_m"]) if level.get("floor_to_floor_height_m") is not None else None,
            clear_height_m=float(level["clear_height_m"]) if level.get("clear_height_m") is not None else None,
            slab_thickness_m=float(level["slab_thickness_m"]) if level.get("slab_thickness_m") is not None else None,
        )
        for index, level in enumerate(raw_levels, start=1)
    )

    return ProfessionalDeliverableSourceModel(
        project_id=project_id,
        version_id=version_id or (str(geometry_json.get("version_id")) if geometry_json.get("version_id") else None),
        project_name=project_name,
        issue_date=issue_date or date.today(),
        revision_label=str(geometry_json.get("revision_label") or geometry_json.get("version_label") or "") or None,
        brief_summary=_brief_summary(brief_json),
        concept_note="Bản vẽ khái niệm - không dùng cho thi công",
        site=SourceSiteModel(
            boundary=normalized_site_boundary,
            lot_width_m=max_x - min_x,
            lot_depth_m=max_y - min_y,
            lot_area_m2=float(site.get("area_m2") or _polygon_area(normalized_site_boundary)),
            north_angle_degrees=float(site.get("orientation_north_deg") or site.get("north_angle_degrees") or 0),
            orientation=str(site.get("orientation") or "") or None,
            setbacks=site.get("setbacks") if isinstance(site.get("setbacks"), dict) else None,
            access_points=tuple(_translate_point(_point(point), min_x, min_y) for point in site.get("access_points", []) if isinstance(point, (list, tuple))),
        ),
        levels=levels,
        rooms=tuple(geometry_json.get("rooms", []) or ()),
        walls=tuple(geometry_json.get("walls", []) or ()),
        openings=tuple(geometry_json.get("openings", []) or ()),
        fixtures=tuple(geometry_json.get("fixtures", []) or ()),
        roof=geometry_json.get("roof", {}) or {},
        grid=geometry_json.get("dimensions_config") or geometry_json.get("grid"),
        style=geometry_json.get("materials") or geometry_json.get("style") or None,
    )


def geometry_to_drawing_project(
    *,
    project_id: str,
    project_name: str,
    brief_json: dict | None,
    geometry_json: dict | None,
    issue_date: date | None = None,
    version_id: str | None = None,
) -> DrawingProject:
    source = build_professional_deliverable_source_model(
        project_id=project_id,
        project_name=project_name,
        brief_json=brief_json,
        geometry_json=geometry_json,
        issue_date=issue_date,
        version_id=version_id,
    )
    raw_site_boundary = _polygon(geometry_json.get("site", {}).get("boundary"))
    min_x, min_y, _, _ = _bounds(raw_site_boundary)
    level_map = {level.id: level.floor_number for level in source.levels}
    walls_by_id = {str(wall.get("id")): wall for wall in source.walls}

    rooms = tuple(
        Room(
            id=str(room.get("id")),
            floor=_floor_for_level(str(room.get("level")), level_map),
            name=_room_label(room),
            polygon=_translate_polygon(_polygon(room.get("polygon")), min_x, min_y),
            original_type=str(room.get("type") or "") or None,
            area_m2=float(room["area_m2"]) if room.get("area_m2") is not None else None,
            perimeter_m=float(room["perimeter_m"]) if room.get("perimeter_m") is not None else None,
            category=str(room.get("category") or "") or None,
            finish_set=room.get("finish_set") if isinstance(room.get("finish_set"), dict) else None,
        )
        for room in source.rooms
    )
    walls = tuple(
        WallSegment(
            floor=_floor_for_level(str(wall.get("level")), level_map),
            start=_translate_point(_point(wall.get("start")), min_x, min_y),
            end=_translate_point(_point(wall.get("end")), min_x, min_y),
            layer="S-COLS" if wall.get("structural") else "A-WALL",
            id=str(wall.get("id") or "") or None,
            thickness_m=float(wall["thickness_m"]) if wall.get("thickness_m") is not None else None,
            height_m=float(wall["height_m"]) if wall.get("height_m") is not None else None,
            is_exterior=bool(wall.get("exterior")) if wall.get("exterior") is not None else None,
            structural_category=str(wall.get("structural_category") or "") or None,
        )
        for wall in source.walls
    )
    openings: list[Opening] = []
    for item in source.openings:
        wall = walls_by_id.get(str(item.get("wall_id")))
        if not wall:
            raise GeometryAdapterError(f"Opening {item.get('id')} references missing wall")
        start, end = _opening_span(wall, float(item.get("position_along_wall_m") or 0), float(item.get("width_m") or 0.9))
        start = _translate_point(start, min_x, min_y)
        end = _translate_point(end, min_x, min_y)
        kind = "window" if item.get("type") == "window" else "door"
        openings.append(
            Opening(
                floor=_floor_for_level(str(item.get("level")), level_map),
                kind=kind,
                start=start,
                end=end,
                label=str(item.get("schedule_mark") or item.get("id") or ("W" if kind == "window" else "D")),
                id=str(item.get("id") or "") or None,
                wall_id=str(item.get("wall_id") or "") or None,
                width_m=float(item["width_m"]) if item.get("width_m") is not None else None,
                height_m=float(item["height_m"]) if item.get("height_m") is not None else None,
                sill_height_m=float(item["sill_height_m"]) if item.get("sill_height_m") is not None else None,
                operation=_opening_operation_label(item.get("operation") or item.get("swing")),
            )
        )

    fixtures: list[Fixture] = []
    for item in source.fixtures:
        center, size = _fixture_center_size(item)
        center = _translate_point(center, min_x, min_y)
        raw_type = str(item.get("type") or "furniture")
        fixtures.append(
            Fixture(
                floor=_floor_for_level(str(item.get("level")), level_map),
                kind=FIXTURE_KINDS.get(raw_type, "furniture"),
                center=center,
                size=size,
                label=raw_type.replace("_", " ").title(),
                id=str(item.get("id") or "") or None,
                source_type=raw_type,
                room_id=str(item.get("room_id") or "") or None,
                rotation_degrees=float(item["rotation_degrees"]) if item.get("rotation_degrees") is not None else None,
            )
        )

    roof_outline = source.site.boundary
    terrace_zones = source.roof.get("terrace_zones") or []
    if terrace_zones and isinstance(terrace_zones[0], dict) and terrace_zones[0].get("polygon"):
        roof_outline = _translate_polygon(_polygon(terrace_zones[0]["polygon"]), min_x, min_y)

    project = DrawingProject(
        project_id=source.project_id,
        project_name=source.project_name,
        lot_width_m=source.site.lot_width_m,
        lot_depth_m=source.site.lot_depth_m,
        storeys=len(source.levels),
        style=_style(brief_json, geometry_json),
        issue_date=source.issue_date,
        rooms=rooms,
        walls=walls,
        openings=tuple(openings),
        fixtures=tuple(fixtures),
        roof_outline=roof_outline,
        north_angle_degrees=source.site.north_angle_degrees,
        version_id=source.version_id,
        revision_label=source.revision_label,
        brief_summary=source.brief_summary,
        concept_note=source.concept_note,
        site_boundary=source.site.boundary,
        lot_area_m2=source.site.lot_area_m2,
        orientation=source.site.orientation,
        setbacks=source.site.setbacks,
        access_points=source.site.access_points,
        level_metadata=tuple(level.__dict__ for level in source.levels),
        roof_metadata=source.roof,
        grid_metadata=source.grid,
        style_metadata=source.style,
    )
    try:
        validate_project_contract(project)
    except Exception as exc:
        raise GeometryAdapterError(f"Geometry cannot be converted to DrawingProject: {exc}") from exc
    return project
