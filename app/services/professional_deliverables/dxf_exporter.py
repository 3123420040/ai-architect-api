from __future__ import annotations

import math
from pathlib import Path

import ezdxf

from app.services.professional_deliverables.aia_layers import apply_aia_layers
from app.services.professional_deliverables.drawing_contract import DrawingProject, Fixture, Opening, SheetSpec
from app.services.professional_deliverables.pdf_generator import format_compact_m, format_dimension_m


def _new_doc(project: DrawingProject, sheet: SheetSpec):
    doc = ezdxf.new("R2018", setup=True)
    doc.header["$INSUNITS"] = 6  # meters
    doc.header["$DWGCODEPAGE"] = "UTF-8"
    apply_aia_layers(doc)
    return doc


def _add_text(msp, text: str, point: tuple[float, float], *, height: float = 0.22, layer: str = "A-ANNO-TEXT") -> None:
    entity = msp.add_text(text, dxfattribs={"layer": layer, "height": height})
    entity.dxf.insert = point


def _add_polyline(msp, points, *, layer: str, closed: bool = False, lineweight: int | None = None) -> None:
    attribs = {"layer": layer}
    if lineweight is not None:
        attribs["lineweight"] = lineweight
    msp.add_lwpolyline(points, close=closed, dxfattribs=attribs)


def _sheet_content_width(project: DrawingProject, sheet: SheetSpec) -> float:
    if sheet.kind in {"room_area_schedule", "door_window_schedule", "assumptions_style_notes", "cover_index"}:
        return 18.0
    if sheet.kind in {"elevations", "sections"}:
        return max(project.lot_width_m, project.lot_depth_m) * 2 + 3.5
    return max(project.lot_width_m + 2.8, project.lot_depth_m + 2.8, 10.0)


def _fit_cell_text(value: object, width: float) -> str:
    text = str(value)
    max_chars = max(8, int(width / 0.075))
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3].rstrip() + "..."


def _wrapped_text(value: object, *, max_chars: int = 92) -> list[str]:
    words = str(value).split()
    lines: list[str] = []
    current: list[str] = []
    for word in words:
        candidate = " ".join([*current, word])
        if len(candidate) > max_chars and current:
            lines.append(" ".join(current))
            current = [word]
        else:
            current.append(word)
    if current:
        lines.append(" ".join(current))
    return lines or [""]


def _customer_style_label(project: DrawingProject) -> str:
    metadata = project.style_metadata or {}
    label = metadata.get("customer_style_label") or metadata.get("style_display_name") or metadata.get("style_name") or project.style
    return str(label).replace("_", " ").strip() or "Concept style"


def _operation_display_label(operation: object | None) -> str:
    if operation is None:
        return "concept"
    if isinstance(operation, dict):
        operation_type = str(operation.get("type") or operation.get("operation") or operation.get("mode") or "").strip()
        hinge_side = str(operation.get("hinge_side") or operation.get("swing") or "").strip()
        parts: list[str] = []
        if operation_type == "sliding" or operation.get("sliding"):
            parts.append("truot")
        elif operation_type in {"swing", "hinged"}:
            parts.append("mo quay")
        elif operation_type == "fixed":
            parts.append("co dinh")
        elif operation_type:
            parts.append(operation_type.replace("_", " "))
        if hinge_side in {"left", "right"}:
            parts.append("ban le trai" if hinge_side == "left" else "ban le phai")
        return ", ".join(parts) or "concept"
    text = str(operation).strip()
    if not text:
        return "concept"
    return {
        "sliding": "truot",
        "swing": "mo quay",
        "hinged": "mo quay",
        "fixed": "co dinh",
        "fixed_or_sliding": "co dinh hoac truot",
        "sliding_or_swing": "truot hoac mo quay",
        "shaded_louver": "lam che nang",
        "vent_louver": "o thoang thong gio",
        "unspecified": "concept",
    }.get(text, text.replace("_", " "))


def _bounds_m(points) -> tuple[float, float, float, float]:
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return min(xs), min(ys), max(xs), max(ys)


def _room_size_label(room) -> str:
    min_x, min_y, max_x, max_y = _bounds_m(room.polygon)
    return f"{format_dimension_m(max_x - min_x)} x {format_dimension_m(max_y - min_y)}"


