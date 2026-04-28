from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

from app.services.professional_deliverables.drawing_contract import Point


@dataclass(frozen=True)
class SourceSiteModel:
    boundary: tuple[Point, ...]
    lot_width_m: float
    lot_depth_m: float
    lot_area_m2: float
    north_angle_degrees: float
    orientation: str | None = None
    setbacks: dict[str, Any] | None = None
    access_points: tuple[Point, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class SourceLevelModel:
    id: str
    floor_number: int
    finished_floor_elevation_m: float
    floor_to_floor_height_m: float | None = None
    clear_height_m: float | None = None
    slab_thickness_m: float | None = None


@dataclass(frozen=True)
class ProfessionalDeliverableSourceModel:
    project_id: str
    version_id: str | None
    project_name: str
    issue_date: date
    revision_label: str | None
    brief_summary: str | None
    concept_note: str
    site: SourceSiteModel
    levels: tuple[SourceLevelModel, ...]
    rooms: tuple[dict[str, Any], ...]
    walls: tuple[dict[str, Any], ...]
    openings: tuple[dict[str, Any], ...]
    fixtures: tuple[dict[str, Any], ...]
    roof: dict[str, Any]
    grid: dict[str, Any] | None = None
    style: dict[str, Any] | None = None

