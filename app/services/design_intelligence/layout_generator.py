from __future__ import annotations

from dataclasses import replace
from itertools import combinations

from app.services.design_intelligence.concept_model import (
    ArchitecturalConceptModel,
    ConceptFixture,
    ConceptModelValidationError,
    ConceptOpening,
    ConceptRoom,
    ConceptSectionLine,
    ConceptStair,
    ConceptWall,
    Point,
    validate_concept_model,
)
from app.services.design_intelligence.customer_understanding import CustomerUnderstanding
from app.services.design_intelligence.program_planner import ProgramPlan, RoomProgramItem, plan_room_program
from app.services.design_intelligence.provenance import DecisionValue
from app.services.design_intelligence.technical_defaults import TechnicalDefaults, resolve_technical_defaults


class LayoutValidationError(ValueError):
    pass


def generate_concept_layout(
    *,
    concept_model: ArchitecturalConceptModel,
    understanding: CustomerUnderstanding,
    style_id: str | None = None,
) -> ArchitecturalConceptModel:
    resolved_style = style_id or (str(concept_model.style.value) if concept_model.style else "minimal_warm")
    defaults = resolve_technical_defaults(resolved_style)
    program = plan_room_program(understanding=understanding, concept_model=concept_model, style_id=resolved_style)
    width = float(concept_model.site.width_m.value)
    depth = float(concept_model.site.depth_m.value)

    rooms = _generate_rooms(program, width=width, depth=depth, floors=len(concept_model.levels))
    walls = _generate_walls(rooms, width=width, depth=depth, defaults=defaults)
    stairs = _generate_stairs(concept_model, rooms, width=width, depth=depth, defaults=defaults, program=program)
    openings = _generate_openings(rooms, walls, width=width, depth=depth, defaults=defaults, style_id=resolved_style)
    fixtures = _generate_fixtures(rooms)
    section_lines = (
        ConceptSectionLine(
            id="section-a",
            label="A-A",
            start=_proposal((width / 2, 0.0), "Vị trí mặt cắt concept đi qua trục thang/giếng trời."),
            end=_proposal((width / 2, depth), "Vị trí mặt cắt concept đi qua trục thang/giếng trời."),
            intent=_proposal("stair_lightwell_section", "Mặt cắt concept diễn giải thang và vùng lấy sáng."),
        ),
    )
    updated = replace(concept_model, rooms=rooms, walls=walls, openings=openings, stairs=stairs, fixtures=fixtures, section_lines=section_lines)
    validate_concept_model(updated)
    validate_layout(updated)
    return updated


def validate_layout(model: ArchitecturalConceptModel) -> None:
    _validate_rooms_inside_site(model)
    _validate_no_room_overlap(model)
    _validate_room_access(model)
    _validate_openings_attach_to_walls(model)
    _validate_stairs_fit(model)


def _generate_rooms(program: ProgramPlan, *, width: float, depth: float, floors: int) -> tuple[ConceptRoom, ...]:
    by_floor: dict[int, list[RoomProgramItem]] = {floor: [] for floor in range(1, floors + 1)}
    for item in program.items:
        by_floor.setdefault(item.level_number, []).append(item)

    rooms: list[ConceptRoom] = []
    for floor in range(1, floors + 1):
        items = by_floor.get(floor) or []
        if floor == 1:
            ordered = _floor_one_sequence(items)
        else:
            ordered = _upper_floor_sequence(items)
        if not ordered:
            ordered = [RoomProgramItem("flex", "Không gian linh hoạt", floor, "fallback")]
        rooms.extend(_partition_floor_rooms(ordered, width=width, depth=depth, floor=floor))
    return tuple(rooms)


def _floor_one_sequence(items: list[RoomProgramItem]) -> list[RoomProgramItem]:
    priority = ("garage", "living", "stair_lightwell", "kitchen_dining", "wc")
    return sorted(items, key=lambda item: priority.index(item.room_type) if item.room_type in priority else len(priority))


