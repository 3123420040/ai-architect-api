from __future__ import annotations

from dataclasses import dataclass
from datetime import date
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

    @property
    def center(self) -> Point:
        return (
            sum(point[0] for point in self.polygon) / len(self.polygon),
            sum(point[1] for point in self.polygon) / len(self.polygon),
        )


@dataclass(frozen=True)
class WallSegment:
    floor: int
    start: Point
    end: Point
    layer: str = "A-WALL"


@dataclass(frozen=True)
class Opening:
    floor: int
    kind: Literal["door", "window"]
    start: Point
    end: Point
    label: str


@dataclass(frozen=True)
class Fixture:
    floor: int
    kind: Literal["furniture", "plumbing", "light", "plant"]
    center: Point
    size: Point
    label: str


@dataclass(frozen=True)
class SheetSpec:
    number: str
    title: str
    filename_stem: str
    kind: Literal["site", "floorplan", "elevations", "sections"]
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

    def rooms_for_floor(self, floor: int) -> tuple[Room, ...]:
        return tuple(room for room in self.rooms if room.floor == floor)

    def walls_for_floor(self, floor: int) -> tuple[WallSegment, ...]:
        return tuple(wall for wall in self.walls if wall.floor == floor)

    def openings_for_floor(self, floor: int) -> tuple[Opening, ...]:
        return tuple(opening for opening in self.openings if opening.floor == floor)

    def fixtures_for_floor(self, floor: int) -> tuple[Fixture, ...]:
        return tuple(fixture for fixture in self.fixtures if fixture.floor == floor)


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

