from __future__ import annotations

import math

from app.services.professional_deliverables.drawing_contract import DrawingProject, validate_project_contract
from app.services.professional_deliverables.material_registry import GOLDEN_MATERIALS
from app.services.professional_deliverables.scene_contract import BoxMeshElement, SceneContract, validate_scene_contract

FLOOR_HEIGHT_M = 3.2
WALL_HEIGHT_M = 3.0
WALL_THICKNESS_M = 0.18
SLAB_THICKNESS_M = 0.12
ROOF_THICKNESS_M = 0.32


def _segment_length(start: tuple[float, float], end: tuple[float, float]) -> float:
    return math.hypot(end[0] - start[0], end[1] - start[1])


def _segment_center(start: tuple[float, float], end: tuple[float, float]) -> tuple[float, float]:
    return ((start[0] + end[0]) / 2.0, (start[1] + end[1]) / 2.0)


def _segment_angle_degrees(start: tuple[float, float], end: tuple[float, float]) -> float:
    return math.degrees(math.atan2(end[1] - start[1], end[0] - start[0]))


def _floor_base_z(floor: int) -> float:
    return (floor - 1) * FLOOR_HEIGHT_M


def build_scene_from_project(project: DrawingProject) -> SceneContract:
    validate_project_contract(project)
    elements: list[BoxMeshElement] = [
        BoxMeshElement(
            id="site-ground",
            name="Site ground",
            category="site",
            lod=100,
            material_name="MAT_site_ground",
            center_m=(project.lot_width_m / 2.0, project.lot_depth_m / 2.0, -0.035),
            size_m=(project.lot_width_m + 1.2, project.lot_depth_m + 1.2, 0.07),
        )
    ]

    for floor in range(1, project.storeys + 1):
        base_z = _floor_base_z(floor)
        elements.append(
            BoxMeshElement(
                id=f"slab-f{floor}",
                name=f"Slab F{floor}",
                category="slab",
                lod=300,
                material_name="MAT_building_floor",
                center_m=(project.lot_width_m / 2.0, project.lot_depth_m / 2.0, base_z + SLAB_THICKNESS_M / 2.0),
                size_m=(project.lot_width_m, project.lot_depth_m, SLAB_THICKNESS_M),
            )
        )
        for index, wall in enumerate(project.walls_for_floor(floor), start=1):
            center_x, center_y = _segment_center(wall.start, wall.end)
            elements.append(
                BoxMeshElement(
                    id=f"wall-f{floor}-{index:02d}",
                    name=f"Wall F{floor}-{index:02d}",
                    category="wall",
                    lod=300,
                    material_name="MAT_building_wall",
                    center_m=(center_x, center_y, base_z + SLAB_THICKNESS_M + WALL_HEIGHT_M / 2.0),
                    size_m=(_segment_length(wall.start, wall.end), WALL_THICKNESS_M, WALL_HEIGHT_M),
                    rotation_z_degrees=_segment_angle_degrees(wall.start, wall.end),
                )
            )

        for opening in project.openings_for_floor(floor):
            center_x, center_y = _segment_center(opening.start, opening.end)
            length = _segment_length(opening.start, opening.end)
            is_window = opening.kind == "window"
            height = 1.1 if is_window else 2.1
            sill = 1.0 if is_window else 0.0
            material = "MAT_opening_glass" if is_window else "MAT_opening_door"
            elements.append(
                BoxMeshElement(
                    id=f"{opening.label.lower()}-f{floor}",
                    name=f"{opening.kind.title()} {opening.label}",
                    category=opening.kind,
                    lod=300,
                    material_name=material,
                    center_m=(center_x, center_y, base_z + SLAB_THICKNESS_M + sill + height / 2.0),
                    size_m=(length, WALL_THICKNESS_M * 0.7, height),
                    rotation_z_degrees=_segment_angle_degrees(opening.start, opening.end),
                )
            )

        for index, fixture in enumerate(project.fixtures_for_floor(floor), start=1):
            material = {
                "furniture": "MAT_fixture_furniture",
                "plumbing": "MAT_fixture_plumbing",
                "light": "MAT_fixture_plumbing",
                "plant": "MAT_site_vegetation",
            }[fixture.kind]
            height = {
                "furniture": 0.55,
                "plumbing": 0.85,
                "light": 0.12,
                "plant": 1.25,
            }[fixture.kind]
            z_center = base_z + SLAB_THICKNESS_M + (WALL_HEIGHT_M - 0.25 if fixture.kind == "light" else height / 2.0)
            elements.append(
                BoxMeshElement(
                    id=f"fixture-f{floor}-{index:02d}",
                    name=f"{fixture.kind.title()} F{floor}-{index:02d}",
                    category=fixture.kind,
                    lod=200,
                    material_name=material,
                    center_m=(fixture.center[0], fixture.center[1], z_center),
                    size_m=(fixture.size[0], fixture.size[1], height),
                )
            )

    elements.append(
        BoxMeshElement(
            id="roof-main",
            name="Main roof",
            category="roof",
            lod=300,
            material_name="MAT_building_roof",
            center_m=(
                project.lot_width_m / 2.0,
                project.lot_depth_m / 2.0,
                project.storeys * FLOOR_HEIGHT_M + ROOF_THICKNESS_M / 2.0,
            ),
            size_m=(project.lot_width_m + 0.25, project.lot_depth_m + 0.25, ROOF_THICKNESS_M),
        )
    )

    scene = SceneContract(
        project_id=project.project_id,
        project_name=project.project_name,
        elements=tuple(elements),
        materials=GOLDEN_MATERIALS,
    )
    validate_scene_contract(scene)
    return scene