def _room_type_key(room) -> str:
    return str(room.original_type or room.category or "").strip().lower()


def _room_type_display_label(room) -> str:
    room_type = _room_type_key(room)
    if "bedroom" in room_type:
        return "Phong ngu"
    if "bath" in room_type or "wc" in room_type:
        return "WC / tam"
    if "kitchen" in room_type or "dining" in room_type:
        return "Bep / an"
    if "living" in room_type:
        return "Sinh hoat chung"
    if "stair" in room_type or "lightwell" in room_type or "core" in room_type:
        return "Loi thang / lay sang"
    if "storage" in room_type:
        return "Kho / luu tru"
    if "laundry" in room_type or "service" in room_type:
        return "Giat phoi / ky thuat"
    if "parking" in room_type or "garage" in room_type:
        return "Dau xe / dich vu"
    if "terrace" in room_type or "balcony" in room_type or "garden" in room_type:
        return "Khong gian ngoai"
    if "worship" in room_type:
        return "Tho / yen tinh"
    if room_type:
        return room_type.replace("_", " ").title()
    return "Khong gian concept"


def _room_schedule_note(room) -> str:
    room_type = _room_type_key(room)
    min_x, min_y, max_x, max_y = _bounds_m(room.polygon)
    if min(max_x - min_x, max_y - min_y) < 1.35:
        return "Kiem tra be ngang"
    if "stair" in room_type or "lightwell" in room_type or "core" in room_type:
        return "Loi dung concept"
    if "bath" in room_type or "wc" in room_type or "laundry" in room_type:
        return "Nhom uot/service"
    if "storage" in room_type:
        return "Diem luu tru"
    if "terrace" in room_type or "garden" in room_type or "balcony" in room_type:
        return "Khong gian thoang"
    return "Review cong nang"


def _room_needs_hatch(room) -> bool:
    room_type = _room_type_key(room)
    return any(token in room_type for token in ("bath", "wc", "laundry", "service", "stair", "lightwell", "core", "storage", "terrace", "garden", "balcony"))


def _draw_room_hatch(msp, room) -> None:
    if not _room_needs_hatch(room):
        return
    min_x, min_y, max_x, max_y = _bounds_m(room.polygon)
    spacing = 0.38
    cursor = min_x - (max_y - min_y)
    while cursor < max_x:
        start_x = max(cursor, min_x)
        start_y = min_y + max(0.0, min_x - cursor)
        end_x = min(cursor + (max_y - min_y), max_x)
        end_y = min_y + min(max_y - min_y, max_x - cursor)
        _add_polyline(msp, [(start_x, start_y), (end_x, end_y)], layer="A-ANNO-NPLT", lineweight=5)
        cursor += spacing


def _draw_title_note(msp, project: DrawingProject, sheet: SheetSpec) -> None:
    title_width = _sheet_content_width(project, sheet)
    left = -1.4
    right = left + title_width
    scale_x = left + title_width * 0.55
    date_x = left + title_width * 0.72
    _add_polyline(msp, [(left, -2.15), (right, -2.15), (right, -0.72), (left, -0.72)], layer="A-ANNO-TTLB", closed=True, lineweight=35)
    _add_polyline(msp, [(scale_x, -2.15), (scale_x, -0.72)], layer="A-ANNO-TTLB", lineweight=18)
    _add_polyline(msp, [(date_x, -2.15), (date_x, -0.72)], layer="A-ANNO-TTLB", lineweight=18)
    _add_text(msp, project.project_name, (left + 0.2, -1.2), height=0.18, layer="A-ANNO-TTLB")
    _add_text(msp, f"{sheet.number} - {sheet.title}", (left + 0.2, -1.55), height=0.16, layer="A-ANNO-TTLB")
    _add_text(msp, f"Tỷ lệ {sheet.scale}", (scale_x + 0.18, -1.2), height=0.14, layer="A-ANNO-TTLB")
    _add_text(msp, project.issue_date.isoformat(), (date_x + 0.18, -1.2), height=0.14, layer="A-ANNO-TTLB")
    _add_text(msp, _fit_cell_text(project.concept_note, title_width * 0.44), (left + 3.8, -1.55), height=0.12, layer="A-ANNO-TTLB")


