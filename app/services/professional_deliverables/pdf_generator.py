from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from reportlab.lib import colors
from reportlab.lib.pagesizes import A3, landscape
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

from app.services.professional_deliverables.drawing_contract import DrawingProject, Fixture, Opening, SheetSpec

PAGE_SIZE = landscape(A3)
PT_PER_MM = 72.0 / 25.4
SCALE_1_100_PT_PER_M = 10.0 * PT_PER_MM
MARGIN = 28.0
TITLE_BLOCK_HEIGHT = 86.0
CONTENT_BOTTOM = MARGIN + TITLE_BLOCK_HEIGHT + 34.0
CONTENT_TOP = PAGE_SIZE[1] - MARGIN - 28.0
FONT_DIR = Path(__file__).resolve().parent / "assets" / "fonts"
FONT_REGULAR = FONT_DIR / "BeVietnamPro-Regular.ttf"
FONT_SEMIBOLD = FONT_DIR / "BeVietnamPro-SemiBold.ttf"
FONT_NAME = "BeVietnamPro"
FONT_BOLD = "BeVietnamPro-SemiBold"
INK = colors.HexColor("#202124")
MUTED_INK = colors.HexColor("#5f6368")
GRID_STROKE = colors.HexColor("#9aa0a6")
ROOM_STROKE = colors.HexColor("#9c5aa4")
ROOM_FILL = colors.HexColor("#fbf7fc")
NOTE_FILL = colors.HexColor("#f8f9fa")
HEADER_FILL = colors.HexColor("#eef2f6")
SITE_FILL = colors.HexColor("#f7fbf7")


@dataclass(frozen=True)
class RoomLabelBox:
    room_id: str
    floor: int
    rect: tuple[float, float, float, float]
    room_rect: tuple[float, float, float, float]
    label_size: float
    area_size: float
    show_size: bool


def format_dimension_m(value: float) -> str:
    return f"{value:.2f} m"


def format_compact_m(value: float) -> str:
    if abs(value - round(value)) < 0.005:
        return str(int(round(value)))
    return f"{value:.2f}".rstrip("0").rstrip(".")


def plan_layout(project: DrawingProject) -> tuple[float, float, float]:
    available_width = PAGE_SIZE[0] - 2 * MARGIN - 132.0
    available_height = CONTENT_TOP - CONTENT_BOTTOM - 26.0
    required_width_m = max(project.lot_width_m + 1.4, 1.0)
    required_height_m = max(project.lot_depth_m + 1.4, 1.0)
    scale = min(SCALE_1_100_PT_PER_M, available_width / required_width_m, available_height / required_height_m)
    drawing_width = project.lot_width_m * scale
    drawing_height = project.lot_depth_m * scale
    x = (PAGE_SIZE[0] - drawing_width) / 2.0
    y = CONTENT_BOTTOM + (CONTENT_TOP - CONTENT_BOTTOM - drawing_height) / 2.0
    return x, y, scale


def effective_scale_label(project: DrawingProject) -> str:
    _, _, scale = plan_layout(project)
    denominator = max(1, round(100 * SCALE_1_100_PT_PER_M / scale))
    rounded = int(round(denominator / 10.0) * 10)
    return "1:100" if rounded <= 100 else f"1:{rounded}"


def register_fonts() -> None:
    if FONT_NAME not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont(FONT_NAME, FONT_REGULAR))
    if FONT_BOLD not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont(FONT_BOLD, FONT_SEMIBOLD))


def _set_font(c: canvas.Canvas, size: float, *, bold: bool = False) -> None:
    c.setFont(FONT_BOLD if bold else FONT_NAME, size)


def _text_width(value: str, size: float, *, bold: bool = False) -> float:
    return pdfmetrics.stringWidth(value, FONT_BOLD if bold else FONT_NAME, size)


def _fit_text(value: str, max_width: float, *, size: float, bold: bool = False) -> str:
    text = str(value)
    if _text_width(text, size, bold=bold) <= max_width:
        return text
    suffix = "..."
    available = max(0.0, max_width - _text_width(suffix, size, bold=bold))
    output = ""
    for character in text:
        candidate = output + character
        if _text_width(candidate, size, bold=bold) > available:
            break
        output = candidate
    return (output.rstrip() + suffix) if output else suffix


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
            parts.append("trượt")
        elif operation_type in {"swing", "hinged"}:
            parts.append("mở quay")
        elif operation_type == "fixed":
            parts.append("cố định")
        elif operation_type:
            parts.append(operation_type.replace("_", " "))
        if hinge_side in {"left", "right"}:
            parts.append("bản lề trái" if hinge_side == "left" else "bản lề phải")
        return ", ".join(parts) or "concept"
    text = str(operation).strip()
    if not text:
        return "concept"
    return {
        "sliding": "trượt",
        "swing": "mở quay",
        "hinged": "mở quay",
        "fixed": "cố định",
        "fixed_or_sliding": "cố định hoặc trượt",
        "sliding_or_swing": "trượt hoặc mở quay",
        "shaded_louver": "lam che nắng",
        "vent_louver": "ô thoáng thông gió",
        "screened_reduced_glass": "màn/lam giảm kính",
        "shuttered_screen": "shutter/màn nhẹ",
        "unspecified": "concept",
    }.get(text, text.replace("_", " "))


def _project_descriptor(project: DrawingProject) -> str:
    return (
        f"{format_compact_m(project.lot_width_m)} m x {format_compact_m(project.lot_depth_m)} m"
        f" | {project.storeys} tầng | {_customer_style_label(project)}"
    )


def _draw_title_block(c: canvas.Canvas, project: DrawingProject, sheet: SheetSpec, *, scale_label: str | None = None) -> None:
    width, _ = PAGE_SIZE
    y = MARGIN
    c.setFillColor(colors.white)
    c.setStrokeColor(INK)
    c.setLineWidth(1.2)
    c.rect(MARGIN, y, width - 2 * MARGIN, TITLE_BLOCK_HEIGHT, stroke=1, fill=1)
    c.line(width * 0.58, y, width * 0.58, y + TITLE_BLOCK_HEIGHT)
    c.line(width * 0.73, y, width * 0.73, y + TITLE_BLOCK_HEIGHT)
    c.line(width * 0.86, y, width * 0.86, y + TITLE_BLOCK_HEIGHT)
    _set_font(c, 10, bold=True)
    c.drawString(MARGIN + 12, y + 58, "AI Architect")
    _set_font(c, 8)
    c.drawString(MARGIN + 12, y + 38, "Hồ sơ trình bày phương án")
    c.drawString(MARGIN + 12, y + 20, "Concept review only")
    _set_font(c, 12, bold=True)
    c.drawString(MARGIN + 168, y + 58, _fit_text(project.project_name, width * 0.58 - (MARGIN + 180), size=12, bold=True))
    _set_font(c, 9)
    c.drawString(MARGIN + 168, y + 38, _fit_text(sheet.title, width * 0.58 - (MARGIN + 180), size=9))
    c.drawString(MARGIN + 168, y + 20, _fit_text(project.concept_note, width * 0.58 - (MARGIN + 180), size=9))
    _set_font(c, 7)
    c.setFillColor(MUTED_INK)
    c.drawString(MARGIN + 168, y + 8, _fit_text(_project_descriptor(project), width * 0.58 - (MARGIN + 180), size=7))
    c.setFillColor(INK)
    x = width * 0.59
    _set_font(c, 8)
    c.drawString(x, y + 58, "Số bản vẽ")
    _set_font(c, 14, bold=True)
    c.drawString(x, y + 34, sheet.number)
    x = width * 0.74
    _set_font(c, 8)
    c.drawString(x, y + 58, "Tỷ lệ")
    _set_font(c, 13, bold=True)
    c.drawString(x, y + 34, scale_label or sheet.scale)
    x = width * 0.87
    _set_font(c, 8)
    c.drawString(x, y + 58, "Ngày")
    _set_font(c, 10, bold=True)
    c.drawString(x, y + 36, project.issue_date.isoformat())
    _set_font(c, 8)
    c.drawString(x, y + 18, "Bản concept")