def _upper_floor_sequence(items: list[RoomProgramItem]) -> list[RoomProgramItem]:
    priority = ("bedroom", "stair_lightwell", "prayer", "laundry", "terrace_green", "storage")
    if not any(item.room_type == "stair_lightwell" for item in items):
        floor = items[0].level_number if items else 2
        items = [*items, RoomProgramItem("stair_lightwell", "Thang + giếng trời", floor, "circulation_green_core")]
    return sorted(items, key=lambda item: priority.index(item.room_type) if item.room_type in priority else len(priority))


def _partition_floor_rooms(items: list[RoomProgramItem], *, width: float, depth: float, floor: int) -> list[ConceptRoom]:
    margin = 0.3
    usable_depth = max(1.0, depth - margin * 2)
    weights = [_room_depth_weight(item.room_type) for item in items]
    weight_total = sum(weights)
    y = margin
    rooms: list[ConceptRoom] = []
    for index, item in enumerate(items):
        segment_depth = usable_depth * weights[index] / weight_total
        if index == len(items) - 1:
            y2 = depth - margin
        else:
            y2 = min(depth - margin, y + segment_depth)
        polygon = ((margin, y), (width - margin, y), (width - margin, y2), (margin, y2))
        area = _rect_area(polygon)
        room_id = f"f{floor}-{item.room_type}-{index + 1}"
        adjacency = (f"f{floor}-{items[index - 1].room_type}-{index}",) if index > 0 else ()
        rooms.append(
            ConceptRoom(
                id=room_id,
                level_id=f"L{floor}",
                room_type=item.room_type,
                label_vi=item.label_vi,
                polygon=_proposal(polygon, f"Phòng {item.label_vi} được chia theo module mặt bằng concept."),
                area_m2=_proposal(round(area, 2), f"Diện tích {item.label_vi} được tính từ polygon concept."),
                priority=_proposal(item.priority, f"Mức ưu tiên {item.label_vi} lấy từ brief/pattern."),
                adjacency=adjacency,
            )
        )
        y = y2
    return rooms


def _room_depth_weight(room_type: str) -> float:
    return {
        "garage": 1.0,
        "living": 1.25,
        "stair_lightwell": 0.75,
        "kitchen_dining": 1.35,
        "wc": 0.55,
        "bedroom": 1.25,
        "prayer": 0.75,
        "laundry": 0.55,
        "terrace_green": 0.8,
        "storage": 0.5,
    }.get(room_type, 1.0)


def _generate_walls(rooms: tuple[ConceptRoom, ...], *, width: float, depth: float, defaults: TechnicalDefaults) -> tuple[ConceptWall, ...]:
    floors = sorted({int(room.level_id[1:]) for room in rooms})
    walls: list[ConceptWall] = []
    for floor in floors:
        level_id = f"L{floor}"
        exterior_segments = [
            ("front", (0.0, 0.0), (width, 0.0)),
            ("right", (width, 0.0), (width, depth)),
            ("back", (width, depth), (0.0, depth)),
            ("left", (0.0, depth), (0.0, 0.0)),
        ]
        for name, start, end in exterior_segments:
            walls.append(
                ConceptWall(
                    id=f"wall-{level_id}-{name}",
                    level_id=level_id,
                    start=_proposal(start, "Tường bao concept bám ranh/khối nhà sơ bộ."),
                    end=_proposal(end, "Tường bao concept bám ranh/khối nhà sơ bộ."),
                    thickness_m=defaults.exterior_wall_thickness_m,
                    height_m=defaults.floor_to_floor_height_m,
                    wall_type="exterior",
                    exterior=True,
                )
            )
        for index, y in enumerate(sorted({round(_bounds(room.polygon.value)[1], 3) for room in rooms if room.level_id == level_id and _bounds(room.polygon.value)[1] > 0.31})):
            walls.append(
                ConceptWall(
                    id=f"wall-{level_id}-partition-{index + 1}",
                    level_id=level_id,
                    start=_proposal((0.0, y), "Tường ngăn concept theo ranh phòng."),
                    end=_proposal((width, y), "Tường ngăn concept theo ranh phòng."),
                    thickness_m=defaults.interior_wall_thickness_m,
                    height_m=defaults.floor_to_floor_height_m,
                    wall_type="interior",
                    exterior=False,
                )
            )
    return tuple(walls)


