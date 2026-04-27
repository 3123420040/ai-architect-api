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


def _style(brief_json: dict | None, geometry: dict[str, Any]) -> str:
    return str((brief_json or {}).get("style") or geometry.get("project_info", {}).get("style") or "Modern Minimalist")


def geometry_to_drawing_project(
    *,
    project_id: str,
    project_name: str,
    brief_json: dict | None,
    geometry_json: dict | None,
    issue_date: date | None = None,
) -> DrawingProject:
    if not geometry_json:
        raise GeometryAdapterError("DesignVersion.geometry_json is required for professional deliverables")
    if geometry_json.get("$schema") != LAYER_2_SCHEMA:
        raise GeometryAdapterError("Only ai-architect-geometry-v2 is supported")

    levels = [level for level in geometry_json.get("levels", []) if level.get("type") == "floor"]
    if not levels:
        raise GeometryAdapterError("Geometry contains no floor levels")
    level_map = {str(level["id"]): index for index, level in enumerate(levels, start=1)}

    site_boundary = _polygon(geometry_json.get("site", {}).get("boundary"))
    min_x, min_y, max_x, max_y = _bounds(site_boundary)
    walls_by_id = {str(wall.get("id")): wall for wall in geometry_json.get("walls", [])}

    rooms = tuple(
        Room(
            id=str(room.get("id")),
            floor=_floor_for_level(str(room.get("level")), level_map),
            name=_room_label(room),
            polygon=_polygon(room.get("polygon")),
        )
        for room in geometry_json.get("rooms", [])
    )
    walls = tuple(
        WallSegment(
            floor=_floor_for_level(str(wall.get("level")), level_map),
            start=_point(wall.get("start")),
            end=_point(wall.get("end")),
            layer="S-COLS" if wall.get("structural") else "A-WALL",
        )
        for wall in geometry_json.get("walls", [])
    )
    openings: list[Opening] = []
    for item in geometry_json.get("openings", []):
        wall = walls_by_id.get(str(item.get("wall_id")))
        if not wall:
            raise GeometryAdapterError(f"Opening {item.get('id')} references missing wall")
        start, end = _opening_span(wall, float(item.get("position_along_wall_m") or 0), float(item.get("width_m") or 0.9))
        kind = "window" if item.get("type") == "window" else "door"
        openings.append(
            Opening(
                floor=_floor_for_level(str(item.get("level")), level_map),
                kind=kind,
                start=start,
                end=end,
                label=str(item.get("schedule_mark") or item.get("id") or ("W" if kind == "window" else "D")),
            )
        )

    fixtures: list[Fixture] = []
    for item in geometry_json.get("fixtures", []):
        center, size = _fixture_center_size(item)
        raw_type = str(item.get("type") or "furniture")
        fixtures.append(
            Fixture(
                floor=_floor_for_level(str(item.get("level")), level_map),
                kind=FIXTURE_KINDS.get(raw_type, "furniture"),
                center=center,
                size=size,
                label=raw_type.replace("_", " ").title(),
            )
        )

    roof_outline = site_boundary
    terrace_zones = geometry_json.get("roof", {}).get("terrace_zones") or []
    if terrace_zones and isinstance(terrace_zones[0], dict) and terrace_zones[0].get("polygon"):
        roof_outline = _polygon(terrace_zones[0]["polygon"])

    project = DrawingProject(
        project_id=project_id,
        project_name=project_name,
        lot_width_m=max_x - min_x,
        lot_depth_m=max_y - min_y,
        storeys=len(levels),
        style=_style(brief_json, geometry_json),
        issue_date=issue_date or date.today(),
        rooms=rooms,
        walls=walls,
        openings=tuple(openings),
        fixtures=tuple(fixtures),
        roof_outline=roof_outline,
        north_angle_degrees=float(geometry_json.get("site", {}).get("orientation_north_deg") or 0),
    )
    try:
        validate_project_contract(project)
    except Exception as exc:
        raise GeometryAdapterError(f"Geometry cannot be converted to DrawingProject: {exc}") from exc
    return project