def _draw_sheet_heading(c: canvas.Canvas, project: DrawingProject, sheet: SheetSpec) -> None:
    x = MARGIN
    y = PAGE_SIZE[1] - MARGIN - 4
    _set_font(c, 16, bold=True)
    c.setFillColor(INK)
    c.drawString(x, y, f"{sheet.number} - {sheet.title}")
    _set_font(c, 8)
    c.setFillColor(MUTED_INK)
    c.drawString(x, y - 15, _fit_text(project.concept_note, PAGE_SIZE[0] - 2 * MARGIN, size=8))
    c.setFillColor(INK)


def _plan_origin(project: DrawingProject, *, scale: float | None = None) -> tuple[float, float]:
    x, y, computed_scale = plan_layout(project)
    if scale is None or abs(scale - computed_scale) <= 0.001:
        return x, y
    drawing_width = project.lot_width_m * scale
    drawing_height = project.lot_depth_m * scale
    return (PAGE_SIZE[0] - drawing_width) / 2.0, CONTENT_BOTTOM + (CONTENT_TOP - CONTENT_BOTTOM - drawing_height) / 2.0


def _transform(project: DrawingProject, *, offset_x: float = 0.0, offset_y: float = 0.0, scale: float | None = None) -> Callable[[float, float], tuple[float, float]]:
    effective_scale = scale or plan_layout(project)[2]
    ox, oy = _plan_origin(project, scale=effective_scale)

    def tx(x: float, y: float) -> tuple[float, float]:
        return ox + offset_x + x * effective_scale, oy + offset_y + y * effective_scale

    return tx


def _poly(
    c: canvas.Canvas,
    points: tuple[tuple[float, float], ...] | list[tuple[float, float]],
    tx: Callable[[float, float], tuple[float, float]],
    *,
    close: bool = False,
    stroke=colors.black,
    width: float = 1.0,
    fill=None,
) -> None:
    c.setStrokeColor(stroke)
    c.setLineWidth(width)
    if fill is not None:
        c.setFillColor(fill)
    path = c.beginPath()
    x0, y0 = tx(*points[0])
    path.moveTo(x0, y0)
    for point in points[1:]:
        x, y = tx(*point)
        path.lineTo(x, y)
    if close:
        path.close()
    c.drawPath(path, stroke=1, fill=1 if fill is not None else 0)


def _text(c: canvas.Canvas, value: str, x: float, y: float, *, size: float = 8, bold: bool = False, color=colors.black) -> None:
    c.setFillColor(color)
    _set_font(c, size, bold=bold)
    c.drawString(x, y, value)


def _wrapped_lines(value: str, *, max_chars: int = 92) -> list[str]:
    words = value.split()
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


def _draw_text_lines(
    c: canvas.Canvas,
    lines: list[str] | tuple[str, ...],
    x: float,
    y: float,
    *,
    size: float = 8,
    leading: float = 13,
    bold: bool = False,
    color=colors.black,
) -> float:
    cursor = y
    for line in lines:
        _text(c, line, x, cursor, size=size, bold=bold, color=color)
        cursor -= leading
    return cursor


def _point_bounds(points: tuple[tuple[float, float], ...] | list[tuple[float, float]], tx: Callable[[float, float], tuple[float, float]]) -> tuple[float, float, float, float]:
    transformed = [tx(*point) for point in points]
    xs = [point[0] for point in transformed]
    ys = [point[1] for point in transformed]
    return min(xs), min(ys), max(xs), max(ys)


def _bounds_m(points: tuple[tuple[float, float], ...] | list[tuple[float, float]]) -> tuple[float, float, float, float]:
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return min(xs), min(ys), max(xs), max(ys)


def _room_type_key(room) -> str:
    return str(room.original_type or room.category or "").strip().lower()


def _room_type_display_label(room) -> str:
    room_type = _room_type_key(room)
    if "bedroom" in room_type:
        return "Phòng ngủ"
    if "bath" in room_type or "wc" in room_type:
        return "WC / tắm"
    if "kitchen" in room_type or "dining" in room_type:
        return "Bếp / ăn"
    if "living" in room_type:
        return "Sinh hoạt chung"
    if "stair" in room_type or "lightwell" in room_type or "core" in room_type:
        return "Lõi thang / lấy sáng"
    if "storage" in room_type:
        return "Kho / lưu trữ"
    if "laundry" in room_type or "service" in room_type:
        return "Giặt phơi / kỹ thuật"
    if "parking" in room_type or "garage" in room_type:
        return "Đậu xe / dịch vụ"
    if "terrace" in room_type or "balcony" in room_type or "garden" in room_type:
        return "Không gian ngoài"
    if "worship" in room_type:
        return "Thờ / yên tĩnh"
    if room_type:
        return room_type.replace("_", " ").title()
    return "Không gian concept"


def _room_schedule_note(room) -> str:
    room_type = _room_type_key(room)
    min_x, min_y, max_x, max_y = _bounds_m(room.polygon)
    width_m = max_x - min_x
    depth_m = max_y - min_y
    if min(width_m, depth_m) < 1.35:
        return "Cần kiểm tra bề ngang khi phát triển thiết kế"
    if "stair" in room_type or "lightwell" in room_type or "core" in room_type:
        return "Lõi đứng concept để đọc thông tầng"
    if "bath" in room_type or "wc" in room_type or "laundry" in room_type:
        return "Nhóm ướt/service để kiểm tra stacking"
    if "storage" in room_type:
        return "Điểm lưu trữ theo ưu tiên brief"
    if "terrace" in room_type or "garden" in room_type or "balcony" in room_type:
        return "Không gian ngoài trời/thoáng ở mức concept"
    return "Kích thước sơ bộ để review công năng"


def _room_size_label(room) -> str:
    min_x, min_y, max_x, max_y = _bounds_m(room.polygon)
    width_m = max_x - min_x
    depth_m = max_y - min_y
    return f"{format_dimension_m(width_m)} x {format_dimension_m(depth_m)}"


def _clamp(value: float, lower: float, upper: float) -> float:
    if upper < lower:
        return lower
    return max(lower, min(upper, value))


def _room_label_box(room, tx: Callable[[float, float], tuple[float, float]]) -> RoomLabelBox:
    min_x, min_y, max_x, max_y = _point_bounds(room.polygon, tx)
    room_width = max_x - min_x
    room_height = max_y - min_y
    max_label_width = max(4.0, room_width - 4.0)
    label_width = min(max(room_width - 8.0, 58.0), 132.0, max_label_width)
    max_label_height = max(8.0, room_height - 4.0)
    label_height = min(34.0 if room_height >= 42.0 else 27.0, max_label_height)
    show_size = label_width >= 50.0 and label_height >= 28.0
    if label_width < 58.0 or label_height < 27.0:
        label_size = 5.1
    elif label_width >= 78.0 and room_height >= 34.0:
        label_size = 7.1
    else:
        label_size = 5.9
    area_size = max(4.8, label_size - 0.8)
    center_x, center_y = tx(*room.center)
    box_x = _clamp(center_x - label_width / 2.0, min_x + 2.0, max_x - label_width - 2.0)
    box_y = _clamp(center_y - label_height / 2.0, min_y + 2.0, max_y - label_height - 2.0)
    return RoomLabelBox(
        room_id=room.id,
        floor=room.floor,
        rect=(box_x, box_y, box_x + label_width, box_y + label_height),
        room_rect=(min_x, min_y, max_x, max_y),
        label_size=label_size,
        area_size=area_size,
        show_size=show_size,
    )


