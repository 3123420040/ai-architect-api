from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from math import hypot
from typing import Literal

Point = tuple[float, float]


class DeliverableValidationError(ValueError):
    pass


@dataclass(frozen=True)
class Room:
    id: str
    floor: int
    name: str
    polygon: tuple[Point, ...]
    original_type: str | None = None
    area_m2: float | None = None
    perimeter_m: float | None = None
    category: str | None = None
    finish_set: dict | None = None

    @property
    def center(self) -> Point:
        return (
            sum(point[0] for point in self.polygon) / len(self.polygon),
            sum(point[1] for point in self.polygon) / len(self.polygon),
        )

    @property
    def display_area_m2(self) -> float:
        if self.area_m2 is not None and self.area_m2 > 0:
            return self.area_m2
        area = 0.0
        points = list(self.polygon)
        for index, point in enumerate(points):
            next_point = points[(index + 1) % len(points)]
            area += point[0] * next_point[1] - next_point[0] * point[1]
        return abs(area) / 2.0

    @property
    def display_perimeter_m(self) -> float:
        if self.perimeter_m is not None and self.perimeter_m > 0:
            return self.perimeter_m
        perimeter = 0.0
        points = list(self.polygon)
        for index, point in enumerate(points):
            next_point = points[(index + 1) % len(points)]
            perimeter += hypot(next_point[0] - point[0], next_point[1] - point[1])
        return perimeter


@dataclass(frozen=True)
class WallSegment:
    floor: int
    start: Point
    end: Point
    layer: str = "A-WALL"
    id: str | None = None
    thickness_m: float | None = None
    height_m: float | None = None
    is_exterior: bool | None = None
    structural_category: str | None = None


@dataclass(frozen=True)
class Opening:
    floor: int
    kind: Literal["door", "window"]
    start: Point
    end: Point
    label: str
    id: str | None = None
    wall_id: str | None = None
    width_m: float | None = None
    height_m: float | None = None
    sill_height_m: float | None = None
    operation: str | None = None


@dataclass(frozen=True)
class Fixture:
    floor: int
    kind: Literal["furniture", "plumbing", "light", "plant"]
    center: Point
    size: Point
    label: str
    id: str | None = None
    source_type: str | None = None
    room_id: str | None = None
    rotation_degrees: float | None = None


@dataclass(frozen=True)
class SheetSpec:
    number: str
    title: str
    filename_stem: str
    kind: Literal[
        "cover_index",
        "site",
        "floorplan",
        "elevations",
        "sections",
        "room_area_schedule",
        "door_window_schedule",
        "assumptions_style_notes",
    ]
    floor: int | None = None
    scale: str = "1:100"

    @property
    def dxf_filename(self) -> str:
        return f"{self.filename_stem}.dxf"

    @property
    def dwg_filename(self) -> str:
        return f"{self.filename_stem}.dwg"


@dataclass(frozen=True)
class DrawingProject:
    project_id: str
    project_name: str
    lot_width_m: float
    lot_depth_m: float
    storeys: int
    style: str
    issue_date: date
    rooms: tuple[Room, ...]
    walls: tuple[WallSegment, ...]
    openings: tuple[Opening, ...]
    fixtures: tuple[Fixture, ...]
    roof_outline: tuple[Point, ...]
    north_angle_degrees: float = 0.0
    version_id: str | None = None
    revision_label: str | None = None
    brief_summary: str | None = None
    concept_note: str = "Bản vẽ khái niệm - không dùng cho thi công"
    site_boundary: tuple[Point, ...] = field(default_factory=tuple)
    lot_area_m2: float | None = None
    orientation: str | None = None
    setbacks: dict | None = None
    access_points: tuple[Point, ...] = field(default_factory=tuple)
    level_metadata: tuple[dict, ...] = field(default_factory=tuple)
    roof_metadata: dict | None = None
    grid_metadata: dict | None = None
    style_metadata: dict | None = None

    def rooms_for_floor(self, floor: int) -> tuple[Room, ...]:
        return tuple(room for room in self.rooms if room.floor == floor)

    def walls_for_floor(self, floor: int) -> tuple[WallSegment, ...]:
        return tuple(wall for wall in self.walls if wall.floor == floor)

    def openings_for_floor(self, floor: int) -> tuple[Opening, ...]:
        return tuple(opening for opening in self.openings if opening.floor == floor)

    def fixtures_for_floor(self, floor: int) -> tuple[Fixture, ...]:
        return tuple(fixture for fixture in self.fixtures if fixture.floor == floor)

    @property
    def site_polygon(self) -> tuple[Point, ...]:
        if self.site_boundary:
            return self.site_boundary
        return ((0.0, 0.0), (self.lot_width_m, 0.0), (self.lot_width_m, self.lot_depth_m), (0.0, self.lot_depth_m))

    @property
    def display_lot_area_m2(self) -> float:
        if self.lot_area_m2 is not None and self.lot_area_m2 > 0:
            return self.lot_area_m2
        area = 0.0
        points = list(self.site_polygon)
        for index, point in enumerate(points):
            next_point = points[(index + 1) % len(points)]
            area += point[0] * next_point[1] - next_point[0] * point[1]
        return abs(area) / 2.0


def validate_project_contract(project: DrawingProject) -> None:
    if project.lot_width_m <= 0 or project.lot_depth_m <= 0:
        raise DeliverableValidationError("Project lot dimensions must be positive")
    if project.storeys < 1:
        raise DeliverableValidationError("Project must contain at least one floor")
    if len(project.roof_outline) < 4:
        raise DeliverableValidationError("Project roof outline is required before 2D export")
    for floor in range(1, project.storeys + 1):
        if not project.rooms_for_floor(floor):
            raise DeliverableValidationError(f"Floor F{floor} has no rooms")
        if not project.walls_for_floor(floor):
            raise DeliverableValidationError(f"Floor F{floor} has no wall geometry")
    for room in project.rooms:
        if len(room.polygon) < 3:
            raise DeliverableValidationError(f"Room {room.id} polygon is incomplete")