def _draw_dimensions(msp, project: DrawingProject, *, x_offset: float = 0.0, y_offset: float = 0.0) -> None:
    width = project.lot_width_m
    depth = project.lot_depth_m
    _add_polyline(msp, [(x_offset, y_offset - 0.45), (x_offset + width, y_offset - 0.45)], layer="A-ANNO-DIMS", lineweight=18)
    _add_polyline(msp, [(x_offset, y_offset - 0.55), (x_offset, y_offset - 0.35)], layer="A-ANNO-DIMS", lineweight=18)
    _add_polyline(msp, [(x_offset + width, y_offset - 0.55), (x_offset + width, y_offset - 0.35)], layer="A-ANNO-DIMS", lineweight=18)
    _add_text(msp, format_dimension_m(width), (x_offset + width / 2 - 0.35, y_offset - 0.75), height=0.18, layer="A-ANNO-DIMS")
    _add_polyline(msp, [(x_offset - 0.45, y_offset), (x_offset - 0.45, y_offset + depth)], layer="A-ANNO-DIMS", lineweight=18)
    _add_polyline(msp, [(x_offset - 0.55, y_offset), (x_offset - 0.35, y_offset)], layer="A-ANNO-DIMS", lineweight=18)
    _add_polyline(msp, [(x_offset - 0.55, y_offset + depth), (x_offset - 0.35, y_offset + depth)], layer="A-ANNO-DIMS", lineweight=18)
    _add_text(msp, format_dimension_m(depth), (x_offset - 1.15, y_offset + depth / 2), height=0.18, layer="A-ANNO-DIMS")


def _draw_north_arrow(msp, base: tuple[float, float], angle_degrees: float) -> None:
    x, y = base
    angle = math.radians(-angle_degrees)
    local = [(-0.25, -0.4), (0.0, 0.4), (0.25, -0.4), (-0.25, -0.4)]
    rotated = []
    for px, py in local:
        rotated.append((x + px * math.cos(angle) - py * math.sin(angle), y + px * math.sin(angle) + py * math.cos(angle)))
    _add_polyline(msp, rotated, layer="A-ANNO-NORTH")
    _add_text(msp, f"B {angle_degrees:.0f}°", (x - 0.18, y + 0.62), height=0.2, layer="A-ANNO-NORTH")


def _fixture_layer(fixture: Fixture) -> str:
    return {
        "furniture": "A-FURN",
        "plumbing": "P-FIXT",
        "light": "E-LITE",
        "plant": "L-PLNT",
    }[fixture.kind]


def _draw_fixture(msp, fixture: Fixture) -> None:
    x, y = fixture.center
    w, h = fixture.size
    layer = _fixture_layer(fixture)
    if fixture.kind == "light":
        msp.add_circle((x, y), w / 2, dxfattribs={"layer": layer})
    elif fixture.kind == "plant":
        msp.add_circle((x, y), w / 2, dxfattribs={"layer": layer})
        _add_polyline(msp, [(x - w / 2, y), (x + w / 2, y), (x, y - h / 2), (x, y + h / 2)], layer=layer)
    else:
        _add_polyline(msp, [(x - w / 2, y - h / 2), (x + w / 2, y - h / 2), (x + w / 2, y + h / 2), (x - w / 2, y + h / 2)], layer=layer, closed=True)
    _add_text(msp, fixture.label, (x - w / 2, y + h / 2 + 0.12), height=0.12, layer="A-ANNO-TEXT")


def _draw_opening(msp, opening: Opening) -> None:
    layer = "A-DOOR" if opening.kind == "door" else "A-GLAZ"
    _add_polyline(msp, [opening.start, opening.end], layer=layer)
    if opening.kind == "door":
        sx, sy = opening.start
        ex, ey = opening.end
        radius = math.dist(opening.start, opening.end)
        if abs(sy - ey) < 0.01:
            start_angle = 0 if ex > sx else 180
            end_angle = 90 if ex > sx else 90
            msp.add_arc((sx, sy), radius, start_angle, end_angle, dxfattribs={"layer": "A-DOOR"})
        else:
            msp.add_arc((sx, sy), radius, 270, 360, dxfattribs={"layer": "A-DOOR"})
        _add_text(msp, opening.label, ((sx + ex) / 2, (sy + ey) / 2 + 0.16), height=0.12, layer="A-DOOR-IDEN")
    else:
        _add_text(msp, opening.label, ((opening.start[0] + opening.end[0]) / 2, (opening.start[1] + opening.end[1]) / 2 + 0.16), height=0.12, layer="A-ANNO-TEXT")