def room_label_boxes(project: DrawingProject, floor: int) -> tuple[RoomLabelBox, ...]:
    tx = _transform(project)
    return tuple(_room_label_box(room, tx) for room in project.rooms_for_floor(floor))


def _draw_room_label(c: canvas.Canvas, room, tx: Callable[[float, float], tuple[float, float]]) -> None:
    label = _room_label_box(room, tx)
    box_x1, box_y1, box_x2, box_y2 = label.rect
    label_width = box_x2 - box_x1
    label_height = box_y2 - box_y1
    c.setFillColor(colors.white)
    c.setStrokeColor(colors.HexColor("#c9a0cf"))
    c.setLineWidth(0.35)
    c.roundRect(box_x1, box_y1, label_width, label_height, 2.5, stroke=1, fill=1)
    _text(c, _fit_text(room.name, label_width - 8, size=label.label_size, bold=True), box_x1 + 4, box_y1 + label_height - 10, size=label.label_size, bold=True, color=colors.darkmagenta)
    _text(c, f"{room.display_area_m2:.1f} m²", box_x1 + 4, box_y1 + label_height - 20, size=label.area_size, color=colors.darkmagenta)
    if label.show_size:
        _text(c, _fit_text(_room_size_label(room), label_width - 8, size=label.area_size), box_x1 + 4, box_y1 + 5, size=label.area_size, color=colors.darkmagenta)


def _draw_plan_key(c: canvas.Canvas, project: DrawingProject) -> None:
    x = PAGE_SIZE[0] - MARGIN - 118
    y = CONTENT_TOP - 124
    width = 104
    height = 112
    c.setFillColor(NOTE_FILL)
    c.setStrokeColor(GRID_STROKE)
    c.setLineWidth(0.5)
    c.rect(x, y, width, height, stroke=1, fill=1)
    _text(c, "Ghi chú đọc bản vẽ", x + 8, y + height - 16, size=7.2, bold=True, color=INK)
    samples = (
        ("Tường bao", 1.8, INK),
        ("Tường ngăn", 0.8, GRID_STROKE),
        ("Cửa/cửa sổ", 1.1, colors.darkcyan),
        ("Kích thước", 0.7, colors.red),
    )
    cursor = y + height - 34
    for label, line_width, color in samples:
        c.setStrokeColor(color)
        c.setLineWidth(line_width)
        c.line(x + 8, cursor + 4, x + 34, cursor + 4)
        _text(c, label, x + 40, cursor, size=6.6, color=INK)
        cursor -= 17
    c.setFillColor(colors.white)
    c.setStrokeColor(colors.HexColor("#d0d7de"))
    c.roundRect(x + 8, y + 10, width - 16, 20, 3, stroke=1, fill=1)
    _text(c, _fit_text(_customer_style_label(project), width - 24, size=6.3), x + 12, y + 17, size=6.3, color=MUTED_INK)


def _draw_floor_room_index(c: canvas.Canvas, project: DrawingProject, floor: int) -> None:
    rooms = project.rooms_for_floor(floor)
    if not rooms:
        return
    x = PAGE_SIZE[0] - MARGIN - 154
    y = CONTENT_TOP - 254
    width = 140
    height = min(170, 28 + len(rooms[:9]) * 14)
    c.setFillColor(colors.white)
    c.setStrokeColor(colors.HexColor("#d0d7de"))
    c.setLineWidth(0.4)
    c.roundRect(x, y - height, width, height, 4, stroke=1, fill=1)
    _text(c, f"Danh mục phòng tầng {floor}", x + 8, y - 14, size=6.8, bold=True, color=INK)
    cursor = y - 30
    for room in rooms[:9]:
        _text(c, f"{room.name} - {room.display_area_m2:.1f} m²", x + 8, cursor, size=5.6, color=MUTED_INK)
        cursor -= 13
    if len(rooms) > 9:
        _text(c, f"+ {len(rooms) - 9} phòng xem bảng A-601", x + 8, cursor, size=5.6, color=MUTED_INK)


def _draw_cover_index(c: canvas.Canvas, project: DrawingProject, sheets: tuple[SheetSpec, ...]) -> None:
    x = MARGIN + 22
    y = CONTENT_TOP - 12
    _draw_text_lines(c, ["Professional Concept 2D Package", project.project_name], x, y, size=17, leading=24, bold=True)
    y -= 68
    _draw_text_lines(
        c,
        [
            project.concept_note,
            f"Quy mô concept: {format_compact_m(project.lot_width_m)} m x {format_compact_m(project.lot_depth_m)} m, {project.storeys} tầng",
            f"Phong cách định hướng: {_customer_style_label(project)}",
        ],
        x,
        y,
        size=9,
        leading=16,
    )
    y -= 92
    _text(c, "Mục lục bản vẽ", x, y, size=12, bold=True)
    y -= 22
    for sheet in sheets:
        _text(c, sheet.number, x, y, size=8, bold=True)
        _text(c, sheet.title, x + 78, y, size=8)
        y -= 15
    y -= 20
    _text(c, "Phạm vi", x, y, size=12, bold=True)
    y -= 18
    scope_lines = [
        "Hồ sơ dùng để trao đổi phương án concept/schematic với khách hàng.",
        "Không dùng cho thi công, xin phép, kết cấu, MEP, địa kỹ thuật, pháp lý hoặc xác nhận tuân thủ địa phương.",
    ]
    for line in scope_lines:
        for wrapped in _wrapped_lines(line, max_chars=108):
            _text(c, wrapped, x, y, size=8)
            y -= 13
    metadata = project.style_metadata or {}
    assumptions = tuple(metadata.get("assumptions") or ())
    if assumptions and y > CONTENT_BOTTOM + 62:
        y -= 16
        _text(c, "Giả định chính", x, y, size=12, bold=True)
        y -= 18
        for index, assumption in enumerate(assumptions[:4], start=1):
            for wrapped in _wrapped_lines(f"{index}. {assumption}", max_chars=108):
                _text(c, wrapped, x, y, size=8)
                y -= 13


def _draw_dimensions(c: canvas.Canvas, project: DrawingProject, tx: Callable[[float, float], tuple[float, float]]) -> None:
    c.setStrokeColor(colors.red)
    c.setLineWidth(0.7)
    x1, y1 = tx(0, -0.55)
    x2, y2 = tx(project.lot_width_m, -0.55)
    c.line(x1, y1, x2, y2)
    c.line(x1, y1 - 4, x1, y1 + 4)
    c.line(x2, y2 - 4, x2, y2 + 4)
    _text(c, format_dimension_m(project.lot_width_m), (x1 + x2) / 2 - 18, y1 - 12, size=7, color=colors.red)
    x3, y3 = tx(-0.55, 0)
    x4, y4 = tx(-0.55, project.lot_depth_m)
    c.line(x3, y3, x4, y4)
    c.line(x3 - 4, y3, x3 + 4, y3)
    c.line(x4 - 4, y4, x4 + 4, y4)
    _text(c, format_dimension_m(project.lot_depth_m), x3 - 34, (y3 + y4) / 2, size=7, color=colors.red)
    sx, sy = tx(project.lot_width_m + 0.7, 0)
    _, _, scale = plan_layout(project)
    c.line(sx, sy, sx + scale, sy)
    c.line(sx, sy - 3, sx, sy + 3)
    c.line(sx + scale, sy - 3, sx + scale, sy + 3)
    _text(c, "1 m", sx + 5, sy + 6, size=7, color=colors.red)


