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
    section_lines = _generate_section_lines(width=width, depth=depth, stairs=stairs)
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
    _validate_fixtures_fit(model)
    _validate_room_area_plausibility(model)
    _validate_wet_core_alignment(model)


def _generate_rooms(program: ProgramPlan, *, width: float, depth: float, floors: int) -> tuple[ConceptRoom, ...]:
    by_floor: dict[int, list[RoomProgramItem]] = {floor: [] for floor in range(1, floors + 1)}
    for item in program.items:
        by_floor.setdefault(item.level_number, []).append(item)

    rooms: list[ConceptRoom] = []
    for floor in range(1, floors + 1):
        items = by_floor.get(floor) or []
        if program.project_type == "apartment_renovation":
            ordered = _apartment_sequence(items)
            rooms.extend(_partition_apartment_rooms(ordered, width=width, depth=depth, floor=floor))
            continue
        if floor == 1:
            ordered = _floor_one_sequence(items)
        else:
            ordered = _upper_floor_sequence(items)
        if not ordered:
            ordered = [RoomProgramItem("flex", "Không gian linh hoạt", floor, "fallback")]
        rooms.extend(_partition_townhouse_rooms(ordered, width=width, depth=depth, floor=floor))
    return tuple(rooms)


def _floor_one_sequence(items: list[RoomProgramItem]) -> list[RoomProgramItem]:
    priority = ("business", "garage", "garden", "living", "bedroom", "stair_lightwell", "kitchen_dining", "wc", "storage")
    return sorted(items, key=lambda item: priority.index(item.room_type) if item.room_type in priority else len(priority))


def _upper_floor_sequence(items: list[RoomProgramItem]) -> list[RoomProgramItem]:
    priority = ("bedroom", "work", "flex", "stair_lightwell", "wc", "prayer", "laundry", "terrace_green", "storage")
    if not any(item.room_type == "stair_lightwell" for item in items):
        floor = items[0].level_number if items else 2
        items = [*items, RoomProgramItem("stair_lightwell", "Thang + giếng trời", floor, "circulation_green_core")]
    return sorted(items, key=lambda item: priority.index(item.room_type) if item.room_type in priority else len(priority))


def _apartment_sequence(items: list[RoomProgramItem]) -> list[RoomProgramItem]:
    priority = ("living", "flex_sleep", "kitchen_dining", "work", "storage", "laundry", "wc", "bedroom")
    return sorted(items, key=lambda item: priority.index(item.room_type) if item.room_type in priority else len(priority))