def _draw_floorplan(msp, project: DrawingProject, floor: int) -> None:
    _add_polyline(msp, project.site_polygon, layer="A-WALL", closed=True, lineweight=50)
    for wall in project.walls_for_floor(floor):
        _add_polyline(msp, [wall.start, wall.end], layer=wall.layer, lineweight=50 if wall.is_exterior else 25)
    for room in project.rooms_for_floor(floor):
        _add_polyline(msp, room.polygon, layer="A-AREA", closed=True, lineweight=13)
        _draw_room_hatch(msp, room)
        label_width = max(1.7, min(3.8, len(room.name) * 0.095))
        label_height = 0.58
        cx, cy = room.center
        _add_polyline(
            msp,
            [
                (cx - label_width / 2, cy - label_height / 2),
                (cx + label_width / 2, cy - label_height / 2),
                (cx + label_width / 2, cy + label_height / 2),
                (cx - label_width / 2, cy + label_height / 2),
            ],
            layer="A-ANNO-TEXT",
            closed=True,
            lineweight=9,
        )
        _add_text(msp, room.name, (cx - label_width / 2 + 0.08, cy + 0.08), height=0.16, layer="A-AREA-IDEN")
        _add_text(msp, f"{room.display_area_m2:.1f} m²", (cx - label_width / 2 + 0.08, cy - 0.18), height=0.12, layer="A-AREA-IDEN")
        _add_text(msp, _room_size_label(room), (cx - label_width / 2 + 0.08, cy - 0.42), height=0.11, layer="A-ANNO-DIMS")
    for opening in project.openings_for_floor(floor):
        _draw_opening(msp, opening)
    for fixture in project.fixtures_for_floor(floor):
        _draw_fixture(msp, fixture)
    for x, y in (
        (0.25, 0.25),
        (max(project.lot_width_m - 0.25, 0.25), 0.25),
        (0.25, max(project.lot_depth_m - 0.25, 0.25)),
        (max(project.lot_width_m - 0.25, 0.25), max(project.lot_depth_m - 0.25, 0.25)),
    ):
        _add_polyline(msp, [(x - 0.12, y - 0.12), (x + 0.12, y - 0.12), (x + 0.12, y + 0.12), (x - 0.12, y + 0.12)], layer="S-COLS", closed=True)
    _add_polyline(msp, [(0.1, project.lot_depth_m * 0.55), (min(2.0, project.lot_width_m * 0.45), project.lot_depth_m * 0.72)], layer="A-ANNO-NPLT")
    if floor == 1:
        _add_polyline(
            msp,
            [(project.lot_width_m / 2.0, 0.35), (project.lot_width_m / 2.0, min(project.lot_depth_m * 0.42, project.lot_depth_m - 0.8))],
            layer="A-ANNO-NPLT",
            lineweight=13,
        )
        _add_text(msp, "Loi vao chinh", (project.lot_width_m / 2.0 + 0.18, min(project.lot_depth_m * 0.42, project.lot_depth_m - 0.8) + 0.12), height=0.12, layer="A-ANNO-TEXT")
    _draw_dimensions(msp, project)
    _draw_north_arrow(msp, (project.lot_width_m + 0.85, max(project.lot_depth_m - 1.5, 0.8)), project.north_angle_degrees)
    _add_text(msp, f"Tang {floor}: kich thuoc phong nam trong nhan phong de review ty le.", (0.0, project.lot_depth_m + 0.55), height=0.14, layer="A-ANNO-TEXT")