def _generate_stairs(
    concept_model: ArchitecturalConceptModel,
    rooms: tuple[ConceptRoom, ...],
    *,
    width: float,
    depth: float,
    defaults: TechnicalDefaults,
    program: ProgramPlan,
) -> tuple[ConceptStair, ...]:
    if len(concept_model.levels) < 2:
        return ()
    stair_room = next((room for room in rooms if room.room_type == "stair_lightwell"), None)
    if stair_room is None:
        y1 = depth * 0.42
        y2 = min(depth - 0.3, y1 + defaults.stair_run_m.value)
    else:
        _, y1, _, y2 = _bounds(stair_room.polygon.value)
    x2 = width - 0.6
    x1 = max(0.4, x2 - defaults.stair_width_m.value)
    footprint = ((x1, y1 + 0.2), (x2, y1 + 0.2), (x2, min(y2 - 0.2, y1 + defaults.stair_run_m.value)), (x1, min(y2 - 0.2, y1 + defaults.stair_run_m.value)))
    return (
        ConceptStair(
            id="stair-main",
            level_from="L1",
            level_to=f"L{len(concept_model.levels)}",
            footprint=_proposal(footprint, "Thang concept đặt cạnh giếng trời theo pattern đã chọn."),
            width_m=defaults.stair_width_m,
            strategy=_proposal(program.strategy_notes[0], "Vị trí thang/giếng trời lấy từ pattern memory."),
        ),
    )


def _generate_openings(
    rooms: tuple[ConceptRoom, ...],
    walls: tuple[ConceptWall, ...],
    *,
    width: float,
    depth: float,
    defaults: TechnicalDefaults,
    style_id: str,
) -> tuple[ConceptOpening, ...]:
    openings: list[ConceptOpening] = []
    wall_ids = {wall.id for wall in walls}
    for floor in sorted({int(room.level_id[1:]) for room in rooms}):
        level_id = f"L{floor}"
        front = f"wall-{level_id}-front"
        back = f"wall-{level_id}-back"
        if front in wall_ids:
            openings.append(
                ConceptOpening(
                    id=f"d-{level_id}-main",
                    level_id=level_id,
                    wall_id=front,
                    opening_type="door",
                    width_m=defaults.main_door_width_m if floor == 1 else defaults.internal_door_width_m,
                    height_m=_proposal(2.4 if floor == 1 else 2.2, "Chiều cao cửa concept lấy theo mặc định."),
                    sill_height_m=None,
                    operation=_proposal("swing", "Kiểu mở cửa concept dùng cửa quay cơ bản."),
                )
            )
        if back in wall_ids:
            openings.append(
                ConceptOpening(
                    id=f"w-{level_id}-rear",
                    level_id=level_id,
                    wall_id=back,
                    opening_type="window",
                    width_m=defaults.window_width_m,
                    height_m=defaults.window_height_m,
                    sill_height_m=defaults.window_sill_height_m,
                    operation=_proposal("shaded_louver" if style_id == "modern_tropical" else "fixed_or_sliding", "Kiểu cửa sổ concept lấy từ style/default."),
                )
            )
    return tuple(openings)


def _generate_fixtures(rooms: tuple[ConceptRoom, ...]) -> tuple[ConceptFixture, ...]:
    fixtures: list[ConceptFixture] = []
    for room in rooms:
        min_x, min_y, max_x, max_y = _bounds(room.polygon.value)
        center = ((min_x + max_x) / 2, (min_y + max_y) / 2)
        if room.room_type == "garage":
            fixture_type, label, size = "car", "Xe ô tô", (2.0, 4.2)
        elif room.room_type == "living":
            fixture_type, label, size = "sofa", "Sofa", (2.2, 0.9)
        elif room.room_type == "kitchen_dining":
            fixture_type, label, size = "kitchen_counter", "Bếp", (2.4, 0.65)
        elif room.room_type == "bedroom":
            fixture_type, label, size = "bed", "Giường", (2.0, 1.8)
        elif room.room_type == "wc":
            fixture_type, label, size = "toilet", "Thiết bị WC", (0.8, 1.4)
        elif room.room_type in {"terrace_green", "stair_lightwell"}:
            fixture_type, label, size = "plant", "Cây xanh", (1.0, 1.0)
        else:
            continue
        fixtures.append(
            ConceptFixture(
                id=f"fx-{room.id}",
                level_id=room.level_id,
                room_id=room.id,
                fixture_type=fixture_type,
                position=_proposal(center, f"Vị trí {label} đặt sơ bộ trong {room.label_vi}."),
                dimensions_m=_proposal(size, f"Kích thước {label} là module concept."),
                label_vi=label,
            )
        )
    return tuple(fixtures)