def _partition_apartment_rooms(items: list[RoomProgramItem], *, width: float, depth: float, floor: int) -> list[ConceptRoom]:
    margin = 0.3
    min_x, min_y, max_x, max_y = margin, margin, width - margin, depth - margin
    bedrooms = [item for item in items if item.room_type == "bedroom"]
    living = _first_item(items, "living", floor=floor)
    kitchen = _first_item(items, "kitchen_dining", floor=floor)
    wc = _first_item(items, "wc", floor=floor)
    storage = _find_item(items, "storage")
    laundry = _find_item(items, "laundry")
    work = _find_item(items, "work")
    flex_sleep = _find_item(items, "flex_sleep")

    room_specs: list[tuple[RoomProgramItem, tuple[Point, ...], tuple[str, ...], str]] = []
    if flex_sleep is not None and not bedrooms:
        public_y2 = min(max_y - 3.6, min_y + max(2.4, depth * 0.34))
        sleep_y1 = public_y2 + 0.15
        sleep_y2 = min(max_y - 2.0, sleep_y1 + max(1.6, depth * 0.22))
        service_y1 = sleep_y2 + 0.15
        service_split_x = min(max_x - 1.7, min_x + (max_x - min_x) * 0.62)
        room_specs.append((living, _rect(min_x, min_y, max_x, public_y2), (), "studio giữ vùng sinh hoạt mở, không giả định phòng khách tách kín"))
        room_specs.append((flex_sleep, _rect(min_x, sleep_y1, max_x, sleep_y2), ("living",), "khu ngủ linh hoạt là zone concept trong studio, cần xác nhận đồ nội thất gập/mở"))
        kitchen_x1 = min_x
        if storage is not None and service_split_x - min_x >= 2.4:
            storage_x2 = min(service_split_x - 1.2, min_x + 1.3)
            room_specs.append((storage, _rect(min_x, service_y1, storage_x2, max_y), ("living", "flex_sleep"), "lưu trữ studio đặt thành dải tủ gần vùng bếp"))
            kitchen_x1 = storage_x2 + 0.1
        room_specs.append((kitchen, _rect(kitchen_x1, service_y1, service_split_x, max_y), ("living",), "bếp studio giữ dạng tuyến gọn trong lõi dịch vụ"))
        room_specs.append((wc, _rect(service_split_x + 0.1, service_y1, max_x, max_y), ("kitchen_dining",), "WC studio gom vào lõi phụ để giữ vùng ở linh hoạt"))
        return _build_rooms_from_specs(room_specs, floor=floor)

    mid_x = min(max(min_x + 3.2, width * 0.58), max_x - 2.35)
    public_y2 = min(max_y - 4.0, min_y + max(3.5, depth * 0.38))
    service_depth = max(2.05 if (storage is not None or work is not None) else 1.7, depth * 0.17)
    service_y2 = min(max_y - 3.0, public_y2 + service_depth)
    room_specs.append((living, _rect(min_x, min_y, mid_x, public_y2), (), "vùng sinh hoạt gần cửa vào và ánh sáng chính của căn hộ"))
    room_specs.append((kitchen, _rect(mid_x, min_y, max_x, public_y2), ("living",), "bếp/ăn đặt cạnh phòng khách để giữ trục sinh hoạt mở"))

    service_split_x = min(max_x - 1.9, min_x + (max_x - min_x) * 0.58)
    service_items = [item for item in (storage, work, laundry) if item is not None]
    if len(service_items) >= 2:
        cursor_x = min_x
        available = max(service_split_x - min_x, 1.8)
        for index, item in enumerate(service_items):
            remaining = len(service_items) - index
            segment_width = available / remaining
            next_x = service_split_x if remaining == 1 else min(service_split_x - 0.1, cursor_x + max(1.35, segment_width * 0.75))
            explanation = {
                "storage": "mảng lưu trữ đặt gần lối vào/khu bếp theo brief",
                "work": "góc làm việc đặt trong dải đệm, tách tương đối khỏi vùng ngủ",
                "laundry": "giặt phơi concept gom vào lõi dịch vụ căn hộ",
            }.get(item.room_type, "zone phụ căn hộ đặt trong dải dịch vụ")
            room_specs.append((item, _rect(cursor_x, public_y2, next_x, service_y2), ("living", "kitchen_dining"), explanation))
            cursor_x = next_x + 0.1
    elif storage is not None:
        room_specs.append((storage, _rect(min_x, public_y2, service_split_x, service_y2), ("living", "kitchen_dining"), "mảng lưu trữ đặt gần lối vào/khu bếp theo brief"))
    elif work is not None:
        room_specs.append((work, _rect(min_x, public_y2, service_split_x, service_y2), ("living",), "góc làm việc đặt gần vùng sinh hoạt nhưng tách khỏi phòng ngủ"))
    elif laundry is not None:
        room_specs.append((laundry, _rect(min_x, public_y2, service_split_x, service_y2), ("kitchen_dining",), "giặt phơi concept gom vào lõi dịch vụ căn hộ"))
    room_specs.append((wc, _rect(service_split_x, public_y2, max_x, service_y2), ("kitchen_dining",), "WC giữ trong lõi phụ của căn hộ ở mức concept"))

    bedroom_y1 = service_y2 + 0.2
    if bedrooms:
        if len(bedrooms) == 1:
            room_specs.append((bedrooms[0], _rect(min_x, bedroom_y1, max_x, max_y), ("living", "wc"), "phòng ngủ đặt về vùng riêng tư phía sau"))
        else:
            split_x = min_x + (max_x - min_x) / 2
            room_specs.append((bedrooms[0], _rect(min_x, bedroom_y1, split_x, max_y), ("living", "wc"), "phòng ngủ master đặt về vùng riêng tư phía sau"))
            room_specs.append((bedrooms[1], _rect(split_x, bedroom_y1, max_x, max_y), ("living", bedrooms[0].room_type), "phòng ngủ phụ chia nửa sau căn hộ để giữ diện tích gọn"))
            for extra_index, item in enumerate(bedrooms[2:], start=1):
                extra_y1 = min(max_y - 2.8 * extra_index, max_y - 2.6)
                extra_y2 = min(max_y, extra_y1 + 2.6)
                room_specs.append((item, _rect(min_x, extra_y1, max_x, extra_y2), ("living",), "phòng ngủ bổ sung là giả định concept cần xác nhận từ mặt bằng hiện trạng"))

    return _build_rooms_from_specs(room_specs, floor=floor)


def _partition_townhouse_rooms(items: list[RoomProgramItem], *, width: float, depth: float, floor: int) -> list[ConceptRoom]:
    if floor == 1:
        return _partition_townhouse_ground_floor(items, width=width, depth=depth, floor=floor)
    return _partition_townhouse_upper_floor(items, width=width, depth=depth, floor=floor)