def _draw_site(msp, project: DrawingProject) -> None:
    _add_polyline(msp, project.site_polygon, layer="L-SITE", closed=True, lineweight=35)
    _add_polyline(msp, project.roof_outline, layer="A-ROOF", closed=True, lineweight=25)
    _add_polyline(msp, project.site_polygon, layer="A-WALL", closed=True, lineweight=35)
    _add_polyline(msp, [(0.0, -1.12), (project.lot_width_m, -1.12), (project.lot_width_m, -0.68), (0.0, -0.68)], layer="A-ANNO-NPLT", closed=True, lineweight=12)
    _add_polyline(msp, [(project.lot_width_m / 2, -0.68), (project.lot_width_m / 2, 0.2)], layer="A-ANNO-NPLT", lineweight=18)
    _add_text(msp, "Duong tiep can / mat tien", (0.2, -1.55), height=0.16, layer="A-ANNO-TEXT")
    _add_text(msp, "Loi vao chinh", (project.lot_width_m / 2 + 0.18, 0.18), height=0.14, layer="A-ANNO-TEXT")
    for x, y in (
        (0.5, -0.5),
        (max(project.lot_width_m - 0.5, 0.5), -0.5),
        (0.5, project.lot_depth_m + 0.5),
        (max(project.lot_width_m - 0.5, 0.5), project.lot_depth_m + 0.5),
    ):
        msp.add_circle((x, y), 0.22, dxfattribs={"layer": "L-PLNT"})
    _add_text(
        msp,
        f"Ranh đất {format_compact_m(project.lot_width_m)} m x {format_compact_m(project.lot_depth_m)} m | {project.display_lot_area_m2:.1f} m²",
        (0.3, project.lot_depth_m + 0.25),
        height=0.18,
        layer="A-ANNO-TEXT",
    )
    _draw_dimensions(msp, project)
    _draw_north_arrow(msp, (project.lot_width_m + 0.85, max(project.lot_depth_m - 1.2, 0.8)), project.north_angle_degrees)


def _draw_cover_index(msp, project: DrawingProject) -> None:
    _add_text(msp, "Professional Concept 2D Package", (0.0, 9.5), height=0.32, layer="A-ANNO-TEXT")
    _add_text(msp, project.project_name, (0.0, 8.95), height=0.24, layer="A-ANNO-TEXT")
    _add_text(msp, project.concept_note, (0.0, 8.45), height=0.18, layer="A-ANNO-TEXT")
    index_lines = (
        "Muc luc: A-100 site, A-101 floor plans, A-201 elevation, A-301 section.",
        "Schedules: A-601 room areas, A-602 doors/windows, A-901 assumptions and style notes.",
        "Pham vi: concept/schematic only, not for construction or permit use.",
    )
    y = 7.9
    for line in index_lines:
        _add_text(msp, line, (0.0, y), height=0.14, layer="A-ANNO-TEXT")
        y -= 0.36
    _add_polyline(msp, [(-0.2, 7.0), (14.5, 7.0), (14.5, 10.05), (-0.2, 10.05)], layer="A-ANNO-TTLB", closed=True, lineweight=25)