def _validate_rooms_inside_site(model: ArchitecturalConceptModel) -> None:
    width = float(model.site.width_m.value)
    depth = float(model.site.depth_m.value)
    for room in model.rooms:
        for x, y in room.polygon.value:
            if x < -0.001 or y < -0.001 or x > width + 0.001 or y > depth + 0.001:
                raise LayoutValidationError(f"Room {room.id} is outside site bounds")


def _validate_no_room_overlap(model: ArchitecturalConceptModel) -> None:
    for first, second in combinations(model.rooms, 2):
        if first.level_id != second.level_id:
            continue
        if _rectangles_overlap(first.polygon.value, second.polygon.value):
            raise LayoutValidationError(f"Rooms {first.id} and {second.id} overlap")


def _validate_room_access(model: ArchitecturalConceptModel) -> None:
    for floor in {room.level_id for room in model.rooms}:
        floor_rooms = [room for room in model.rooms if room.level_id == floor]
        floor_rooms.sort(key=lambda room: _bounds(room.polygon.value)[1])
        for index, room in enumerate(floor_rooms):
            if index == 0:
                continue
            previous = floor_rooms[index - 1]
            if not _rectangles_touch(previous.polygon.value, room.polygon.value) and not room.adjacency:
                raise LayoutValidationError(f"Room {room.id} has no access adjacency")


def _validate_openings_attach_to_walls(model: ArchitecturalConceptModel) -> None:
    walls = {wall.id: wall for wall in model.walls}
    for opening in model.openings:
        wall = walls.get(opening.wall_id)
        if wall is None:
            raise LayoutValidationError(f"Opening {opening.id} references missing wall")
        if wall.level_id != opening.level_id:
            raise LayoutValidationError(f"Opening {opening.id} level does not match wall")


def _validate_stairs_fit(model: ArchitecturalConceptModel) -> None:
    width = float(model.site.width_m.value)
    depth = float(model.site.depth_m.value)
    for stair in model.stairs:
        min_x, min_y, max_x, max_y = _bounds(stair.footprint.value)
        if min_x < 0 or min_y < 0 or max_x > width or max_y > depth:
            raise LayoutValidationError(f"Stair {stair.id} does not fit inside site")
        if max_x - min_x <= 0 or max_y - min_y <= 0:
            raise LayoutValidationError(f"Stair {stair.id} has invalid footprint")


def _proposal(value: object, explanation: str) -> DecisionValue:
    return DecisionValue(
        value=value,
        source="ai_proposal",
        confidence=0.74,
        assumption=True,
        customer_visible_explanation=explanation,
        needs_confirmation=False,
    )


def _bounds(points: tuple[Point, ...]) -> tuple[float, float, float, float]:
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return min(xs), min(ys), max(xs), max(ys)


def _rect_area(points: tuple[Point, ...]) -> float:
    min_x, min_y, max_x, max_y = _bounds(points)
    return max(0.0, (max_x - min_x) * (max_y - min_y))


def _rectangles_overlap(first: tuple[Point, ...], second: tuple[Point, ...]) -> bool:
    a_min_x, a_min_y, a_max_x, a_max_y = _bounds(first)
    b_min_x, b_min_y, b_max_x, b_max_y = _bounds(second)
    return a_min_x < b_max_x and a_max_x > b_min_x and a_min_y < b_max_y and a_max_y > b_min_y


def _rectangles_touch(first: tuple[Point, ...], second: tuple[Point, ...]) -> bool:
    a_min_x, a_min_y, a_max_x, a_max_y = _bounds(first)
    b_min_x, b_min_y, b_max_x, b_max_y = _bounds(second)
    horizontal_overlap = a_min_x < b_max_x and a_max_x > b_min_x
    vertical_touch = abs(a_max_y - b_min_y) < 0.001 or abs(b_max_y - a_min_y) < 0.001
    return horizontal_overlap and vertical_touch