def _draw_north_arrow(c: canvas.Canvas, x: float, y: float, angle_degrees: float) -> None:
    c.setStrokeColor(colors.red)
    c.setLineWidth(1.0)
    c.saveState()
    c.translate(x + 8, y + 14)
    c.rotate(-angle_degrees)
    path = c.beginPath()
    path.moveTo(-8, -14)
    path.lineTo(0, 14)
    path.lineTo(8, -14)
    path.close()
    c.drawPath(path, stroke=1, fill=0)
    c.restoreState()
    _text(c, "B", x + 5, y + 34, size=8, bold=True, color=colors.red)
    _text(c, f"Hướng Bắc {angle_degrees:.0f}°", x - 18, y - 12, size=7, color=colors.red)


def _draw_opening(c: canvas.Canvas, opening: Opening, tx: Callable[[float, float], tuple[float, float]]) -> None:
    c.setStrokeColor(colors.darkcyan if opening.kind == "window" else colors.darkgoldenrod)
    c.setLineWidth(1.35)
    x1, y1 = tx(*opening.start)
    x2, y2 = tx(*opening.end)
    c.line(x1, y1, x2, y2)
    if opening.kind == "door":
        radius = ((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5
        c.arc(x1 - radius, y1, x1 + radius, y1 + radius * 2, 0, 90)
    label_x = (x1 + x2) / 2
    label_y = (y1 + y2) / 2 + 5
    c.setFillColor(colors.white)
    c.setStrokeColor(colors.HexColor("#f0d0d0"))
    c.setLineWidth(0.25)
    c.rect(label_x - 2, label_y - 2, _text_width(opening.label, 6) + 4, 8, stroke=1, fill=1)
    _text(c, opening.label, label_x, label_y, size=6, color=colors.darkred)


def _draw_fixture(c: canvas.Canvas, fixture: Fixture, tx: Callable[[float, float], tuple[float, float]], *, scale: float) -> None:
    x, y = tx(*fixture.center)
    w = fixture.size[0] * scale
    h = fixture.size[1] * scale
    c.setStrokeColor(colors.darkgreen)
    c.setLineWidth(0.8)
    if fixture.kind in {"light", "plant"}:
        c.circle(x, y, w / 2.0, stroke=1, fill=0)
    else:
        c.rect(x - w / 2.0, y - h / 2.0, w, h, stroke=1, fill=0)
    _text(c, fixture.label, x - w / 2.0, y + h / 2.0 + 4, size=5.5, color=colors.darkgreen)


def _room_fill(room):
    room_type = _room_type_key(room)
    if "bath" in room_type or "wc" in room_type or "laundry" in room_type or "service" in room_type:
        return colors.HexColor("#eef7fb")
    if "stair" in room_type or "lightwell" in room_type or "core" in room_type:
        return colors.HexColor("#f2f3f5")
    if "storage" in room_type:
        return colors.HexColor("#fff5dc")
    if "terrace" in room_type or "garden" in room_type or "balcony" in room_type:
        return colors.HexColor("#eef8ec")
    return ROOM_FILL


def _room_needs_hatch(room) -> bool:
    room_type = _room_type_key(room)
    return any(token in room_type for token in ("bath", "wc", "laundry", "service", "stair", "lightwell", "core", "storage", "terrace", "garden", "balcony"))


def _draw_room_hatch(c: canvas.Canvas, room, tx: Callable[[float, float], tuple[float, float]]) -> None:
    if not _room_needs_hatch(room):
        return
    min_x, min_y, max_x, max_y = _point_bounds(room.polygon, tx)
    c.setStrokeColor(colors.HexColor("#c9d1d9"))
    c.setLineWidth(0.25)
    spacing = 9.0
    cursor = min_x - (max_y - min_y)
    while cursor < max_x:
        start_x = max(cursor, min_x)
        start_y = min_y + max(0.0, min_x - cursor)
        end_x = min(cursor + (max_y - min_y), max_x)
        end_y = min_y + min(max_y - min_y, max_x - cursor)
        c.line(start_x, start_y, end_x, end_y)
        cursor += spacing


def _draw_circulation_arrow(c: canvas.Canvas, project: DrawingProject, floor: int, tx: Callable[[float, float], tuple[float, float]]) -> None:
    if floor == 1:
        start = tx(project.lot_width_m / 2.0, 0.35)
        mid = tx(project.lot_width_m / 2.0, min(project.lot_depth_m * 0.42, project.lot_depth_m - 0.8))
        label = "Luồng vào chính"
    else:
        rooms = project.rooms_for_floor(floor)
        core = next((room for room in rooms if "stair" in _room_type_key(room) or "lightwell" in _room_type_key(room) or "core" in _room_type_key(room)), None)
        if core is None:
            return
        start = tx(*core.center)
        mid = tx(project.lot_width_m / 2.0, min(project.lot_depth_m - 0.7, core.center[1] + max(project.lot_depth_m * 0.18, 1.0)))
        label = "Kết nối từ lõi thang"
    c.setStrokeColor(colors.HexColor("#1a73e8"))
    c.setLineWidth(0.8)
    c.setDash(3, 2)
    c.line(start[0], start[1], mid[0], mid[1])
    c.setDash()
    c.line(mid[0], mid[1], mid[0] - 4, mid[1] - 7)
    c.line(mid[0], mid[1], mid[0] + 4, mid[1] - 7)
    _text(c, label, mid[0] + 6, mid[1] + 4, size=6.2, color=colors.HexColor("#1a73e8"))


def _draw_floorplan(c: canvas.Canvas, project: DrawingProject, sheet: SheetSpec) -> None:
    assert sheet.floor is not None
    _, _, scale = plan_layout(project)
    tx = _transform(project)
    _poly(c, project.site_polygon, tx, close=True, stroke=INK, width=1.2, fill=colors.HexColor("#fffdf8"))
    for room in project.rooms_for_floor(sheet.floor):
        _poly(c, room.polygon, tx, close=True, stroke=ROOM_STROKE, width=0.45, fill=_room_fill(room))
        _draw_room_hatch(c, room, tx)
    for wall in project.walls_for_floor(sheet.floor):
        _poly(
            c,
            [wall.start, wall.end],
            tx,
            stroke=INK if wall.is_exterior else GRID_STROKE,
            width=1.85 if wall.is_exterior else 0.85,
        )
    for opening in project.openings_for_floor(sheet.floor):
        _draw_opening(c, opening, tx)
    for fixture in project.fixtures_for_floor(sheet.floor):
        _draw_fixture(c, fixture, tx, scale=scale)
    for room in project.rooms_for_floor(sheet.floor):
        _draw_room_label(c, room, tx)
    _draw_circulation_arrow(c, project, sheet.floor, tx)
    _draw_floorplan_intent_notes(c, project, sheet.floor)
    _draw_dimensions(c, project, tx)
    _draw_north_arrow(c, PAGE_SIZE[0] - 112, PAGE_SIZE[1] - 122, project.north_angle_degrees)
    _draw_plan_key(c, project)
    _draw_floor_room_index(c, project, sheet.floor)


def _draw_site(c: canvas.Canvas, project: DrawingProject) -> None:
    tx = _transform(project)
    _poly(c, project.site_polygon, tx, close=True, stroke=colors.brown, width=1.5, fill=SITE_FILL)
    _poly(c, project.roof_outline, tx, close=True, stroke=INK, width=1.2)
    road_y1 = -1.12
    road_y2 = -0.68
    road_points = ((0.0, road_y1), (project.lot_width_m, road_y1), (project.lot_width_m, road_y2), (0.0, road_y2))
    _poly(c, road_points, tx, close=True, stroke=colors.HexColor("#8a8f98"), width=0.6, fill=colors.HexColor("#f0f1f2"))
    entry_x, entry_y = tx(project.lot_width_m / 2.0, -0.66)
    lot_entry_x, lot_entry_y = tx(project.lot_width_m / 2.0, 0.18)
    c.setStrokeColor(colors.HexColor("#1a73e8"))
    c.setLineWidth(1.0)
    c.line(entry_x, entry_y, lot_entry_x, lot_entry_y)
    c.line(lot_entry_x, lot_entry_y, lot_entry_x - 5, lot_entry_y - 7)
    c.line(lot_entry_x, lot_entry_y, lot_entry_x + 5, lot_entry_y - 7)
    _text(c, "Đường tiếp cận / mặt tiền", entry_x - 44, entry_y - 12, size=6.4, color=colors.HexColor("#1a73e8"))
    _text(c, "Lối vào chính", lot_entry_x + 6, lot_entry_y + 3, size=6.4, color=colors.HexColor("#1a73e8"))
    setback = (project.setbacks or {}).get("front_m") if isinstance(project.setbacks, dict) else None
    if setback is not None:
        sx1, sy1 = tx(0, float(setback))
        sx2, sy2 = tx(project.lot_width_m, float(setback))
        c.setDash(3, 2)
        c.setStrokeColor(colors.HexColor("#6f42c1"))
        c.line(sx1, sy1, sx2, sy2)
        c.setDash()
        _text(c, f"Lùi trước {format_dimension_m(float(setback))}", sx1 + 4, sy1 + 4, size=6.2, color=colors.HexColor("#6f42c1"))
    label_x, label_y = tx(0.2, project.lot_depth_m + 0.25)
    _text(
        c,
        f"Ranh đất {format_compact_m(project.lot_width_m)} m x {format_compact_m(project.lot_depth_m)} m | {project.display_lot_area_m2:.1f} m²",
        label_x,
        label_y,
        size=7,
        bold=True,
    )
    _draw_dimensions(c, project, tx)
    _draw_north_arrow(c, PAGE_SIZE[0] - 112, PAGE_SIZE[1] - 122, project.north_angle_degrees)
    _draw_plan_key(c, project)


def _draw_floorplan_intent_notes(c: canvas.Canvas, project: DrawingProject, floor: int) -> None:
    rooms = project.rooms_for_floor(floor)
    if not rooms:
        return
    x = MARGIN + 16
    y = CONTENT_TOP - 80
    lines = [
        f"Tầng {floor}: kích thước phòng ghi trong từng nhãn để khách kiểm tra tỷ lệ sử dụng.",
        "Mũi cửa/cửa sổ là vị trí concept; chi tiết mở quay/trượt sẽ xác nhận ở bước thiết kế tiếp theo.",
    ]
    if any(room.original_type == "stair_lightwell" for room in rooms):
        lines.append("Lõi thang/giếng trời là trục lấy sáng và thông gió chính.")
    c.setFillColor(NOTE_FILL)
    c.setStrokeColor(colors.HexColor("#d0d7de"))
    c.setLineWidth(0.4)
    c.roundRect(x - 8, y - 45, 248, 56, 4, stroke=1, fill=1)
    _draw_text_lines(c, [_fit_text(line, 236, size=6.4) for line in lines[:3]], x, y, size=6.4, leading=13, color=INK)


def _mini_transform(x0: float, y0: float, scale: float = SCALE_1_100_PT_PER_M) -> Callable[[float, float], tuple[float, float]]:
    def tx(x: float, y: float) -> tuple[float, float]:
        return x0 + x * scale, y0 + y * scale

    return tx


def _style_family(project: DrawingProject) -> str:
    metadata = project.style_metadata or {}
    style_id = str(metadata.get("style_id") or project.style).lower()
    label = _customer_style_label(project).lower()
    if "tropical" in style_id or "nhiệt đới" in label or "nhiet doi" in label:
        return "tropical"
    if "indochine" in style_id or "đông dương" in label or "dong duong" in label:
        return "indochine"
    return "minimal"


def _metadata_feature_keys(project: DrawingProject, key: str) -> set[str]:
    metadata = project.style_metadata or {}
    features: set[str] = set()
    for item in tuple(metadata.get(key) or ()):
        if isinstance(item, dict) and item.get("feature"):
            features.add(str(item["feature"]))
    return features


def _glass_suppressed(project: DrawingProject) -> bool:
    metadata = project.style_metadata or {}
    return metadata.get("facade_glass_policy") == "reduce_large_unshaded_glass" or "large_glass" in _metadata_feature_keys(project, "suppressed_style_features")


def _reference_feature_keys(project: DrawingProject) -> set[str]:
    return _metadata_feature_keys(project, "reference_style_hints")


def _draw_style_facade_features(c: canvas.Canvas, project: DrawingProject, tx: Callable[[float, float], tuple[float, float]], width_m: float, height_m: float) -> None:
    family = _style_family(project)
    reduce_glass = _glass_suppressed(project)
    reference_features = _reference_feature_keys(project)
    base_fill = {
        "tropical": colors.HexColor("#eef6ef"),
        "indochine": colors.HexColor("#f4ead8"),
        "minimal": colors.HexColor("#f2f0ea"),
    }[family]
    accent = {
        "tropical": colors.HexColor("#6aa874"),
        "indochine": colors.HexColor("#8b5e34"),
        "minimal": colors.HexColor("#b9976b"),
    }[family]
    screen = {
        "tropical": colors.HexColor("#9c6b3f"),
        "indochine": colors.HexColor("#5f3b24"),
        "minimal": colors.HexColor("#c6ad88"),
    }[family]
    _poly(c, [(0, 0), (width_m, 0), (width_m, height_m), (0, height_m)], tx, close=True, stroke=INK, width=1.35, fill=base_fill)
    if family == "minimal":
        accent_x1 = width_m * 0.58
        _poly(c, [(accent_x1, 0.1), (min(width_m - 0.1, accent_x1 + width_m * 0.28), 0.1), (min(width_m - 0.1, accent_x1 + width_m * 0.28), height_m - 0.2), (accent_x1, height_m - 0.2)], tx, close=True, stroke=colors.HexColor("#d6c0a5"), width=0.45, fill=colors.HexColor("#efe2d0"))
    if family == "indochine":
        _poly(c, [(0.05, 0.18), (width_m - 0.05, 0.18), (width_m - 0.05, 0.48), (0.05, 0.48)], tx, close=True, stroke=screen, width=0.4, fill=colors.HexColor("#e6d1b5"))
    for level in range(project.storeys):
        y1 = level * 3.3 + 0.15
        y2 = min(y1 + 3.0, height_m - 0.1)
        if family == "indochine":
            panel_x1 = width_m * (0.18 if level % 2 == 0 else 0.48)
            panel_width_factor = 0.3
        elif family == "tropical":
            panel_x1 = width_m * (0.06 if level % 2 == 0 else 0.5)
            panel_width_factor = 0.38
        else:
            panel_x1 = width_m * (0.08 if level % 2 == 0 else 0.46)
            panel_width_factor = 0.28
        panel_x2 = min(width_m - 0.08, panel_x1 + max(width_m * panel_width_factor, 0.9))
        _poly(c, [(panel_x1, y1), (panel_x2, y1), (panel_x2, y2), (panel_x1, y2)], tx, close=True, stroke=colors.HexColor("#d6d0c5"), width=0.4, fill=colors.HexColor("#fbfaf7"))
        opening_factor = {"tropical": 0.34, "indochine": 0.24, "minimal": 0.22}[family]
        if reduce_glass:
            opening_factor = min(opening_factor, 0.18)
        opening_w = min(max(width_m * opening_factor, 0.82), 2.35 if family == "tropical" and not reduce_glass else 1.75)
        ox1 = max(0.25, min(width_m - opening_w - 0.25, panel_x1 + 0.25))
        oy1 = y1 + 0.85
        _poly(c, [(ox1, oy1), (ox1 + opening_w, oy1), (ox1 + opening_w, oy1 + 1.15), (ox1, oy1 + 1.15)], tx, close=True, stroke=colors.darkcyan, width=0.9, fill=colors.HexColor("#e8f5f7"))
        if family == "indochine" and (level == 0 or "soft_arch" in reference_features):
            x1, y_arc1 = tx(ox1, oy1 + 0.15)
            x2, y_arc2 = tx(ox1 + opening_w, oy1 + 1.25)
            c.setStrokeColor(screen)
            c.setLineWidth(0.7)
            c.arc(x1, y_arc1, x2, y_arc2 + 8, 0, 180)
        if level > 0:
            balcony_x1 = max(0.15, ox1 - 0.2)
            balcony_x2 = min(width_m - 0.15, ox1 + opening_w + 0.2)
            _poly(c, [(balcony_x1, y1 + 0.55), (balcony_x2, y1 + 0.55)], tx, stroke=accent, width=1.3)
            _poly(c, [(balcony_x1, y1 + 0.32), (balcony_x2, y1 + 0.32), (balcony_x2, y1 + 0.55), (balcony_x1, y1 + 0.55)], tx, close=True, stroke=accent, width=0.5, fill=colors.HexColor("#edf7ed") if family == "tropical" else colors.HexColor("#f4efe6"))
        if family in {"tropical", "indochine"} or reduce_glass:
            fin_count = 4 if family == "tropical" else 3
            if reduce_glass:
                fin_count = max(fin_count, 4)
            fin_x = min(width_m - 0.22, ox1 + opening_w + 0.18)
            for index in range(fin_count):
                fx = fin_x + index * 0.12
                if fx < width_m - 0.12:
                    _poly(c, [(fx, oy1 - 0.08), (fx, oy1 + 1.3)], tx, stroke=screen, width=0.7)
        elif family == "minimal" and level % 2 == 0:
            _poly(c, [(0.15, y1 + 0.2), (width_m - 0.15, y1 + 0.2)], tx, stroke=screen, width=1.0)
        if family == "tropical":
            overhang_y = min(y2 - 0.25, oy1 + 1.35)
            _poly(c, [(max(0.1, ox1 - 0.25), overhang_y), (min(width_m - 0.1, ox1 + opening_w + 0.45), overhang_y)], tx, stroke=screen, width=1.15)
        if family == "minimal" and level == 0:
            _poly(c, [(0.18, y1 + 0.42), (min(width_m - 0.18, ox1 + opening_w + 0.28), y1 + 0.42)], tx, stroke=accent, width=1.0)
    if family == "tropical":
        for gx in (width_m * 0.18, width_m * 0.58):
            for gy in (height_m - 1.1, max(1.2, height_m - 4.4)):
                _poly(c, [(gx, gy), (gx + 0.35, gy + 0.5), (gx + 0.7, gy)], tx, stroke=accent, width=0.7, fill=colors.HexColor("#dff0df"))
        if "green_layer" in reference_features:
            for level in range(1, project.storeys):
                gy = level * 3.3 + 0.52
                _poly(c, [(width_m * 0.12, gy), (width_m * 0.28, gy + 0.28), (width_m * 0.44, gy)], tx, stroke=accent, width=0.65, fill=colors.HexColor("#dff0df"))
    if family == "indochine":
        arch_w = min(1.2, width_m * 0.28)
        ax1 = width_m * 0.12
        ay1 = 0.95
        x1, y1 = tx(ax1, ay1)
        x2, y2 = tx(ax1 + arch_w, ay1 + 1.3)
        c.setStrokeColor(screen)
        c.setLineWidth(0.9)
        c.arc(x1, y1, x2, y2 + 10, 0, 180)
        if "cream_pattern_palette" in reference_features:
            for index in range(max(2, int(width_m / 1.2))):
                tile_x = 0.2 + index * 0.5
                if tile_x + 0.24 < width_m:
                    _poly(c, [(tile_x, 0.22), (tile_x + 0.18, 0.38)], tx, stroke=screen, width=0.28)


def _draw_elevations(c: canvas.Canvas, project: DrawingProject) -> None:
    height = project.storeys * 3.3 + 0.8
    gap = 40.0
    available_frame_width = (PAGE_SIZE[0] - 2 * MARGIN - gap) / 2
    available_frame_height = (CONTENT_TOP - CONTENT_BOTTOM - gap - 28) / 2
    left_x = MARGIN + 18
    right_x = left_x + available_frame_width + gap
    lower_y = CONTENT_BOTTOM + 18
    upper_y = lower_y + available_frame_height + gap
    specs = (
        ("Bắc", left_x, upper_y, project.lot_width_m),
        ("Nam", right_x, upper_y, project.lot_width_m),
        ("Đông", left_x, lower_y, project.lot_depth_m),
        ("Tây", right_x, lower_y, project.lot_depth_m),
    )
    for label, x0, y0, width_m in specs:
        scale = min(SCALE_1_100_PT_PER_M, available_frame_width / max(width_m, 1.0), available_frame_height / max(height, 1.0))
        tx = _mini_transform(x0, y0, scale=scale)
        c.setFillColor(colors.white)
        c.setStrokeColor(colors.HexColor("#d0d7de"))
        c.setLineWidth(0.5)
        c.rect(x0 - 10, y0 - 10, available_frame_width, available_frame_height, stroke=1, fill=0)
        _draw_style_facade_features(c, project, tx, width_m, height)
        for level in range(1, project.storeys + 1):
            _poly(c, [(0, level * 3.3), (width_m, level * 3.3)], tx, stroke=GRID_STROKE, width=0.6)
            lx, ly = tx(width_m, level * 3.3)
            _text(c, f"L{level}", lx + 5, ly - 3, size=6, color=MUTED_INK)
        _text(c, f"Mặt đứng {label}", x0, y0 + height * scale + 10, size=8, bold=True)
    note_lines = _facade_note_lines(project)
    _text(c, f"Style concept: {_fit_text(_customer_style_label(project), 320, size=8)}", MARGIN + 22, CONTENT_BOTTOM - 8, size=8, color=MUTED_INK)
    cursor = CONTENT_BOTTOM - 20
    for line in note_lines[:3]:
        _text(c, _fit_text(line, 720, size=6.7), MARGIN + 22, cursor, size=6.7, color=MUTED_INK)
        cursor -= 10


def _facade_note_lines(project: DrawingProject) -> tuple[str, ...]:
    metadata = project.style_metadata or {}
    expression = metadata.get("facade_expression") if isinstance(metadata.get("facade_expression"), dict) else {}
    note = metadata.get("facade_strategy") or metadata.get("facade_intent") or "Mặt tiền concept thể hiện theo style và hình khối sơ bộ."
    lines = [
        f"Mặt tiền: {note}",
    ]
    rhythm = expression.get("rhythm")
    openings = expression.get("opening_language")
    shading = expression.get("shading_language")
    if rhythm:
        lines.append(f"Nhịp mặt đứng: {rhythm}")
    if openings:
        lines.append(f"Ngôn ngữ cửa mở: {openings}")
    if shading:
        lines.append(f"Che nắng/lọc nhìn: {shading}")
    suppressed = _feature_summaries(metadata.get("suppressed_style_features"), prefix="Dislike suppressed")
    references = _feature_summaries(metadata.get("reference_style_hints"), prefix="Reference descriptors")
    return tuple(dict.fromkeys((*lines, *suppressed, *references)))


def _feature_summaries(value, *, prefix: str) -> tuple[str, ...]:
    summaries: list[str] = []
    for item in value or ():
        if not isinstance(item, dict):
            continue
        feature = str(item.get("feature") or "").replace("_", " ")
        note = item.get("drawing_note") or item.get("note") or item.get("material_note")
        if feature and note:
            summaries.append(f"{prefix}: {feature} - {note}")
        elif note:
            summaries.append(f"{prefix}: {note}")
    return tuple(summaries)


def _draw_sections(c: canvas.Canvas, project: DrawingProject) -> None:
    height = project.storeys * 3.3 + 0.8
    available_frame_width = PAGE_SIZE[0] - 2 * MARGIN - 120
    available_frame_height = (CONTENT_TOP - CONTENT_BOTTOM - 64) / 2
    scale = min(SCALE_1_100_PT_PER_M, available_frame_width / max(project.lot_depth_m, project.lot_width_m, 1.0), available_frame_height / max(height, 1.0))
    specs = (
        ("Mặt cắt ngang", MARGIN + 48, CONTENT_BOTTOM + available_frame_height + 46, project.lot_width_m),
        ("Mặt cắt dọc", MARGIN + 48, CONTENT_BOTTOM + 18, project.lot_depth_m),
    )
    for label, x0, y0, width_m in specs:
        tx = _mini_transform(x0, y0, scale=scale)
        c.setStrokeColor(colors.HexColor("#d0d7de"))
        c.setLineWidth(0.5)
        c.rect(x0 - 10, y0 - 10, available_frame_width + 20, available_frame_height, stroke=1, fill=0)
        section_fill = colors.HexColor("#fffaf2")
        slab_fill = colors.HexColor("#d8dde3")
        core_fill = colors.HexColor("#eef2f6")
        room_fill = colors.HexColor("#fffdf9")
        terrace_fill = colors.HexColor("#f2f8f0")
        _poly(c, [(0, 0), (width_m, 0), (width_m, height), (0, height)], tx, close=True, stroke=INK, width=1.6, fill=section_fill)
        zone_edges = (0.0, width_m * 0.42, width_m * 0.63, width_m)
        zone_labels = ("Không gian chính", "Lõi thang/WC", "Không gian sau")
        if width_m <= 5.2:
            zone_edges = (0.0, width_m * 0.58, width_m)
            zone_labels = ("Không gian chính", "Lõi phụ")
        for level_index in range(project.storeys):
            y_base = level_index * 3.3
            y_top = y_base + 3.3
            for zone_index, (zx1, zx2) in enumerate(zip(zone_edges, zone_edges[1:])):
                fill = core_fill if "Lõi" in zone_labels[zone_index] else (terrace_fill if level_index == project.storeys - 1 and zone_index == len(zone_labels) - 1 else room_fill)
                inset = 0.08
                _poly(
                    c,
                    [(zx1 + inset, y_base + 0.16), (zx2 - inset, y_base + 0.16), (zx2 - inset, y_top - 0.18), (zx1 + inset, y_top - 0.18)],
                    tx,
                    close=True,
                    stroke=colors.HexColor("#d7dce2"),
                    width=0.35,
                    fill=fill,
                )
                label_x, label_y = tx(zx1 + inset + 0.08, y_base + 0.34)
                _text(c, _fit_text(zone_labels[zone_index], max(34, (zx2 - zx1) * scale - 10), size=5.4), label_x, label_y, size=5.4, color=MUTED_INK)
            slab_x1, slab_y1 = tx(0, y_base)
            slab_x2, slab_y2 = tx(width_m, y_base + 0.12)
            c.setFillColor(slab_fill)
            c.setStrokeColor(colors.HexColor("#9aa0a6"))
            c.setLineWidth(0.35)
            c.rect(slab_x1, slab_y1, slab_x2 - slab_x1, max(2.0, slab_y2 - slab_y1), stroke=1, fill=1)
        roof_x1, roof_y1 = tx(0, project.storeys * 3.3)
        roof_x2, roof_y2 = tx(width_m, project.storeys * 3.3 + 0.16)
        c.setFillColor(slab_fill)
        c.rect(roof_x1, roof_y1, roof_x2 - roof_x1, max(2.4, roof_y2 - roof_y1), stroke=1, fill=1)
        for level in range(1, project.storeys + 1):
            _poly(c, [(0, level * 3.3), (width_m, level * 3.3)], tx, stroke=GRID_STROKE, width=0.7)
            lx, ly = tx(width_m, level * 3.3)
            _text(c, f"Cao độ L{level}", lx + 6, ly - 3, size=6, color=MUTED_INK)
            if level <= project.storeys:
                base_x, base_y = tx(width_m + 0.55, (level - 1) * 3.3)
                top_x, top_y = tx(width_m + 0.55, level * 3.3)
                c.setStrokeColor(colors.red)
                c.setLineWidth(0.55)
                c.line(base_x, base_y, top_x, top_y)
                c.line(base_x - 3, base_y, base_x + 3, base_y)
                c.line(top_x - 3, top_y, top_x + 3, top_y)
                _text(c, "Tầng-tầng 3.30 m", top_x + 4, (base_y + top_y) / 2, size=5.8, color=colors.red)
                _text(c, "Thông thủy ~3.00 m", top_x + 4, (base_y + top_y) / 2 - 9, size=5.8, color=colors.red)
        stair_x1 = width_m * 0.43
        stair_x2 = min(width_m - 0.25, stair_x1 + max(1.2, width_m * 0.14))
        stair_points: list[tuple[float, float]] = []
        for level_index in range(project.storeys):
            y_base = level_index * 3.3 + 0.25
            stair_points.extend([(stair_x1, y_base), (stair_x2, y_base + 1.45), (stair_x1, y_base + 2.9)])
        _poly(c, stair_points, tx, stroke=INK, width=0.9)
        for hatch in range(0, max(1, int(width_m))):
            hx = hatch + 0.15
            if hx + 0.32 < width_m:
                _poly(c, [(hx, 0.04), (hx + 0.32, 0.22)], tx, stroke=colors.HexColor("#b8bec5"), width=0.25)
        _text(c, "Mặt cắt qua lõi thang/giếng trời concept", x0 + 8, y0 + 8, size=6.4, color=MUTED_INK)
        roof_x, roof_y = tx(width_m * 0.12, height - 0.35)
        _text(c, "Mái/parapet concept", roof_x, roof_y, size=6.2, color=MUTED_INK)
        _text(c, label, x0, y0 + height * scale + 10, size=8, bold=True)
        note_x = x0 + min(width_m * scale + 44, available_frame_width * 0.62)
        note_w = x0 + available_frame_width - note_x - 18
        if note_w > 120:
            note_y = y0 + available_frame_height - 36
            c.setFillColor(NOTE_FILL)
            c.setStrokeColor(colors.HexColor("#d0d7de"))
            c.setLineWidth(0.35)
            c.roundRect(note_x, note_y - 82, note_w, 84, 4, stroke=1, fill=1)
            notes = [
                "Sàn/mái: lớp concept, chưa phải cấu tạo thi công.",
                "Lõi thang/WC đặt giữa nhà để chia nhịp sử dụng.",
                "Chiều cao: kiểm tra lại theo khảo sát và pháp lý bước sau.",
            ]
            _draw_text_lines(c, [_fit_text(item, note_w - 14, size=6.2) for item in notes], note_x + 8, note_y - 15, size=6.2, leading=14, color=MUTED_INK)


def _draw_room_area_schedule(c: canvas.Canvas, project: DrawingProject) -> None:
    x = MARGIN + 22
    y = CONTENT_TOP - 16
    headers = ("Tầng", "Phòng", "Loại", "Kích thước", "Diện tích", "Ghi chú")
    widths = (52, 210, 118, 116, 78, 218)
    _draw_table_header(c, headers, widths, x, y)
    y -= 22
    for room in project.rooms:
        if y < CONTENT_BOTTOM + 28:
            break
        values = (
            f"Tầng {room.floor}",
            room.name,
            _room_type_display_label(room),
            _room_size_label(room),
            f"{room.display_area_m2:.1f} m²",
            _room_schedule_note(room),
        )
        _draw_table_row(c, values, widths, x, y)
        y -= 18
    if y >= CONTENT_BOTTOM + 28:
        total_area = sum(room.display_area_m2 for room in project.rooms)
        _draw_table_row(c, ("", "Tổng diện tích phòng concept", "", "", f"{total_area:.1f} m²", "Không thay thế đo đạc hiện trạng"), widths, x, y, bold=True)


def _draw_door_window_schedule(c: canvas.Canvas, project: DrawingProject) -> None:
    x = MARGIN + 22
    y = CONTENT_TOP - 16
    headers = ("Mã", "Tầng", "Loại", "Rộng", "Cao", "Vận hành")
    widths = (112, 58, 96, 74, 74, 260)
    _draw_table_header(c, headers, widths, x, y)
    y -= 22
    for opening in project.openings:
        if y < CONTENT_BOTTOM + 28:
            break
        values = (
            opening.label,
            f"Tầng {opening.floor}",
            "Cửa sổ" if opening.kind == "window" else "Cửa đi",
            f"{opening.width_m:.2f} m" if opening.width_m else "-",
            f"{opening.height_m:.2f} m" if opening.height_m else "-",
            _operation_display_label(opening.operation),
        )
        _draw_table_row(c, values, widths, x, y)
        y -= 18


def _draw_assumptions_style_notes(c: canvas.Canvas, project: DrawingProject) -> None:
    metadata = project.style_metadata or {}
    x = MARGIN + 22
    y = CONTENT_TOP - 16
    _text(c, "Ghi chú style", x, y, size=12, bold=True)
    y -= 20
    style_lines = [
        f"Style ID: {metadata.get('style_id') or project.style}",
        f"Phong cách khách đọc: {_customer_style_label(project)}",
        f"Mặt tiền concept: {metadata.get('facade_strategy') or metadata.get('facade_intent') or 'mặt tiền lấy từ style/profile và layout sơ bộ.'}",
    ]
    expression = metadata.get("facade_expression") if isinstance(metadata.get("facade_expression"), dict) else {}
    if expression.get("rhythm"):
        style_lines.append(f"Nhịp mặt đứng concept: {expression['rhythm']}")
    if expression.get("opening_language"):
        style_lines.append(f"Ngôn ngữ cửa mở concept: {expression['opening_language']}")
    if expression.get("shading_language"):
        style_lines.append(f"Che nắng/lọc nhìn concept: {expression['shading_language']}")
    style_lines.extend(str(note) for note in tuple(metadata.get("drawing_notes") or ())[:4])
    palette = metadata.get("material_palette") or {}
    if isinstance(palette, dict) and palette:
        accent = ", ".join(str(item) for item in palette.get("accent", ())[:3])
        base = ", ".join(str(item) for item in palette.get("base", ())[:3])
        if base:
            style_lines.append(f"Vật liệu nền concept: {base}")
        if accent:
            style_lines.append(f"Vật liệu/điểm nhấn concept: {accent}")
    facade_rules = metadata.get("facade_rules") or {}
    if isinstance(facade_rules, dict) and facade_rules:
        for key in ("massing", "screening", "greenery", "expression"):
            value = facade_rules.get(key)
            if value:
                style_lines.append(f"Luật mặt tiền - {key}: {value}")
    style_lines.extend(str(note) for note in tuple(metadata.get("material_assumptions") or ())[:3])
    style_lines.extend(_feature_summaries(metadata.get("suppressed_style_features"), prefix="Dislike suppressed"))
    style_lines.extend(_feature_summaries(metadata.get("reference_style_hints"), prefix="Reference descriptors"))
    if metadata.get("reference_descriptor_signals"):
        style_lines.append("Reference descriptors are homeowner-provided style hints only; no real image analysis or measured drawing extraction is performed.")
    provenance = metadata.get("style_provenance") if isinstance(metadata.get("style_provenance"), dict) else {}
    if provenance:
        style_lines.append("Provenance: style-derived facade/material fields are tagged as style_profile, explicit_dislike, or reference_image_descriptor assumptions.")
    style_lines.extend(str(warning) for warning in tuple(metadata.get("planning_warnings") or ()))
    for line in style_lines:
        for wrapped in _wrapped_lines(line, max_chars=108):
            _text(c, wrapped, x, y, size=8)
            y -= 13
    y -= 16
    _text(c, "Giả định concept", x, y, size=12, bold=True)
    y -= 20
    assumptions = tuple(metadata.get("assumptions") or ())
    if not assumptions:
        assumptions = ("Chưa có giả định bổ sung ngoài thông tin brief.",)
    for index, assumption in enumerate(assumptions, start=1):
        if y < CONTENT_BOTTOM + 24:
            break
        for line_index, wrapped in enumerate(_wrapped_lines(str(assumption), max_chars=104)):
            prefix = f"{index}. " if line_index == 0 else "   "
            _text(c, prefix + wrapped, x, y, size=8)
            y -= 13


def _draw_table_header(c: canvas.Canvas, headers: tuple[str, ...], widths: tuple[float, ...], x: float, y: float) -> None:
    c.setStrokeColor(INK)
    c.setLineWidth(0.8)
    cursor = x
    for header, width in zip(headers, widths):
        c.setFillColor(HEADER_FILL)
        c.rect(cursor, y - 6, width, 18, stroke=1, fill=1)
        _text(c, _fit_text(header, width - 8, size=7.5, bold=True), cursor + 4, y, size=7.5, bold=True)
        cursor += width


def _draw_table_row(c: canvas.Canvas, values: tuple[str, ...], widths: tuple[float, ...], x: float, y: float, *, bold: bool = False) -> None:
    c.setStrokeColor(GRID_STROKE)
    c.setLineWidth(0.4)
    cursor = x
    for value, width in zip(values, widths):
        c.setFillColor(colors.white)
        c.rect(cursor, y - 6, width, 18, stroke=1, fill=0)
        _text(c, _fit_text(str(value), width - 8, size=7, bold=bold), cursor + 4, y, size=7, bold=bold)
        cursor += width


def write_pdf_bundle(project: DrawingProject, sheets: tuple[SheetSpec, ...], output_path: Path) -> Path:
    register_fonts()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    sheet_numbers = "/".join(sheet.number for sheet in sheets)
    c = canvas.Canvas(str(output_path), pagesize=PAGE_SIZE, pageCompression=1)
    c.setTitle(f"{project.project_name} - {sheet_numbers}")
    c.setAuthor("AI Architect")
    c.setSubject("Concept 2D drawing set - not for construction")
    for sheet in sheets:
        c.setPageSize(PAGE_SIZE)
        _draw_title_block(c, project, sheet, scale_label=effective_scale_label(project))
        _draw_sheet_heading(c, project, sheet)
        if sheet.kind == "cover_index":
            _draw_cover_index(c, project, sheets)
        elif sheet.kind == "site":
            _draw_site(c, project)
        elif sheet.kind == "floorplan":
            _draw_floorplan(c, project, sheet)
        elif sheet.kind == "elevations":
            _draw_elevations(c, project)
        elif sheet.kind == "sections":
            _draw_sections(c, project)
        elif sheet.kind == "room_area_schedule":
            _draw_room_area_schedule(c, project)
        elif sheet.kind == "door_window_schedule":
            _draw_door_window_schedule(c, project)
        elif sheet.kind == "assumptions_style_notes":
            _draw_assumptions_style_notes(c, project)
        c.showPage()
    c.save()
    return output_path