def _draw_elevations(msp, project: DrawingProject) -> None:
    height = project.storeys * 3.3 + 0.8
    max_width = max(project.lot_width_m, project.lot_depth_m, 1.0)
    gap = 1.8
    col_x = max_width + gap
    upper_y = height + gap
    specs = (
        ("Bắc", 0.0, upper_y, project.lot_width_m),
        ("Nam", col_x, upper_y, project.lot_width_m),
        ("Đông", 0.0, 0.0, project.lot_depth_m),
        ("Tây", col_x, 0.0, project.lot_depth_m),
    )
    for label, ox, oy, width in specs:
        _add_polyline(msp, [(ox - 0.25, oy - 0.35), (ox + max_width + 0.25, oy - 0.35), (ox + max_width + 0.25, oy + height + 0.7), (ox - 0.25, oy + height + 0.7)], layer="A-ANNO-NPLT", closed=True, lineweight=9)
        _add_polyline(msp, [(ox, oy), (ox + width, oy), (ox + width, oy + height), (ox, oy + height)], layer="A-ELEV-OTLN", closed=True, lineweight=35)
        family = _style_family(project)
        for level in range(project.storeys):
            base_y = oy + level * 3.3 + 0.15
            panel_x1 = ox + width * (0.08 if level % 2 == 0 else 0.54)
            panel_x2 = min(ox + width - 0.08, panel_x1 + max(width * 0.34, 0.9))
            _add_polyline(msp, [(panel_x1, base_y), (panel_x2, base_y), (panel_x2, base_y + 2.95), (panel_x1, base_y + 2.95)], layer="A-ELEV-OTLN", closed=True, lineweight=9)
            opening_w = min(max(width * 0.28, 0.9), 2.2)
            win_x1 = max(ox + 0.25, min(ox + width - opening_w - 0.25, panel_x1 + 0.25))
            win_y1 = base_y + 0.85
            _add_polyline(msp, [(win_x1, win_y1), (win_x1 + opening_w, win_y1), (win_x1 + opening_w, win_y1 + 1.15), (win_x1, win_y1 + 1.15)], layer="A-GLAZ", closed=True, lineweight=18)
            if level > 0:
                _add_polyline(msp, [(win_x1 - 0.15, base_y + 0.45), (win_x1 + opening_w + 0.15, base_y + 0.45)], layer="A-ROOF", lineweight=18)
            if family in {"tropical", "indochine"}:
                for index in range(4 if family == "tropical" else 3):
                    fin_x = win_x1 + opening_w + 0.16 + index * 0.12
                    if fin_x < ox + width - 0.12:
                        _add_polyline(msp, [(fin_x, win_y1 - 0.08), (fin_x, win_y1 + 1.3)], layer="A-ELEV-OTLN", lineweight=13)
        for level in range(1, project.storeys + 1):
            _add_polyline(msp, [(ox, oy + level * 3.3), (ox + width, oy + level * 3.3)], layer="A-ELEV-OTLN", lineweight=13)
            _add_text(msp, f"L{level}", (ox + width + 0.18, oy + level * 3.3 - 0.06), height=0.12, layer="A-ANNO-TEXT")
        _add_text(msp, f"Mặt đứng {label}", (ox, oy + height + 0.28), height=0.18, layer="A-ANNO-TEXT")
    _add_text(msp, f"Style concept: {_customer_style_label(project)}", (0.0, upper_y + height + 0.8), height=0.16, layer="A-ANNO-TEXT")
    _add_text(msp, "Mat tien: nhan manh lop vat lieu, ban cong/lam che nang va cua theo style concept.", (0.0, upper_y + height + 0.45), height=0.13, layer="A-ANNO-TEXT")


def _style_family(project: DrawingProject) -> str:
    metadata = project.style_metadata or {}
    style_id = str(metadata.get("style_id") or project.style).lower()
    label = _customer_style_label(project).lower()
    if "tropical" in style_id or "nhiet doi" in label or "nhiệt đới" in label:
        return "tropical"
    if "indochine" in style_id or "dong duong" in label or "đông dương" in label:
        return "indochine"
    return "minimal"


def _draw_sections(msp, project: DrawingProject) -> None:
    height = project.storeys * 3.3 + 0.8
    gap = 1.8
    second_x = max(project.lot_width_m, project.lot_depth_m, 1.0) + gap
    for label, ox, width in (("Mặt cắt ngang", 0.0, project.lot_width_m), ("Mặt cắt dọc", second_x, project.lot_depth_m)):
        _add_polyline(msp, [(ox - 0.25, -0.35), (ox + width + 0.55, -0.35), (ox + width + 0.55, height + 0.7), (ox - 0.25, height + 0.7)], layer="A-ANNO-NPLT", closed=True, lineweight=9)
        _add_polyline(msp, [(ox, 0), (ox + width, 0), (ox + width, height), (ox, height)], layer="A-SECT-MCUT", closed=True, lineweight=35)
        for level in range(1, project.storeys + 1):
            _add_polyline(msp, [(ox, level * 3.3), (ox + width, level * 3.3)], layer="A-SECT-OTLN", lineweight=18)
            _add_text(msp, f"Cao độ L{level}", (ox + width + 0.18, level * 3.3 - 0.06), height=0.12, layer="A-ANNO-TEXT")
            _add_polyline(msp, [(ox + width + 0.55, (level - 1) * 3.3), (ox + width + 0.55, level * 3.3)], layer="A-ANNO-DIMS", lineweight=13)
            _add_text(msp, "Tang-tang 3.30 m", (ox + width + 0.72, (level - 0.5) * 3.3 + 0.08), height=0.12, layer="A-ANNO-DIMS")
            _add_text(msp, "Thong thuy ~3.00 m", (ox + width + 0.72, (level - 0.5) * 3.3 - 0.18), height=0.11, layer="A-ANNO-DIMS")
        _add_polyline(msp, [(ox + 0.5, 0.2), (ox + 2.2, 3.1), (ox + 0.5, 3.1), (ox + 2.2, 6.4)], layer="A-SECT-OTLN", lineweight=18)
        _add_text(msp, "Mat cat qua loi thang/gieng troi concept", (ox + 0.3, 0.35), height=0.12, layer="A-ANNO-TEXT")
        _add_text(msp, "Mai/parapet concept", (ox + 0.3, height - 0.35), height=0.12, layer="A-ANNO-TEXT")
        _add_text(msp, label, (ox, height + 0.28), height=0.18, layer="A-ANNO-TEXT")