def _partition_townhouse_ground_floor(items: list[RoomProgramItem], *, width: float, depth: float, floor: int) -> list[ConceptRoom]:
    margin = 0.3
    min_x, max_x = margin, width - margin
    min_y, max_y = margin, depth - margin
    core_x1, core_x2 = _side_core_bounds(width)
    side_gap = 0.2
    left_x2 = max(min_x + 2.4, core_x1 - side_gap)

    business = _find_item(items, "business")
    garage = _find_item(items, "garage")
    garden = _find_item(items, "garden")
    living = _first_item(items, "living", floor=floor)
    stair = _first_item(items, "stair_lightwell", floor=floor)
    kitchen = _first_item(items, "kitchen_dining", floor=floor)
    wc = _first_item(items, "wc", floor=floor)
    elder_bedroom = _find_item(items, "bedroom")
    storage = _find_item(items, "storage")

    y = min_y
    room_specs: list[tuple[RoomProgramItem, tuple[Point, ...], tuple[str, ...], str]] = []
    if business is not None:
        business_depth = min(max(3.8, depth * 0.17), 5.2, max_y - y)
        room_specs.append((business, _rect(min_x, y, max_x, y + business_depth), (), "khu kinh doanh/service đặt sát mặt tiền và cần xác nhận vận hành riêng"))
        y += business_depth

    if garage is not None:
        garage_depth = min(max(4.8, depth * 0.2), 5.6, max_y - y)
        room_specs.append((garage, _rect(min_x, y, max_x, y + garage_depth), (), "khoảng đậu xe đặt sát mặt tiền để tách xe khỏi không gian ở"))
        y += garage_depth

    if garden is not None:
        garden_depth = min(max(1.6, depth * 0.08), 2.4, max_y - y)
        room_specs.append((garden, _rect(min_x, y, max_x, y + garden_depth), _adjacency_names(room_specs, "garage", "business"), "sân vườn đệm là khoảng xanh concept giữa mặt tiền/xe và vùng ở"))
        y += garden_depth

    living_depth = min(max(4.2, depth * 0.2), 5.6, max_y - y)
    room_specs.append((living, _rect(min_x, y, max_x, y + living_depth), _adjacency_names(room_specs, "garage"), "phòng khách nối trực tiếp lối vào và làm vùng đệm sinh hoạt"))
    y += living_depth

    stair_depth = min(max(4.1, depth * 0.18), 5.1, max_y - y)
    core_y2 = min(max_y - 3.0, y + stair_depth)
    if elder_bedroom is not None:
        room_specs.append((elder_bedroom, _rect(min_x, y, left_x2, core_y2), ("living",), "phòng ngủ tầng trệt dành cho người lớn tuổi theo brief gia đình"))
        room_specs.append((stair, _rect(core_x1, y, core_x2, core_y2), ("living", elder_bedroom.room_type), "lõi thang và giếng trời đặt giữa nhà để chia public/private"))
    else:
        room_specs.append((stair, _rect(core_x1, y, core_x2, core_y2), ("living",), "lõi thang và giếng trời đặt bên hông giữa nhà để nhà hẹp vẫn có lối đi"))
    y = core_y2

    rear_service_depth = 2.1 if wc is not None or storage is not None else 0.0
    kitchen_depth = min(max(3.8, depth * 0.22), 5.8, max_y - y - rear_service_depth)
    kitchen_y2 = y + max(3.2, kitchen_depth)
    kitchen_y2 = min(kitchen_y2, max_y)
    room_specs.append((kitchen, _rect(min_x, y, max_x, kitchen_y2), ("stair_lightwell", "living"), "bếp và ăn đặt phía sau lõi thang để liên thông sân sau/khu phụ"))
    y = kitchen_y2

    if (wc is not None or storage is not None) and y < max_y - 0.8:
        service_y2 = min(max_y, y + 2.4)
        if wc is not None:
            room_specs.append((wc, _rect(core_x1, y, core_x2, service_y2), ("kitchen_dining", "stair_lightwell"), "WC gom về dải phụ sau nhà, không chiếm toàn bộ bề ngang"))
        if storage is not None and left_x2 > min_x + 1.2:
            room_specs.append((storage, _rect(min_x, y, left_x2, service_y2), ("kitchen_dining",), "kho/lưu trữ tầng trệt tận dụng dải sau bếp"))

    return _build_rooms_from_specs(room_specs, floor=floor)


