from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from math import ceil
from typing import Any


LAYER_2_SCHEMA = "ai-architect-geometry-v2"


def _round(value: float) -> float:
    return round(float(value), 3)


def _polygon(x1: float, y1: float, x2: float, y2: float) -> list[list[float]]:
    return [
        [_round(x1), _round(y1)],
        [_round(x2), _round(y1)],
        [_round(x2), _round(y2)],
        [_round(x1), _round(y2)],
    ]


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def _area_from_polygon(polygon: list[list[float]]) -> float:
    points = polygon + [polygon[0]]
    total = 0.0
    for start, end in zip(points, points[1:]):
        total += (start[0] * end[1]) - (end[0] * start[1])
    return abs(total) / 2


def _perimeter_from_polygon(polygon: list[list[float]]) -> float:
    points = polygon + [polygon[0]]
    total = 0.0
    for start, end in zip(points, points[1:]):
        total += ((end[0] - start[0]) ** 2 + (end[1] - start[1]) ** 2) ** 0.5
    return total


def _style_material(style: str) -> dict[str, str]:
    style_key = (style or "modern_minimalist").lower()
    if "tropical" in style_key:
        return {
            "facade": "textured stucco + timber screens",
            "window_frame": "powder-coated aluminum bronze",
            "roof_finish": "warm grey membrane",
            "accent": "#6a4a2f",
        }
    if "industrial" in style_key:
        return {
            "facade": "microcement + dark steel",
            "window_frame": "powder-coated aluminum black",
            "roof_finish": "charcoal waterproof membrane",
            "accent": "#2f2f34",
        }
    return {
        "facade": "painted plaster + porcelain accent tile",
        "window_frame": "powder-coated aluminum dark grey",
        "roof_finish": "light grey waterproof membrane",
        "accent": "#205d67",
    }


def _room_finish(room_type: str, style: str) -> dict[str, Any]:
    materials = _style_material(style)
    defaults = {
        "floor": {"material": "porcelain_tile", "size": "600x600", "color": "warm_grey"},
        "wall": {"material": "painted_plaster", "color": "white", "code": "RAL9010"},
        "ceiling": {"material": "painted_plaster", "color": "white", "type": "flat"},
        "baseboard": {"material": "painted_wood", "height_mm": 80},
    }
    if room_type in {"bedroom", "worship"}:
        defaults["floor"] = {"material": "engineered_wood", "size": "190x1200", "color": "oak"}
    if room_type in {"bathroom", "powder", "laundry"}:
        defaults["wall"] = {"material": "ceramic_tile", "size": "300x600", "color": "white", "height_m": 2.4}
    if room_type in {"kitchen", "pantry"}:
        defaults["wall"] = {"material": "ceramic_tile", "size": "300x600", "color": "white", "height_m": 1.2}
    defaults["style_reference"] = materials["facade"]
    return defaults


def _face_wall_ids(level_id: str) -> dict[str, str]:
    return {
        "south": f"{level_id}-wall-south",
        "north": f"{level_id}-wall-north",
        "east": f"{level_id}-wall-east",
        "west": f"{level_id}-wall-west",
    }


def _level_sequence(floors: int) -> list[dict[str, Any]]:
    levels: list[dict[str, Any]] = [
        {"id": "L0", "name": "Ground", "elevation_m": 0.0, "type": "ground"},
    ]
    elevation = 0.45
    for index in range(1, floors + 1):
        floor_to_floor = 3.6 if index == 1 else 3.3
        slab_thickness = 0.15 if index == 1 else 0.12
        levels.append(
            {
                "id": f"L{index}",
                "name": f"Tang {index}",
                "elevation_m": _round(elevation),
                "floor_to_floor_m": _round(floor_to_floor),
                "slab_thickness_m": _round(slab_thickness),
                "clear_height_m": _round(floor_to_floor - slab_thickness - 0.45),
                "ceiling_height_m": _round(floor_to_floor - slab_thickness - 0.6),
                "type": "floor",
            }
        )
        elevation += floor_to_floor
    levels.append({"id": "LR", "name": "Roof", "elevation_m": _round(elevation), "type": "roof"})
    return levels