def _draw_room_area_schedule(msp, project: DrawingProject) -> None:
    _add_text(msp, "Bang phong va dien tich", (0.0, 10.0), height=0.24, layer="A-ANNO-TEXT")
    y = 9.45
    widths = (1.2, 3.7, 2.2, 2.4, 1.5, 3.8)
    _draw_table(msp, ("Tang", "Phong", "Loai", "Kich thuoc", "Dien tich", "Ghi chu"), widths, 0.0, y, header_layer="A-AREA-IDEN")
    y -= 0.45
    for room in project.rooms:
        _draw_table(
            msp,
            (f"Tang {room.floor}", room.name, _room_type_display_label(room), _room_size_label(room), f"{room.display_area_m2:.1f} m2", _room_schedule_note(room)),
            widths,
            0.0,
            y,
            header_layer="A-AREA-IDEN",
            text_height=0.13,
        )
        y -= 0.38
    total_area = sum(room.display_area_m2 for room in project.rooms)
    _draw_table(msp, ("", "Tong dien tich phong concept", "", "", f"{total_area:.1f} m2", "khong thay the do dac"), widths, 0.0, y, header_layer="A-AREA-IDEN", text_height=0.13)


def _draw_door_window_schedule(msp, project: DrawingProject) -> None:
    _add_text(msp, "Bang cua di va cua so", (0.0, 10.0), height=0.24, layer="A-ANNO-TEXT")
    y = 9.45
    widths = (1.8, 1.3, 1.8, 1.4, 1.4, 4.6)
    _draw_table(msp, ("Ma", "Tang", "Loai", "Rong", "Cao", "Van hanh"), widths, 0.0, y, header_layer="A-DOOR-IDEN")
    y -= 0.45
    for opening in project.openings:
        _draw_table(
            msp,
            (
                opening.label,
                f"Tang {opening.floor}",
                "Cua di" if opening.kind == "door" else "Cua so",
                f"{opening.width_m or 0:.2f} m",
                f"{opening.height_m or 0:.2f} m",
                _operation_display_label(opening.operation),
            ),
            widths,
            0.0,
            y,
            header_layer="A-DOOR-IDEN" if opening.kind == "door" else "A-ANNO-TEXT",
            text_height=0.13,
        )
        y -= 0.38