def _partition_townhouse_upper_floor(items: list[RoomProgramItem], *, width: float, depth: float, floor: int) -> list[ConceptRoom]:
    margin = 0.3
    min_x, max_x = margin, width - margin
    min_y, max_y = margin, depth - margin
    core_x1, core_x2 = _side_core_bounds(width)
    bedrooms = [item for item in items if item.room_type == "bedroom"]
    stair = _first_item(items, "stair_lightwell", floor=floor)
    wcs = [item for item in items if item.room_type == "wc"]
    wc = wcs[0] if wcs else None
    extra_wcs = wcs[1:]
    work = _find_item(items, "work")
    flex = _find_item(items, "flex")
    prayer = _find_item(items, "prayer")
    laundry = _find_item(items, "laundry")
    terrace = _find_item(items, "terrace_green")
    storage = _find_item(items, "storage")

    core_depth = min(max(4.1, depth * 0.18), 5.1)
    core_y1 = min(max(min_y + 4.8, depth * 0.42), max_y - core_depth - 3.2)
    core_y2 = core_y1 + core_depth

    room_specs: list[tuple[RoomProgramItem, tuple[Point, ...], tuple[str, ...], str]] = []
    if bedrooms:
        front_depth = min(max(4.0, depth * 0.18), 5.0)
        room_specs.append((bedrooms[0], _rect(min_x, min_y, max_x, min(min_y + front_depth, core_y1 - 0.2)), (), "phòng ngủ trước lấy sáng mặt tiền nhưng giữ chiều sâu vừa phải"))

    previous_y2 = _bounds(room_specs[-1][1])[3] if room_specs else min_y
    has_pre_core_slot = not room_specs or not bedrooms or core_y1 - previous_y2 >= 2.0
    if work is not None and has_pre_core_slot:
        work_y1 = _bounds(room_specs[-1][1])[3] + 0.2 if room_specs else min_y
        work_y2 = min(core_y1 - 0.2, work_y1 + 2.2)
        if work_y2 - work_y1 >= 1.6:
            room_specs.append((work, _rect(min_x, work_y1, max_x, work_y2), _adjacency_names(room_specs, "bedroom"), "góc làm việc đặt giữa vùng ngủ và lõi thang để giảm nhiễu từ không gian chung"))

    previous_y2 = _bounds(room_specs[-1][1])[3] if room_specs else min_y
    has_pre_core_slot = not room_specs or not bedrooms or core_y1 - previous_y2 >= 2.0
    if flex is not None and work is None and has_pre_core_slot:
        flex_y1 = _bounds(room_specs[-1][1])[3] + 0.2 if room_specs else min_y
        flex_y2 = min(core_y1 - 0.2, flex_y1 + 2.2)
        if flex_y2 - flex_y1 >= 1.6:
            room_specs.append((flex, _rect(min_x, flex_y1, max_x, flex_y2), _adjacency_names(room_specs, "bedroom"), "phòng linh hoạt giữ như zone guest/work concept cần xác nhận"))

    room_specs.append((stair, _rect(core_x1, core_y1, core_x2, core_y2), _adjacency_names(room_specs, "bedroom"), "lõi thang/giếng trời xếp chồng qua các tầng để thông gió và định hướng lưu thông"))

    y = core_y2 + 0.25
    remaining_bedrooms = list(bedrooms[1:])
    if wc is not None and y < max_y - 1.6:
        wc_depth = min(2.35, max_y - y)
        room_specs.append((wc, _rect(core_x1, y, core_x2, y + wc_depth), ("stair_lightwell",), "WC tầng trên xếp trong cùng dải lõi ướt với WC tầng trệt"))
        side_bedroom_x2 = core_x1 - 0.2
        if remaining_bedrooms and side_bedroom_x2 - min_x >= 2.25:
            bedroom = remaining_bedrooms.pop(0)
            bedroom_depth = min(max(3.8, depth * 0.17), 4.8, max_y - y)
            room_specs.append((bedroom, _rect(min_x, y, side_bedroom_x2, y + bedroom_depth), ("stair_lightwell", "wc"), "phòng ngủ sau né lõi WC để giữ stacking ướt rõ ràng"))
            y += bedroom_depth + 0.25
        else:
            y += wc_depth + 0.25

    for bedroom in remaining_bedrooms:
        bedroom_depth = min(max(3.8, depth * 0.17), 4.8, max_y - y)
        room_specs.append((bedroom, _rect(min_x, y, max_x, y + bedroom_depth), ("stair_lightwell",), "phòng ngủ sau tiếp cận từ lõi thang và tách khỏi mặt tiền"))
        y += bedroom_depth + 0.25

    if prayer is not None and y < max_y - 2.0:
        prayer_depth = min(3.4, max_y - y)
        room_specs.append((prayer, _rect(min_x, y, max_x, y + prayer_depth), ("stair_lightwell",), "phòng thờ đặt tầng trên, tách khỏi vùng sinh hoạt ồn"))
        y += prayer_depth + 0.2

    support_y1 = max(y, max_y - 2.3)
    for extra_wc in extra_wcs:
        if support_y1 < max_y - 0.8:
            room_specs.append((extra_wc, _rect(core_x1, support_y1, core_x2, max_y), ("stair_lightwell",), "WC phụ tầng trên vẫn giữ trong cùng dải lõi ướt"))
    if laundry is not None and support_y1 < max_y - 0.8:
        room_specs.append((laundry, _rect(core_x1, support_y1, core_x2, max_y), ("stair_lightwell", "kitchen_dining"), "giặt phơi gom ở dải phụ phía sau/tầng trên"))
    if storage is not None and support_y1 < max_y - 0.8:
        storage_x2 = max(min_x + 1.5, core_x1 - 0.2)
        room_specs.append((storage, _rect(min_x, support_y1, storage_x2, max_y), ("stair_lightwell",), "kho/lưu trữ đặt gọn cạnh lõi phụ để giảm đồ lộ trong phòng ngủ"))
    if terrace is not None and y < max_y - 1.2:
        terrace_y1 = max(y, max_y - 3.4)
        terrace_x2 = core_x1 - 0.2 if laundry is not None else max_x
        if terrace_x2 > min_x + 1.2:
            room_specs.append((terrace, _rect(min_x, terrace_y1, terrace_x2, max_y), ("stair_lightwell", "laundry"), "sân thượng xanh đặt phía sau để có khoảng trồng cây và lấy sáng"))

    return _build_rooms_from_specs(room_specs, floor=floor)