def _add_wall(
    walls: list[dict[str, Any]],
    *,
    wall_id: str,
    level: str,
    start: tuple[float, float],
    end: tuple[float, float],
    wall_type: str,
    thickness: float,
    structural: bool,
    materials: dict[str, str],
) -> None:
    core_layer = "reinforced_concrete" if structural else ("aac_block" if wall_type == "interior" else "brick_100")
    walls.append(
        {
            "id": wall_id,
            "level": level,
            "start": [_round(start[0]), _round(start[1])],
            "end": [_round(end[0]), _round(end[1])],
            "type": wall_type,
            "assembly": {
                "total_thickness_m": _round(thickness),
                "layers": [
                    {"material": "painted_plaster", "thickness_m": 0.015, "side": "interior"},
                    {"material": core_layer, "thickness_m": _round(max(thickness - 0.03, 0.07))},
                    {"material": "textured_plaster" if wall_type == "exterior" else "painted_plaster", "thickness_m": 0.015, "side": "exterior"},
                ],
            },
            "fire_rating": "REI60" if structural else None,
            "structural": structural,
            "finish_tag": materials["facade"] if wall_type == "exterior" else "painted partition",
        }
    )


def build_geometry_v2(
    brief_json: dict[str, Any] | None,
    option_index: int = 0,
    strategy_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    brief = brief_json or {}
    lot = brief.get("lot") or {}
    style = str(brief.get("style") or "modern_minimalist")
    strategy = strategy_profile or {}
    rule_overrides = strategy.get("rule_overrides") or {}
    strategy_key = str(strategy.get("strategy_key") or "")
    width = _clamp(float(lot.get("width_m") or 5.0), 4.0, 12.0)
    depth = _clamp(float(lot.get("depth_m") or 20.0), 12.0, 40.0)
    floors = int(_clamp(float(brief.get("floors") or 4), 2, 4))
    materials = _style_material(style)
    levels = _level_sequence(floors)

    building_depth_factor = float(rule_overrides.get("building_depth_factor") or 0.86)
    front_zone_factor = 0.29 + (option_index % 3) * 0.02 + float(rule_overrides.get("front_zone_shift") or 0.0)
    core_zone_factor = 0.16 + ((option_index + 1) % 3) * 0.015 + float(rule_overrides.get("core_zone_shift") or 0.0)
    x_split_factor = float(rule_overrides.get("x_split") or (0.57 if option_index % 2 == 0 else 0.52))

    max_building_depth = 16.2 if width <= 5.5 else (17.5 if width <= 7.2 else 18.5)
    building_depth = _round(min(max(depth - 2.0, depth * building_depth_factor), max_building_depth, depth - 1.2))
    front_buffer = _round(max((depth - building_depth) / 2, 0.6))
    rear_buffer = _round(depth - building_depth - front_buffer)

    front_zone = _round(building_depth * front_zone_factor)
    core_zone = _round(building_depth * core_zone_factor)
    rear_zone = _round(building_depth - front_zone - core_zone)

    x_split = _round(width * x_split_factor)
    service_width = _round(width - x_split)

    grids = {
        "axes_x": [
            {"id": "A", "position": 0.0},
            {"id": "B", "position": _round(x_split)},
            {"id": "C", "position": _round(width)},
        ],
        "axes_y": [
            {"id": "1", "position": 0.0},
            {"id": "2", "position": _round(front_zone)},
            {"id": "3", "position": _round(front_zone + core_zone)},
            {"id": "4", "position": _round(building_depth)},
        ],
    }

    site = {
        "boundary": _polygon(0, 0, width, depth),
        "orientation_north_deg": 180,
        "setbacks": {
            "front_m": _round(front_buffer),
            "back_m": _round(rear_buffer),
            "left_m": 0.0,
            "right_m": 0.0,
        },
        "access_points": [
            {"type": "main_entrance", "position": [_round(width * 0.35), 0.0], "width_m": 1.2},
            {"type": "service_gate", "position": [_round(width * 0.82), 0.0], "width_m": 0.9},
        ],
        "landscape_zones": [
            {"type": "front_yard", "polygon": _polygon(0, 0, width, front_buffer)},
            {"type": "rear_garden", "polygon": _polygon(0, depth - rear_buffer, width, depth)},
        ],
        "utilities": {
            "water_connection": [0.0, _round(depth * 0.52)],
            "sewer_connection": [0.0, _round(depth * 0.6)],
            "electrical_pole": [_round(width), 0.0],
        },
    }

    walls: list[dict[str, Any]] = []
    rooms: list[dict[str, Any]] = []
    openings: list[dict[str, Any]] = []
    stairs: list[dict[str, Any]] = []
    fixtures: list[dict[str, Any]] = []
    room_doors: dict[str, list[str]] = defaultdict(list)
    room_windows: dict[str, list[str]] = defaultdict(list)
    opening_counter = {"door": 1, "window": 1}

    def next_mark(kind: str) -> str:
        mark = f"{'D' if kind == 'door' else 'W'}{opening_counter[kind]:02d}"
        opening_counter[kind] += 1
        return mark

    def add_room(
        *,
        level: str,
        room_id: str,
        name: str,
        room_type: str,
        polygon: list[list[float]],
        notes: str | None = None,
        extras: dict[str, Any] | None = None,
    ) -> None:
        payload = {
            "id": room_id,
            "name": name,
            "name_en": name,
            "type": room_type,
            "level": level,
            "polygon": polygon,
            "area_m2": _round(_area_from_polygon(polygon)),
            "perimeter_m": _round(_perimeter_from_polygon(polygon)),
            "clear_height_m": next(item["ceiling_height_m"] for item in levels if item["id"] == level),
            "finishes": _room_finish(room_type, style),
            "doors": room_doors[room_id],
            "windows": room_windows[room_id],
            "notes": notes,
        }
        if extras:
            payload.update(extras)
        rooms.append(payload)

    def add_opening(
        *,
        level: str,
        room_id: str,
        wall_id: str,
        kind: str,
        subtype: str,
        position: float,
        width_m: float,
        height_m: float,
        sill_height_m: float,
        face: str,
        extra: dict[str, Any] | None = None,
    ) -> None:
        mark = next_mark(kind)
        payload = {
            "id": mark,
            "wall_id": wall_id,
            "type": kind,
            "subtype": subtype,
            "position_along_wall_m": _round(position),
            "width_m": _round(width_m),
            "height_m": _round(height_m),
            "sill_height_m": _round(sill_height_m),
            "level": level,
            "face": face,
            "room_id": room_id,
            "schedule_mark": mark,
            "schedule_group": f"{face}_{kind}s",
            "frame": {
                "material": materials["window_frame"],
                "color": "dark_grey",
                "profile": "slim",
            },
        }
        if kind == "door":
            payload["panel"] = {
                "material": "engineered_wood" if subtype.startswith("interior") else "tempered_glass",
                "type": "swing",
                "swing_direction": "inward",
                "leaves": 2 if "double" in subtype else 1,
            }
            payload["hardware"] = {"handle": "lever", "lock": "multipoint" if subtype == "entrance_double" else "standard"}
            room_doors[room_id].append(mark)
        else:
            payload["glazing"] = {
                "type": "double_low_e",
                "thickness_mm": 24,
                "u_value": 1.1,
                "solar_heat_gain": 0.28,
            }
            payload["operation"] = {"type": "casement" if "casement" in subtype else "sliding", "hinge_side": "left"}
            room_windows[room_id].append(mark)
        if extra:
            payload.update(extra)
        openings.append(payload)

    floor_ids = [item["id"] for item in levels if item["type"] == "floor"]
    for level_id in floor_ids:
        face_walls = _face_wall_ids(level_id)
        _add_wall(
            walls,
            wall_id=face_walls["south"],
            level=level_id,
            start=(0.0, front_buffer),
            end=(width, front_buffer),
            wall_type="exterior",
            thickness=0.2,
            structural=True,
            materials=materials,
        )
        _add_wall(
            walls,
            wall_id=face_walls["north"],
            level=level_id,
            start=(0.0, front_buffer + building_depth),
            end=(width, front_buffer + building_depth),
            wall_type="exterior",
            thickness=0.2,
            structural=True,
            materials=materials,
        )
        _add_wall(
            walls,
            wall_id=face_walls["east"],
            level=level_id,
            start=(width, front_buffer),
            end=(width, front_buffer + building_depth),
            wall_type="party_wall" if option_index % 2 == 0 else "exterior",
            thickness=0.2,
            structural=True,
            materials=materials,
        )
        _add_wall(
            walls,
            wall_id=face_walls["west"],
            level=level_id,
            start=(0.0, front_buffer),
            end=(0.0, front_buffer + building_depth),
            wall_type="party_wall" if option_index % 2 == 1 else "exterior",
            thickness=0.2,
            structural=True,
            materials=materials,
        )

    def room_box(level: str, suffix: str, name: str, room_type: str, x1: float, y1: float, x2: float, y2: float, extras: dict[str, Any] | None = None) -> str:
        room_id = f"{level}-{suffix}"
        add_room(
            level=level,
            room_id=room_id,
            name=name,
            room_type=room_type,
            polygon=_polygon(x1, y1, x2, y2),
            extras=extras,
        )
        return room_id

    front_y1 = front_buffer
    front_y2 = front_buffer + front_zone
    core_y2 = front_y2 + core_zone
    rear_y2 = front_buffer + building_depth
    service_lane_width = _round(_clamp(service_width * 0.45, 1.1, min(1.6, width * 0.28)))
    service_x = _round(width - service_lane_width)

    def limited_depth(x1: float, x2: float, y1: float, y2: float, max_area: float, *, min_depth: float = 3.2) -> float:
        width_m = max(x2 - x1, 0.5)
        available = max(y2 - y1, min_depth)
        return _round(min(available, max(min_depth, max_area / width_m)))

    for level_number, level_id in enumerate(floor_ids, start=1):
        face_walls = _face_wall_ids(level_id)
        if level_number == 1:
            living_id = room_box(level_id, "R1", "Living Room", "living", 0.2, front_y1 + 0.2, width - 0.2, front_y2 - 0.1)
            powder_id = room_box(level_id, "R2", "Powder", "powder", 0.2, front_y2 + 0.1, x_split - 0.1, core_y2 - 0.1)
            stair_id = room_box(level_id, "R3", "Stair Hall", "circulation", x_split + 0.1, front_y2 + 0.1, width - 0.2, core_y2 - 0.1)
            kitchen_y1 = core_y2 + 0.1
            kitchen_min_depth = 4.0 if width >= 8.0 else 4.8
            kitchen_y2 = _round(kitchen_y1 + limited_depth(0.2, service_x - 0.1, kitchen_y1, rear_y2 - 0.2, 34.0, min_depth=kitchen_min_depth))
            kitchen_id = room_box(
                level_id,
                "R4",
                "Kitchen + Dining",
                "kitchen",
                0.2,
                kitchen_y1,
                service_x - 0.1,
                kitchen_y2,
                extras={"fixtures_refs": ["fix_kitchen_counter", "fix_sink", "fix_cooktop"]},
            )
            service_id = room_box(level_id, "R5", "Laundry / Service", "laundry", service_x + 0.1, kitchen_y1, width - 0.2, kitchen_y2)
            rear_court_id = None
            if rear_y2 - 0.2 - kitchen_y2 >= 1.2:
                rear_court_id = room_box(
                    level_id,
                    "R6",
                    "Rear Garden Court",
                    "terrace",
                    0.2,
                    kitchen_y2 + 0.1,
                    width - 0.2,
                    rear_y2 - 0.2,
                )

            interior_walls = [
                ("wall-front-split", (0.0, front_y2), (width, front_y2)),
                ("wall-core-split", (0.0, core_y2), (width, core_y2)),
                ("wall-service-core", (x_split, front_y2), (x_split, core_y2)),
                ("wall-laundry", (service_x, kitchen_y1), (service_x, kitchen_y2)),
            ]
            if rear_court_id:
                interior_walls.append(("wall-rear-court", (0.0, kitchen_y2), (width, kitchen_y2)))
            for suffix, start, end in interior_walls:
                _add_wall(
                    walls,
                    wall_id=f"{level_id}-{suffix}",
                    level=level_id,
                    start=start,
                    end=end,
                    wall_type="interior",
                    thickness=0.1,
                    structural=False,
                    materials=materials,
                )

            add_opening(level=level_id, room_id=living_id, wall_id=face_walls["south"], kind="door", subtype="entrance_double", position=width * 0.28, width_m=1.6, height_m=2.7, sill_height_m=0.0, face="south")
            add_opening(level=level_id, room_id=living_id, wall_id=face_walls["south"], kind="window", subtype="fixed_casement", position=width * 0.68, width_m=1.8, height_m=1.6, sill_height_m=0.8, face="south")
            add_opening(level=level_id, room_id=kitchen_id, wall_id=face_walls["north"], kind="window", subtype="sliding", position=width * 0.45, width_m=2.1, height_m=1.5, sill_height_m=0.9, face="north")
            add_opening(level=level_id, room_id=service_id, wall_id=f"{level_id}-wall-laundry", kind="door", subtype="interior_single", position=(kitchen_y2 - kitchen_y1) / 2, width_m=0.8, height_m=2.1, sill_height_m=0.0, face="interior")
            if rear_court_id:
                add_opening(level=level_id, room_id=rear_court_id, wall_id=f"{level_id}-wall-rear-court", kind="door", subtype="interior_single", position=width * 0.55, width_m=1.2, height_m=2.2, sill_height_m=0.0, face="interior")
            add_opening(level=level_id, room_id=powder_id, wall_id=f"{level_id}-wall-front-split", kind="door", subtype="interior_single", position=x_split * 0.35, width_m=0.8, height_m=2.1, sill_height_m=0.0, face="interior")
            add_opening(level=level_id, room_id=stair_id, wall_id=f"{level_id}-wall-front-split", kind="door", subtype="interior_single", position=x_split + service_width * 0.25, width_m=0.9, height_m=2.1, sill_height_m=0.0, face="interior")

            stairs.append(
                {
                    "id": f"{level_id}-stair",
                    "from_level": level_id,
                    "to_level": f"L{level_number + 1}" if level_number < floors else "LR",
                    "type": "u_turn",
                    "position": _polygon(x_split + 0.15, front_y2 + 0.15, width - 0.2, core_y2 - 0.15),
                    "direction": "up",
                    "geometry": {
                        "run_count": 20,
                        "riser_height_mm": 165,
                        "tread_depth_mm": 250,
                        "width_m": _round(service_width - 0.35),
                        "landing_depth_m": 0.95,
                        "turn_at_step": 10,
                    },
                    "handrail": {"material": "steel", "height_mm": 900, "sides": ["left"]},
                    "finish": {"tread": "granite", "riser": "painted_plaster"},
                    "headroom_m": 2.1,
                    "code_compliance": {
                        "min_headroom_m": 2.0,
                        "max_riser_mm": 180,
                        "min_tread_mm": 220,
                        "status": "pass",
                    },
                }
            )

            fixtures.extend(
                [
                    {
                        "id": "fix_kitchen_counter",
                        "type": "kitchen_counter",
                        "room_id": kitchen_id,
                        "level": level_id,
                        "polygon": _polygon(0.3, core_y2 + 0.4, 2.7, core_y2 + 1.0),
                        "height_m": 0.86,
                        "material": "quartz_white",
                    },
                    {
                        "id": "fix_sink",
                        "type": "sink",
                        "subtype": "kitchen_single",
                        "room_id": kitchen_id,
                        "level": level_id,
                        "position": [1.8, _round(core_y2 + 0.75)],
                        "dimensions": {"width_m": 0.6, "depth_m": 0.5},
                        "plumbing_connection": True,
                    },
                    {
                        "id": "fix_cooktop",
                        "type": "cooktop",
                        "room_id": kitchen_id,
                        "level": level_id,
                        "position": [2.35, _round(core_y2 + 0.75)],
                        "dimensions": {"width_m": 0.75, "depth_m": 0.55},
                    },
                    {
                        "id": "fix_powder_wc",
                        "type": "toilet",
                        "subtype": "wall_hung",
                        "room_id": powder_id,
                        "level": level_id,
                        "position": [_round(x_split * 0.55), _round((front_y2 + core_y2) / 2)],
                        "dimensions": {"width_m": 0.36, "depth_m": 0.54},
                    },
                ]
            )
            continue

        if level_number < floors:
            bedroom_a = room_box(level_id, "R1", f"Bedroom {level_number}A", "bedroom", 0.2, front_y1 + 0.2, width - 0.2, front_y2 - 0.1)
            bath = room_box(level_id, "R2", "Bathroom", "bathroom", 0.2, front_y2 + 0.1, x_split - 0.1, core_y2 - 0.1)
            landing = room_box(level_id, "R3", "Landing", "circulation", x_split + 0.1, front_y2 + 0.1, width - 0.2, core_y2 - 0.1)
            rear_room_y1 = core_y2 + 0.1
            rear_room_y2 = rear_y2 - 0.2
            bedroom_b_y2 = _round(rear_room_y1 + limited_depth(0.2, width - 0.2, rear_room_y1, rear_room_y2, 31.0, min_depth=4.0))
            bedroom_b = room_box(level_id, "R4", f"Bedroom {level_number}B", "bedroom", 0.2, rear_room_y1, width - 0.2, bedroom_b_y2)
            rear_aux_id = None
            if rear_room_y2 - bedroom_b_y2 >= 1.2:
                rear_aux_id = room_box(
                    level_id,
                    "R5",
                    "Study / Closet",
                    "storage",
                    0.2,
                    bedroom_b_y2 + 0.1,
                    width - 0.2,
                    rear_room_y2,
                )

            for suffix, start, end in [
                ("wall-front-split", (0.0, front_y2), (width, front_y2)),
                ("wall-core-split", (0.0, core_y2), (width, core_y2)),
                ("wall-landing", (x_split, front_y2), (x_split, core_y2)),
            ]:
                _add_wall(
                    walls,
                    wall_id=f"{level_id}-{suffix}",
                    level=level_id,
                    start=start,
                    end=end,
                    wall_type="interior",
                    thickness=0.1,
                    structural=False,
                    materials=materials,
                )
            if rear_aux_id:
                _add_wall(
                    walls,
                    wall_id=f"{level_id}-wall-rear-aux",
                    level=level_id,
                    start=(0.0, bedroom_b_y2),
                    end=(width, bedroom_b_y2),
                    wall_type="interior",
                    thickness=0.1,
                    structural=False,
                    materials=materials,
                )

            add_opening(level=level_id, room_id=bedroom_a, wall_id=face_walls["south"], kind="window", subtype="sliding", position=width * 0.45, width_m=2.0, height_m=1.5, sill_height_m=0.85, face="south")
            add_opening(level=level_id, room_id=bedroom_b, wall_id=f"{level_id}-wall-rear-aux" if rear_aux_id else face_walls["north"], kind="window", subtype="sliding", position=width * 0.45, width_m=1.8, height_m=1.5, sill_height_m=0.85, face="north" if not rear_aux_id else "interior")
            add_opening(level=level_id, room_id=bedroom_a, wall_id=f"{level_id}-wall-front-split", kind="door", subtype="interior_single", position=width * 0.32, width_m=0.9, height_m=2.1, sill_height_m=0.0, face="interior")
            add_opening(level=level_id, room_id=bath, wall_id=f"{level_id}-wall-front-split", kind="door", subtype="interior_single", position=x_split * 0.32, width_m=0.8, height_m=2.1, sill_height_m=0.0, face="interior")
            add_opening(level=level_id, room_id=bedroom_b, wall_id=f"{level_id}-wall-core-split", kind="door", subtype="interior_single", position=width * 0.62, width_m=0.9, height_m=2.1, sill_height_m=0.0, face="interior")
            if rear_aux_id:
                add_opening(level=level_id, room_id=rear_aux_id, wall_id=f"{level_id}-wall-rear-aux", kind="door", subtype="interior_single", position=width * 0.62, width_m=0.8, height_m=2.1, sill_height_m=0.0, face="interior")
            add_opening(level=level_id, room_id=landing, wall_id=face_walls["east"], kind="window", subtype="fixed_casement", position=front_zone + (core_zone / 2), width_m=0.8, height_m=1.2, sill_height_m=1.0, face="east")

            stairs.append(
                {
                    "id": f"{level_id}-stair",
                    "from_level": level_id,
                    "to_level": f"L{level_number + 1}" if level_number < floors else "LR",
                    "type": "u_turn",
                    "position": _polygon(x_split + 0.15, front_y2 + 0.15, width - 0.2, core_y2 - 0.15),
                    "direction": "up",
                    "geometry": {
                        "run_count": 20,
                        "riser_height_mm": 165,
                        "tread_depth_mm": 250,
                        "width_m": _round(service_width - 0.35),
                        "landing_depth_m": 0.95,
                        "turn_at_step": 10,
                    },
                    "handrail": {"material": "steel", "height_mm": 900, "sides": ["left"]},
                    "finish": {"tread": "granite", "riser": "painted_plaster"},
                    "headroom_m": 2.1,
                    "code_compliance": {
                        "min_headroom_m": 2.0,
                        "max_riser_mm": 180,
                        "min_tread_mm": 220,
                        "status": "pass",
                    },
                }
            )
            fixtures.extend(
                [
                    {
                        "id": f"{level_id}-vanity",
                        "type": "basin",
                        "room_id": bath,
                        "level": level_id,
                        "position": [_round(x_split * 0.45), _round(front_y2 + 0.55)],
                        "dimensions": {"width_m": 0.8, "depth_m": 0.45},
                    },
                    {
                        "id": f"{level_id}-wc",
                        "type": "toilet",
                        "room_id": bath,
                        "level": level_id,
                        "position": [_round(x_split * 0.65), _round(core_y2 - 0.55)],
                        "dimensions": {"width_m": 0.36, "depth_m": 0.54},
                    },
                ]
            )
            continue

        worship = room_box(level_id, "R1", "Worship Room", "worship", 0.2, front_y1 + 0.2, width * 0.6, front_y2 - 0.1)
        lounge = room_box(level_id, "R2", "Family Lounge", "living", width * 0.6 + 0.1, front_y1 + 0.2, width - 0.2, front_y2 - 0.1)
        laundry = room_box(level_id, "R3", "Laundry", "laundry", 0.2, front_y2 + 0.1, x_split - 0.1, core_y2 - 0.1)
        landing = room_box(level_id, "R4", "Landing", "circulation", x_split + 0.1, front_y2 + 0.1, width - 0.2, core_y2 - 0.1)
        terrace_y1 = core_y2 + 0.1
        terrace_y2 = _round(terrace_y1 + limited_depth(0.2, width - 0.2, terrace_y1, rear_y2 - 0.2, 34.0, min_depth=3.8))
        terrace = room_box(level_id, "R5", "Roof Terrace", "terrace", 0.2, terrace_y1, width - 0.2, terrace_y2)
        planter_deck_ids: list[str] = []
        if rear_y2 - 0.2 - terrace_y2 >= 1.2:
            deck_y1 = terrace_y2 + 0.1
            deck_y2 = rear_y2 - 0.2
            deck_area = (width - 0.4) * max(deck_y2 - deck_y1, 0.0)
            if deck_area >= 38.0 and width >= 6.4:
                planter_deck_ids.append(room_box(level_id, "R6", "Planter Court", "terrace", 0.2, deck_y1, x_split - 0.1, deck_y2))
                planter_deck_ids.append(room_box(level_id, "R7", "Service Deck", "terrace", x_split + 0.1, deck_y1, width - 0.2, deck_y2))
            else:
                planter_deck_ids.append(room_box(level_id, "R6", "Planter / Service Deck", "terrace", 0.2, deck_y1, width - 0.2, deck_y2))

        for suffix, start, end in [
            ("wall-front-split", (0.0, front_y2), (width, front_y2)),
            ("wall-core-split", (0.0, core_y2), (width, core_y2)),
            ("wall-lounge", (width * 0.6, front_y1), (width * 0.6, front_y2)),
            ("wall-landing", (x_split, front_y2), (x_split, core_y2)),
        ]:
            _add_wall(
                walls,
                wall_id=f"{level_id}-{suffix}",
                level=level_id,
                start=start,
                end=end,
                wall_type="interior",
                thickness=0.1,
                structural=False,
                materials=materials,
            )
        if planter_deck_ids:
            _add_wall(
                walls,
                wall_id=f"{level_id}-wall-planter-deck",
                level=level_id,
                start=(0.0, terrace_y2),
                end=(width, terrace_y2),
                wall_type="interior",
                thickness=0.1,
                structural=False,
                materials=materials,
            )
            if len(planter_deck_ids) > 1:
                _add_wall(
                    walls,
                    wall_id=f"{level_id}-wall-deck-split",
                    level=level_id,
                    start=(x_split, terrace_y2),
                    end=(x_split, rear_y2),
                    wall_type="interior",
                    thickness=0.1,
                    structural=False,
                    materials=materials,
                )

        add_opening(level=level_id, room_id=worship, wall_id=face_walls["south"], kind="window", subtype="sliding", position=width * 0.25, width_m=1.6, height_m=1.5, sill_height_m=0.85, face="south")
        add_opening(level=level_id, room_id=lounge, wall_id=face_walls["south"], kind="door", subtype="entrance_double", position=width * 0.78, width_m=1.4, height_m=2.5, sill_height_m=0.0, face="south")
        add_opening(level=level_id, room_id=terrace, wall_id=f"{level_id}-wall-planter-deck" if planter_deck_ids else face_walls["north"], kind="window", subtype="sliding", position=width * 0.5, width_m=2.4, height_m=1.8, sill_height_m=0.4, face="north" if not planter_deck_ids else "interior")
        for deck_index, deck_room_id in enumerate(planter_deck_ids):
            add_opening(
                level=level_id,
                room_id=deck_room_id,
                wall_id=f"{level_id}-wall-planter-deck",
                kind="door",
                subtype="interior_single",
                position=width * (0.38 if deck_index == 0 else 0.72),
                width_m=0.9,
                height_m=2.1,
                sill_height_m=0.0,
                face="interior",
            )
        add_opening(level=level_id, room_id=laundry, wall_id=f"{level_id}-wall-front-split", kind="door", subtype="interior_single", position=x_split * 0.38, width_m=0.8, height_m=2.1, sill_height_m=0.0, face="interior")
        add_opening(level=level_id, room_id=landing, wall_id=f"{level_id}-wall-front-split", kind="door", subtype="interior_single", position=x_split + service_width * 0.25, width_m=0.9, height_m=2.1, sill_height_m=0.0, face="interior")

        stairs.append(
            {
                "id": f"{level_id}-stair",
                "from_level": level_id,
                "to_level": "LR",
                "type": "u_turn",
                "position": _polygon(x_split + 0.15, front_y2 + 0.15, width - 0.2, core_y2 - 0.15),
                "direction": "up",
                "geometry": {
                    "run_count": 18,
                    "riser_height_mm": 165,
                    "tread_depth_mm": 260,
                    "width_m": _round(service_width - 0.35),
                    "landing_depth_m": 0.95,
                    "turn_at_step": 9,
                },
                "handrail": {"material": "steel", "height_mm": 900, "sides": ["left"]},
                "finish": {"tread": "granite", "riser": "painted_plaster"},
                "headroom_m": 2.1,
                "code_compliance": {
                    "min_headroom_m": 2.0,
                    "max_riser_mm": 180,
                    "min_tread_mm": 220,
                    "status": "pass",
                },
            }
        )
        fixtures.append(
            {
                "id": f"{level_id}-washer",
                "type": "washing_machine",
                "room_id": laundry,
                "level": level_id,
                "position": [_round(x_split * 0.45), _round(front_y2 + 0.65)],
                "dimensions": {"width_m": 0.65, "depth_m": 0.65},
            }
        )

    total_floor_area = _round(sum(room["area_m2"] for room in rooms if room["type"] != "terrace"))
    project_info = {
        "name": str(brief.get("project_name") or "AI Architect Residence"),
        "address": str(brief.get("address") or "Residential project"),
        "lot_area_m2": _round(width * depth),
        "building_area_m2": _round(width * building_depth),
        "total_floor_area_m2": total_floor_area,
        "building_coverage_ratio": _round((width * building_depth) / (width * depth)),
        "floor_area_ratio": _round(total_floor_area / (width * depth)),
    }

    roof = {
        "type": "flat_with_parapet",
        "elevation_top_m": _round(levels[-1]["elevation_m"] + 0.3),
        "parapet_height_m": 0.9,
        "slope_percent": 2,
        "drainage_direction": "rear",
        "layers": [
            {"material": "waterproof_membrane", "thickness_mm": 3},
            {"material": "xps_insulation", "thickness_mm": 50},
            {"material": "reinforced_concrete_slab", "thickness_mm": 120},
            {"material": materials["roof_finish"], "thickness_mm": 15},
        ],
        "drainage_points": [{"position": [_round(width * 0.8), _round(depth - rear_buffer - 0.6)], "type": "internal_drain", "size_mm": 100}],
        "terrace_zones": [{"polygon": _polygon(0.4, front_buffer + core_y2 + 0.3, width - 0.4, front_buffer + building_depth - 0.3), "finish": "outdoor_tile", "use": "terrace"}],
    }

    markers = {
        "sections": [
            {"id": "S1", "start": [_round(width * 0.35), front_buffer], "end": [_round(width * 0.35), front_buffer + building_depth], "direction": "east", "label": "Section A-A"},
            {"id": "S2", "start": [0.0, _round(front_buffer + building_depth * 0.55)], "end": [_round(width), _round(front_buffer + building_depth * 0.55)], "direction": "north", "label": "Section B-B"},
        ],
        "elevations": [
            {"id": "E1", "face": "south", "label": "South Elevation"},
            {"id": "E2", "face": "north", "label": "North Elevation"},
            {"id": "E3", "face": "east", "label": "East Elevation"},
            {"id": "E4", "face": "west", "label": "West Elevation"},
        ],
        "details": [
            {"id": "DT1", "position": [_round(width * 0.78), front_buffer + core_zone], "label": "Stair Detail", "sheet_ref": "A8"},
            {"id": "DT2", "position": [_round(width * 0.22), front_buffer + building_depth - 0.6], "label": "Parapet Detail", "sheet_ref": "A11"},
        ],
    }

    geometry = {
        "$schema": LAYER_2_SCHEMA,
        "version": "2.0",
        "units": "metric",
        "precision": 3,
        "design_intent": {
            "strategy_key": strategy_key,
            "option_index": option_index,
        },
        "project_info": project_info,
        "grids": grids,
        "levels": levels,
        "site": site,
        "walls": walls,
        "openings": openings,
        "rooms": rooms,
        "stairs": stairs,
        "fixtures": fixtures,
        "roof": roof,
        "markers": markers,
        "dimensions_config": {
            "style": "architectural",
            "text_height_mm": 2.5,
            "arrow_type": "tick",
            "extension_line_gap_mm": 2,
            "chains": {
                "overall": True,
                "grid": True,
                "wall": True,
                "opening": True,
                "room_internal": True,
                "elevation_vertical": True,
            },
        },
    }
    return geometry


def ensure_geometry_v2(
    geometry_json: dict[str, Any] | None,
    brief_json: dict[str, Any] | None,
    option_index: int = 0,
    strategy_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if geometry_json and geometry_json.get("$schema") == LAYER_2_SCHEMA:
        return deepcopy(geometry_json)
    return build_geometry_v2(brief_json or {}, option_index=option_index, strategy_profile=strategy_profile)


def summarize_geometry(geometry: dict[str, Any]) -> dict[str, Any]:
    level_totals: dict[str, float] = defaultdict(float)
    for room in geometry.get("rooms", []):
        if room.get("type") == "terrace":
            continue
        level_totals[str(room.get("level"))] += float(room.get("area_m2") or 0)
    return {
        "schema": geometry.get("$schema"),
        "levels": len([item for item in geometry.get("levels", []) if item.get("type") == "floor"]),
        "wall_count": len(geometry.get("walls", [])),
        "opening_count": len(geometry.get("openings", [])),
        "room_count": len(geometry.get("rooms", [])),
        "level_totals": {key: _round(value) for key, value in level_totals.items()},
        "total_floor_area_m2": _round(sum(level_totals.values())),
    }


def geometry_room_index(geometry: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(room["id"]): room for room in geometry.get("rooms", [])}


def geometry_level_index(geometry: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(level["id"]): level for level in geometry.get("levels", [])}