def _draw_assumptions_style_notes(msp, project: DrawingProject) -> None:
    metadata = project.style_metadata or {}
    _add_text(msp, "Gia dinh va ghi chu style", (0.0, 10.0), height=0.24, layer="A-ANNO-TEXT")
    _add_text(msp, f"Style ID: {metadata.get('style_id') or project.style}", (0.0, 9.45), height=0.16, layer="A-ANNO-TEXT")
    _add_text(msp, f"Phong cach khach doc: {_customer_style_label(project)}", (0.0, 9.16), height=0.14, layer="A-ANNO-TEXT")
    y = 8.86
    note_lines = [f"Mat tien concept: {metadata.get('facade_strategy') or metadata.get('facade_intent') or 'theo style/profile concept.'}"]
    note_lines.extend(str(note) for note in tuple(metadata.get("drawing_notes") or ())[:4])
    palette = metadata.get("material_palette") or {}
    if isinstance(palette, dict):
        base = ", ".join(str(item) for item in palette.get("base", ())[:3])
        accent = ", ".join(str(item) for item in palette.get("accent", ())[:3])
        if base:
            note_lines.append(f"Vat lieu nen concept: {base}")
        if accent:
            note_lines.append(f"Vat lieu/diem nhan concept: {accent}")
    facade_rules = metadata.get("facade_rules") or {}
    if isinstance(facade_rules, dict):
        for key in ("massing", "screening", "greenery", "expression"):
            value = facade_rules.get(key)
            if value:
                note_lines.append(f"Luat mat tien - {key}: {value}")
    note_lines.extend(str(warning) for warning in tuple(metadata.get("planning_warnings") or ()))
    for note in note_lines:
        for line in _wrapped_text(note, max_chars=120):
            _add_text(msp, line, (0.0, y), height=0.13, layer="A-ANNO-TEXT")
            y -= 0.3
    y -= 0.18
    _add_text(msp, "Gia dinh concept:", (0.0, y), height=0.16, layer="A-ANNO-TEXT")
    y -= 0.38
    assumptions = tuple(metadata.get("assumptions") or ())
    if not assumptions:
        assumptions = ("No additional assumptions beyond the brief.",)
    for index, assumption in enumerate(assumptions, start=1):
        for line_index, line in enumerate(_wrapped_text(assumption, max_chars=118)):
            prefix = f"{index}. " if line_index == 0 else "   "
            _add_text(msp, prefix + line, (0.0, y), height=0.13, layer="A-ANNO-TEXT")
            y -= 0.3
    _add_polyline(msp, [(-0.2, y + 0.12), (17.0, y + 0.12), (17.0, 10.25), (-0.2, 10.25)], layer="A-ANNO-TTLB", closed=True, lineweight=18)


def _draw_table(
    msp,
    values: tuple[object, ...],
    widths: tuple[float, ...],
    x: float,
    y: float,
    *,
    header_layer: str,
    text_height: float = 0.14,
) -> None:
    cursor = x
    row_height = 0.34
    for value, width in zip(values, widths):
        _add_polyline(
            msp,
            [(cursor, y - 0.12), (cursor + width, y - 0.12), (cursor + width, y + row_height), (cursor, y + row_height)],
            layer="A-ANNO-TTLB",
            closed=True,
            lineweight=9,
        )
        _add_text(msp, _fit_cell_text(value, width - 0.14), (cursor + 0.08, y + 0.02), height=text_height, layer=header_layer)
        cursor += width


def build_dxf_document(project: DrawingProject, sheet: SheetSpec):
    doc = _new_doc(project, sheet)
    msp = doc.modelspace()
    if sheet.kind == "cover_index":
        _draw_cover_index(msp, project)
    elif sheet.kind == "site":
        _draw_site(msp, project)
    elif sheet.kind == "floorplan":
        if sheet.floor is None:
            raise ValueError("floorplan sheet requires floor")
        _draw_floorplan(msp, project, sheet.floor)
    elif sheet.kind == "elevations":
        _draw_elevations(msp, project)
    elif sheet.kind == "sections":
        _draw_sections(msp, project)
    elif sheet.kind == "room_area_schedule":
        _draw_room_area_schedule(msp, project)
    elif sheet.kind == "door_window_schedule":
        _draw_door_window_schedule(msp, project)
    elif sheet.kind == "assumptions_style_notes":
        _draw_assumptions_style_notes(msp, project)
    else:
        raise ValueError(f"Unsupported sheet kind {sheet.kind}")
    _draw_title_note(msp, project, sheet)
    return doc


def write_dxf_sheet(project: DrawingProject, sheet: SheetSpec, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / sheet.dxf_filename
    doc = build_dxf_document(project, sheet)
    doc.saveas(path)
    return path


def write_dxf_sheets(project: DrawingProject, sheets: tuple[SheetSpec, ...], output_dir: Path) -> list[Path]:
    return [write_dxf_sheet(project, sheet, output_dir) for sheet in sheets]