def _build_rooms_from_specs(
    room_specs: list[tuple[RoomProgramItem, tuple[Point, ...], tuple[str, ...], str]],
    *,
    floor: int,
) -> list[ConceptRoom]:
    rooms: list[ConceptRoom] = []
    type_counts: dict[str, int] = {}
    for item, polygon, adjacency_names, explanation in room_specs:
        type_counts[item.room_type] = type_counts.get(item.room_type, 0) + 1
        room_id = f"f{floor}-{item.room_type}-{type_counts[item.room_type]}"
        adjacency = tuple(
            previous.id
            for previous in rooms
            if previous.room_type in adjacency_names or previous.label_vi in adjacency_names
        )
        if not adjacency and rooms:
            adjacency = (rooms[-1].id,)
        area = _rect_area(polygon)
        rooms.append(
            ConceptRoom(
                id=room_id,
                level_id=f"L{floor}",
                room_type=item.room_type,
                label_vi=item.label_vi,
                polygon=_proposal(polygon, f"{item.label_vi} được đặt theo {explanation}."),
                area_m2=_proposal(round(area, 2), f"Diện tích {item.label_vi} được tính từ polygon concept."),
                priority=_proposal(item.priority, f"Mức ưu tiên {item.label_vi} lấy từ brief/pattern."),
                adjacency=adjacency,
            )
        )
    return rooms


def _first_item(items: list[RoomProgramItem], room_type: str, *, floor: int) -> RoomProgramItem:
    found = _find_item(items, room_type)
    if found is not None:
        return found
    labels = {
        "living": "Phòng khách",
        "kitchen_dining": "Bếp và ăn",
        "wc": "Vệ sinh",
        "stair_lightwell": "Thang + giếng trời",
        "storage": "Kho/lưu trữ",
        "laundry": "Giặt phơi",
        "prayer": "Phòng thờ",
        "business": "Khu kinh doanh phía trước",
        "garden": "Sân vườn đệm",
        "work": "Góc làm việc",
        "flex": "Phòng linh hoạt",
        "flex_sleep": "Khu ngủ linh hoạt",
    }
    return RoomProgramItem(room_type, labels.get(room_type, room_type), floor, "assumed_support")


def _find_item(items: list[RoomProgramItem], room_type: str) -> RoomProgramItem | None:
    return next((item for item in items if item.room_type == room_type), None)


def _adjacency_names(room_specs: list[tuple[RoomProgramItem, tuple[Point, ...], tuple[str, ...], str]], *room_types: str) -> tuple[str, ...]:
    present = {item.room_type for item, *_ in room_specs}
    return tuple(room_type for room_type in room_types if room_type in present)


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
        interior_edges: dict[tuple[Point, Point], tuple[Point, Point]] = {}
        for room in rooms:
            if room.level_id != level_id:
                continue
            for start, end in _rect_edges(room.polygon.value):
                if _edge_on_site_boundary(start, end, width=width, depth=depth):
                    continue
                key = _edge_key(start, end)
                interior_edges[key] = key
        for index, (start, end) in enumerate(sorted(interior_edges.values(), key=lambda edge: (edge[0][1], edge[0][0], edge[1][1], edge[1][0]))):
            walls.append(
                ConceptWall(
                    id=f"wall-{level_id}-partition-{index + 1}",
                    level_id=level_id,
                    start=_proposal(start, "Tường ngăn concept theo ranh phòng và lõi lưu thông."),
                    end=_proposal(end, "Tường ngăn concept theo ranh phòng và lõi lưu thông."),
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
        x1, x2 = _side_core_bounds(width)
    else:
        room_x1, y1, room_x2, y2 = _bounds(stair_room.polygon.value)
        x1 = room_x1 + 0.2
        x2 = min(room_x2 - 0.2, x1 + defaults.stair_width_m.value)
    run_y2 = min(y2 - 0.2, y1 + 0.2 + defaults.stair_run_m.value)
    footprint = _rect(x1, y1 + 0.2, x2, run_y2)
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
        side = f"wall-{level_id}-right"
        if front in wall_ids:
            if floor == 1:
                has_garage = any(room.level_id == level_id and room.room_type == "garage" for room in rooms)
                has_business = any(room.level_id == level_id and room.room_type == "business" for room in rooms)
                if has_garage:
                    door_width = _proposal(min(2.8, max(2.4, width * 0.38)), "Cửa vào/xe concept lấy theo bề ngang mặt tiền và cần xác nhận chi tiết.")
                elif has_business:
                    door_width = _proposal(min(2.2, max(1.4, width * 0.32)), "Cửa khu kinh doanh concept giữ bề rộng vừa phải và cần xác nhận vận hành.")
                else:
                    door_width = defaults.main_door_width_m
                openings.append(
                    ConceptOpening(
                        id=f"d-{level_id}-main",
                        level_id=level_id,
                        wall_id=front,
                        opening_type="door",
                        width_m=door_width,
                        height_m=_proposal(2.4, "Chiều cao cửa chính concept lấy theo mặc định."),
                        sill_height_m=None,
                        operation=_proposal("sliding_or_swing" if has_garage or has_business else "swing", "Kiểu mở cửa concept là giả định sơ bộ cho mặt tiền."),
                    )
                )
            else:
                openings.append(
                    ConceptOpening(
                        id=f"w-{level_id}-front",
                        level_id=level_id,
                        wall_id=front,
                        opening_type="window",
                        width_m=defaults.window_width_m,
                        height_m=defaults.window_height_m,
                        sill_height_m=defaults.window_sill_height_m,
                        operation=_proposal("shaded_louver" if style_id == "modern_tropical" else "fixed_or_sliding", "Cửa sổ mặt tiền concept lấy từ style/default."),
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
        if side in wall_ids and any(room.level_id == level_id and room.room_type == "stair_lightwell" for room in rooms):
            openings.append(
                ConceptOpening(
                    id=f"w-{level_id}-stair-vent",
                    level_id=level_id,
                    wall_id=side,
                    opening_type="window",
                    width_m=_proposal(min(1.0, defaults.lightwell_min_width_m.value), "Ô thoáng lõi thang concept lấy theo giếng trời/style."),
                    height_m=_proposal(1.2, "Chiều cao ô thoáng lõi thang concept là giả định sơ bộ."),
                    sill_height_m=defaults.window_sill_height_m,
                    operation=_proposal("vent_louver", "Ô thoáng lõi thang ưu tiên thông gió concept."),
                )
            )
    return tuple(openings)


def _generate_fixtures(rooms: tuple[ConceptRoom, ...]) -> tuple[ConceptFixture, ...]:
    fixtures: list[ConceptFixture] = []
    for room in rooms:
        room_width, room_depth = _room_extent(room.polygon.value)
        if room.room_type == "garage":
            fixture_type, label, size = "car", "Xe ô tô", (min(2.0, room_width - 0.5), min(4.2, room_depth - 0.5))
        elif room.room_type == "business":
            fixture_type, label, size = "service_counter", "Quầy dịch vụ", (min(2.2, room_width - 0.5), 0.65)
        elif room.room_type == "garden":
            fixture_type, label, size = "plant", "Mảng xanh", (min(1.2, room_width - 0.4), min(1.2, room_depth - 0.4))
        elif room.room_type == "living":
            fixture_type, label, size = "sofa", "Sofa", (min(2.2, room_width - 0.5), 0.9)
        elif room.room_type == "flex_sleep":
            fixture_type, label, size = "convertible_bed", "Sofa giường", (min(2.0, room_width - 0.5), min(1.4, room_depth - 0.4))
        elif room.room_type in {"work", "flex"}:
            fixture_type, label, size = "desk", "Bàn làm việc", (min(1.4, room_width - 0.4), 0.7)
        elif room.room_type == "kitchen_dining":
            fixture_type, label, size = "kitchen_counter", "Bếp", (min(2.4, room_width - 0.45), 0.65)
        elif room.room_type == "bedroom":
            fixture_type, label, size = "bed", "Giường", (min(2.0, room_width - 0.45), min(1.8, room_depth - 0.45))
        elif room.room_type == "wc":
            fixture_type, label, size = "toilet", "Thiết bị WC", (min(0.8, room_width - 0.3), min(1.4, room_depth - 0.3))
        elif room.room_type in {"terrace_green", "stair_lightwell"}:
            fixture_type, label, size = "plant", "Cây xanh", (min(1.0, room_width - 0.4), min(1.0, room_depth - 0.4))
        elif room.room_type == "storage":
            fixture_type, label, size = "cabinet", "Tủ lưu trữ", (min(1.6, room_width - 0.35), 0.6)
        elif room.room_type == "laundry":
            fixture_type, label, size = "washer", "Máy giặt", (min(0.7, room_width - 0.3), min(0.7, room_depth - 0.3))
        elif room.room_type == "prayer":
            fixture_type, label, size = "altar", "Bàn thờ", (min(1.4, room_width - 0.4), 0.6)
        else:
            continue
        size = (round(max(0.45, size[0]), 3), round(max(0.45, size[1]), 3))
        center = _fixture_center(room.polygon.value, room.room_type, size)
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
    room_ids = {room.id for room in model.rooms}
    for floor in {room.level_id for room in model.rooms}:
        floor_rooms = [room for room in model.rooms if room.level_id == floor]
        floor_rooms.sort(key=lambda room: _bounds(room.polygon.value)[1])
        for index, room in enumerate(floor_rooms):
            for adjacent in room.adjacency:
                if adjacent not in room_ids:
                    raise LayoutValidationError(f"Room {room.id} references missing adjacent room {adjacent}")
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
    stair_rooms = [room for room in model.rooms if room.room_type == "stair_lightwell"]
    for stair in model.stairs:
        min_x, min_y, max_x, max_y = _bounds(stair.footprint.value)
        if min_x < 0 or min_y < 0 or max_x > width or max_y > depth:
            raise LayoutValidationError(f"Stair {stair.id} does not fit inside site")
        if max_x - min_x <= 0 or max_y - min_y <= 0:
            raise LayoutValidationError(f"Stair {stair.id} has invalid footprint")
        if stair_rooms and not any(_rect_contains(room.polygon.value, stair.footprint.value) for room in stair_rooms):
            raise LayoutValidationError(f"Stair {stair.id} is not inside a stair/lightwell room")


def _validate_fixtures_fit(model: ArchitecturalConceptModel) -> None:
    rooms = {room.id: room for room in model.rooms}
    for fixture in model.fixtures:
        if fixture.room_id is None:
            continue
        room = rooms.get(fixture.room_id)
        if room is None:
            raise LayoutValidationError(f"Fixture {fixture.id} references missing room")
        center_x, center_y = fixture.position.value
        size_x, size_y = fixture.dimensions_m.value
        min_x, min_y, max_x, max_y = _bounds(room.polygon.value)
        if center_x - size_x / 2 < min_x - 0.001 or center_x + size_x / 2 > max_x + 0.001:
            raise LayoutValidationError(f"Fixture {fixture.id} does not fit room width")
        if center_y - size_y / 2 < min_y - 0.001 or center_y + size_y / 2 > max_y + 0.001:
            raise LayoutValidationError(f"Fixture {fixture.id} does not fit room depth")


def _validate_room_area_plausibility(model: ArchitecturalConceptModel) -> None:
    min_area = {
        "wc": 2.0,
        "storage": 1.2,
        "laundry": 1.4,
        "stair_lightwell": 3.0,
        "kitchen_dining": 2.4,
        "work": 2.0,
        "flex_sleep": 4.0,
    }
    max_area = {
        "bedroom": 32.0,
        "kitchen_dining": 36.0,
        "wc": 8.0,
        "storage": 10.0,
        "laundry": 8.0,
        "stair_lightwell": 10.0,
        "garage": 38.0,
        "business": 35.0,
    }
    for room in model.rooms:
        area = float(room.area_m2.value)
        lower = min_area.get(room.room_type)
        upper = max_area.get(room.room_type)
        if lower is not None and area < lower:
            raise LayoutValidationError(f"Room {room.id} is too small for concept review")
        if upper is not None and area > upper:
            raise LayoutValidationError(f"Room {room.id} is too large for plausible concept review")


def _validate_wet_core_alignment(model: ArchitecturalConceptModel) -> None:
    wc_rooms = sorted((room for room in model.rooms if room.room_type == "wc"), key=lambda room: room.level_id)
    if len(wc_rooms) <= 1:
        return
    base = next((room for room in wc_rooms if room.level_id == "L1"), wc_rooms[0])
    base_x1, _, base_x2, _ = _bounds(base.polygon.value)
    for room in wc_rooms:
        if room.id == base.id:
            continue
        x1, _, x2, _ = _bounds(room.polygon.value)
        if min(base_x2, x2) - max(base_x1, x1) < 0.45:
            raise LayoutValidationError(f"Room {room.id} is not aligned with the wet core")


def _generate_section_lines(*, width: float, depth: float, stairs: tuple[ConceptStair, ...]) -> tuple[ConceptSectionLine, ...]:
    if stairs:
        min_x, _, max_x, _ = _bounds(stairs[0].footprint.value)
        section_x = (min_x + max_x) / 2
        intent = "stair_lightwell_section"
        explanation = "Vị trí mặt cắt concept đi qua trục thang/giếng trời."
        intent_explanation = "Mặt cắt concept diễn giải thang và vùng lấy sáng."
    else:
        section_x = width / 2
        intent = "apartment_public_private_section"
        explanation = "Vị trí mặt cắt concept đi qua trục sinh hoạt chính của căn hộ."
        intent_explanation = "Mặt cắt concept diễn giải quan hệ public/private và giả định chiều cao."
    return (
        ConceptSectionLine(
            id="section-a",
            label="A-A",
            start=_proposal((section_x, 0.0), explanation),
            end=_proposal((section_x, depth), explanation),
            intent=_proposal(intent, intent_explanation),
        ),
    )


def _rect(x1: float, y1: float, x2: float, y2: float) -> tuple[Point, ...]:
    x1, x2 = sorted((round(x1, 3), round(x2, 3)))
    y1, y2 = sorted((round(y1, 3), round(y2, 3)))
    if x2 - x1 < 0.6:
        x2 = round(x1 + 0.6, 3)
    if y2 - y1 < 0.6:
        y2 = round(y1 + 0.6, 3)
    return ((x1, y1), (x2, y1), (x2, y2), (x1, y2))


def _side_core_bounds(width: float) -> tuple[float, float]:
    margin = 0.3
    core_width = min(max(width * 0.28, 1.45), 2.0)
    x2 = width - margin
    x1 = max(margin + 1.8, x2 - core_width)
    return round(x1, 3), round(x2, 3)


def _rect_edges(points: tuple[Point, ...]) -> tuple[tuple[Point, Point], ...]:
    return tuple((points[index], points[(index + 1) % len(points)]) for index in range(len(points)))


def _edge_on_site_boundary(start: Point, end: Point, *, width: float, depth: float) -> bool:
    tolerance = 0.001
    return (
        abs(start[0]) < tolerance and abs(end[0]) < tolerance
        or abs(start[0] - width) < tolerance and abs(end[0] - width) < tolerance
        or abs(start[1]) < tolerance and abs(end[1]) < tolerance
        or abs(start[1] - depth) < tolerance and abs(end[1] - depth) < tolerance
    )


def _edge_key(start: Point, end: Point) -> tuple[Point, Point]:
    first = (round(start[0], 3), round(start[1], 3))
    second = (round(end[0], 3), round(end[1], 3))
    return (first, second) if first <= second else (second, first)


def _rect_contains(container: tuple[Point, ...], contained: tuple[Point, ...]) -> bool:
    min_x, min_y, max_x, max_y = _bounds(container)
    for x, y in contained:
        if x < min_x - 0.001 or y < min_y - 0.001 or x > max_x + 0.001 or y > max_y + 0.001:
            return False
    return True


def _fixture_center(points: tuple[Point, ...], room_type: str, size: tuple[float, float]) -> Point:
    min_x, min_y, max_x, max_y = _bounds(points)
    half_x = size[0] / 2
    half_y = size[1] / 2
    if room_type == "garage":
        raw = ((min_x + max_x) / 2, min_y + half_y + 0.45)
    elif room_type == "business":
        raw = (min_x + half_x + 0.45, min_y + half_y + 0.45)
    elif room_type == "garden":
        raw = ((min_x + max_x) / 2, (min_y + max_y) / 2)
    elif room_type == "living":
        raw = (min_x + half_x + 0.45, min_y + half_y + 0.55)
    elif room_type in {"flex_sleep", "work", "flex"}:
        raw = (min_x + half_x + 0.35, min_y + half_y + 0.35)
    elif room_type == "kitchen_dining":
        raw = (max_x - half_x - 0.35, max_y - half_y - 0.35)
    elif room_type == "bedroom":
        raw = (min_x + half_x + 0.45, min_y + half_y + 0.45)
    elif room_type == "wc":
        raw = (max_x - half_x - 0.25, min_y + half_y + 0.25)
    elif room_type in {"storage", "laundry", "prayer"}:
        raw = (min_x + half_x + 0.25, min_y + half_y + 0.25)
    else:
        raw = ((min_x + max_x) / 2, (min_y + max_y) / 2)
    return (
        round(_clamp(raw[0], min_x + half_x, max_x - half_x), 3),
        round(_clamp(raw[1], min_y + half_y, max_y - half_y), 3),
    )


def _clamp(value: float, lower: float, upper: float) -> float:
    if lower > upper:
        return (lower + upper) / 2
    return max(lower, min(upper, value))


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


def _room_extent(points: tuple[Point, ...]) -> tuple[float, float]:
    min_x, min_y, max_x, max_y = _bounds(points)
    return max_x - min_x, max_y - min_y


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
