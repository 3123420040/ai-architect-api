from __future__ import annotations

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


def _draw_title_block(c: canvas.Canvas, project: DrawingProject, sheet: SheetSpec, *, scale_label: str | None = None) -> None:
    width, _ = PAGE_SIZE
    y = MARGIN
    c.setStrokeColor(colors.black)
    c.setLineWidth(1.2)
    c.rect(MARGIN, y, width - 2 * MARGIN, TITLE_BLOCK_HEIGHT, stroke=1, fill=0)
    c.line(width * 0.58, y, width * 0.58, y + TITLE_BLOCK_HEIGHT)
    c.line(width * 0.73, y, width * 0.73, y + TITLE_BLOCK_HEIGHT)
    c.line(width * 0.86, y, width * 0.86, y + TITLE_BLOCK_HEIGHT)
    _set_font(c, 10, bold=True)
    c.drawString(MARGIN + 12, y + 58, "AI Architect")
    _set_font(c, 8)
    c.drawString(MARGIN + 12, y + 38, "Hồ sơ trình bày phương án")
    c.drawString(MARGIN + 12, y + 20, "Ô dấu KTS")
    _set_font(c, 12, bold=True)
    c.drawString(MARGIN + 168, y + 58, project.project_name)
    _set_font(c, 9)
    c.drawString(MARGIN + 168, y + 38, sheet.title)
    c.drawString(MARGIN + 168, y + 20, project.concept_note)
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
    c.drawString(x, y + 18, "Dấu KTS")


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


def _poly(c: canvas.Canvas, points: tuple[tuple[float, float], ...] | list[tuple[float, float]], tx: Callable[[float, float], tuple[float, float]], *, close: bool = False, stroke=colors.black, width: float = 1.0) -> None:
    c.setStrokeColor(stroke)
    c.setLineWidth(width)
    path = c.beginPath()
    x0, y0 = tx(*points[0])
    path.moveTo(x0, y0)
    for point in points[1:]:
        x, y = tx(*point)
        path.lineTo(x, y)
    if close:
        path.close()
    c.drawPath(path, stroke=1, fill=0)


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


def _draw_text_lines(c: canvas.Canvas, lines: list[str] | tuple[str, ...], x: float, y: float, *, size: float = 8, leading: float = 13, bold: bool = False) -> float:
    cursor = y
    for line in lines:
        _text(c, line, x, cursor, size=size, bold=bold)
        cursor -= leading
    return cursor


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
            f"Phong cách định hướng: {project.style}",
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


def _draw_dimensions(c: canvas.Canvas, project: DrawingProject, tx: Callable[[float, float], tuple[float, float]]) -> None:
    c.setStrokeColor(colors.red)
    c.setLineWidth(0.7)
    x1, y1 = tx(0, -0.55)
    x2, y2 = tx(project.lot_width_m, -0.55)
    c.line(x1, y1, x2, y2)
    _text(c, format_dimension_m(project.lot_width_m), (x1 + x2) / 2 - 18, y1 - 12, size=7, color=colors.red)
    x3, y3 = tx(-0.55, 0)
    x4, y4 = tx(-0.55, project.lot_depth_m)
    c.line(x3, y3, x4, y4)
    _text(c, format_dimension_m(project.lot_depth_m), x3 - 34, (y3 + y4) / 2, size=7, color=colors.red)
    sx, sy = tx(project.lot_width_m + 0.7, 0)
    _, _, scale = plan_layout(project)
    c.line(sx, sy, sx + scale, sy)
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
    c.setLineWidth(1.2)
    x1, y1 = tx(*opening.start)
    x2, y2 = tx(*opening.end)
    c.line(x1, y1, x2, y2)
    if opening.kind == "door":
        radius = ((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5
        c.arc(x1 - radius, y1, x1 + radius, y1 + radius * 2, 0, 90)
    _text(c, opening.label, (x1 + x2) / 2, (y1 + y2) / 2 + 5, size=6, color=colors.darkred)


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


def _draw_floorplan(c: canvas.Canvas, project: DrawingProject, sheet: SheetSpec) -> None:
    assert sheet.floor is not None
    _, _, scale = plan_layout(project)
    tx = _transform(project)
    _poly(c, project.site_polygon, tx, close=True, width=1.4)
    for wall in project.walls_for_floor(sheet.floor):
        _poly(c, [wall.start, wall.end], tx, width=1.2)
    c.setStrokeColor(colors.magenta)
    c.setLineWidth(0.45)
    for room in project.rooms_for_floor(sheet.floor):
        _poly(c, room.polygon, tx, close=True, stroke=colors.magenta, width=0.45)
        x, y = tx(*room.center)
        _text(c, room.name, x - 22, y + 4, size=7, bold=True, color=colors.darkmagenta)
        _text(c, f"{room.display_area_m2:.1f} m²", x - 16, y - 7, size=6.2, color=colors.darkmagenta)
    for opening in project.openings_for_floor(sheet.floor):
        _draw_opening(c, opening, tx)
    for fixture in project.fixtures_for_floor(sheet.floor):
        _draw_fixture(c, fixture, tx, scale=scale)
    _draw_dimensions(c, project, tx)
    _draw_north_arrow(c, PAGE_SIZE[0] - 112, PAGE_SIZE[1] - 122, project.north_angle_degrees)


def _draw_site(c: canvas.Canvas, project: DrawingProject) -> None:
    tx = _transform(project)
    _poly(c, project.site_polygon, tx, close=True, stroke=colors.brown, width=1.2)
    _poly(c, project.roof_outline, tx, close=True, stroke=colors.black, width=1.2)
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


def _mini_transform(x0: float, y0: float, scale: float = SCALE_1_100_PT_PER_M) -> Callable[[float, float], tuple[float, float]]:
    def tx(x: float, y: float) -> tuple[float, float]:
        return x0 + x * scale, y0 + y * scale

    return tx


def _draw_elevations(c: canvas.Canvas, project: DrawingProject) -> None:
    height = project.storeys * 3.3 + 0.8
    available_frame_width = (PAGE_SIZE[0] - 2 * MARGIN - 82) / 2
    available_frame_height = (CONTENT_TOP - CONTENT_BOTTOM - 78) / 2
    max_width_m = max(project.lot_width_m, project.lot_depth_m, 1.0)
    scale = min(SCALE_1_100_PT_PER_M, available_frame_width / max_width_m, available_frame_height / max(height, 1.0))
    specs = (
        ("Bắc", MARGIN + 48, CONTENT_BOTTOM + 270, project.lot_width_m),
        ("Nam", MARGIN + 380, CONTENT_BOTTOM + 270, project.lot_width_m),
        ("Đông", MARGIN + 48, CONTENT_BOTTOM + 20, project.lot_depth_m),
        ("Tây", MARGIN + 380, CONTENT_BOTTOM + 20, project.lot_depth_m),
    )
    for label, x0, y0, width_m in specs:
        tx = _mini_transform(x0, y0, scale=scale)
        _poly(c, [(0, 0), (width_m, 0), (width_m, height), (0, height)], tx, close=True, width=1.1)
        for level in range(1, project.storeys + 1):
            _poly(c, [(0, level * 3.3), (width_m, level * 3.3)], tx, stroke=colors.gray, width=0.6)
        _poly(c, [(width_m * 0.2, 1.0), (width_m * 0.42, 1.0), (width_m * 0.42, 2.3), (width_m * 0.2, 2.3)], tx, close=True, stroke=colors.darkcyan, width=0.8)
        _poly(c, [(width_m * 0.62, 4.2), (width_m * 0.84, 4.2), (width_m * 0.84, 5.5), (width_m * 0.62, 5.5)], tx, close=True, stroke=colors.darkcyan, width=0.8)
        _text(c, f"Mặt đứng {label}", x0, y0 + height * scale + 10, size=8, bold=True)


def _draw_sections(c: canvas.Canvas, project: DrawingProject) -> None:
    height = project.storeys * 3.3 + 0.8
    available_frame_width = PAGE_SIZE[0] - 2 * MARGIN - 120
    available_frame_height = (CONTENT_TOP - CONTENT_BOTTOM - 84) / 2
    scale = min(SCALE_1_100_PT_PER_M, available_frame_width / max(project.lot_depth_m, project.lot_width_m, 1.0), available_frame_height / max(height, 1.0))
    specs = (
        ("Mặt cắt ngang", MARGIN + 48, CONTENT_BOTTOM + 260, project.lot_width_m),
        ("Mặt cắt dọc", MARGIN + 48, CONTENT_BOTTOM + 20, project.lot_depth_m),
    )
    for label, x0, y0, width_m in specs:
        tx = _mini_transform(x0, y0, scale=scale)
        _poly(c, [(0, 0), (width_m, 0), (width_m, height), (0, height)], tx, close=True, width=1.6)
        for level in range(1, project.storeys + 1):
            _poly(c, [(0, level * 3.3), (width_m, level * 3.3)], tx, stroke=colors.gray, width=0.7)
        _poly(c, [(0.5, 0.2), (2.2, 3.1), (0.5, 3.1), (2.2, 6.4)], tx, stroke=colors.black, width=0.8)
        _text(c, label, x0, y0 + height * scale + 10, size=8, bold=True)


def _draw_room_area_schedule(c: canvas.Canvas, project: DrawingProject) -> None:
    x = MARGIN + 22
    y = CONTENT_TOP - 16
    headers = ("Tầng", "Phòng", "Loại", "Diện tích")
    widths = (52, 210, 140, 78)
    _draw_table_header(c, headers, widths, x, y)
    y -= 22
    for room in project.rooms:
        if y < CONTENT_BOTTOM + 28:
            break
        values = (f"Tầng {room.floor}", room.name, room.original_type or room.category or "-", f"{room.display_area_m2:.1f} m²")
        _draw_table_row(c, values, widths, x, y)
        y -= 18


def _draw_door_window_schedule(c: canvas.Canvas, project: DrawingProject) -> None:
    x = MARGIN + 22
    y = CONTENT_TOP - 16
    headers = ("Mã", "Tầng", "Loại", "Rộng", "Cao", "Vận hành")
    widths = (92, 52, 86, 64, 64, 150)
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
            opening.operation or "concept",
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
        str(metadata.get("facade_strategy") or "Mặt tiền concept lấy từ style/profile và layout sơ bộ."),
    ]
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
    c.setStrokeColor(colors.black)
    c.setLineWidth(0.8)
    cursor = x
    for header, width in zip(headers, widths):
        c.rect(cursor, y - 6, width, 18, stroke=1, fill=0)
        _text(c, header, cursor + 4, y, size=7.5, bold=True)
        cursor += width


def _draw_table_row(c: canvas.Canvas, values: tuple[str, ...], widths: tuple[float, ...], x: float, y: float) -> None:
    c.setStrokeColor(colors.gray)
    c.setLineWidth(0.4)
    cursor = x
    for value, width in zip(values, widths):
        c.rect(cursor, y - 6, width, 18, stroke=1, fill=0)
        _text(c, str(value)[:42], cursor + 4, y, size=7)
        cursor += width


def write_pdf_bundle(project: DrawingProject, sheets: tuple[SheetSpec, ...], output_path: Path) -> Path:
    register_fonts()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    sheet_numbers = "/".join(sheet.number for sheet in sheets)
    c = canvas.Canvas(str(output_path), pagesize=PAGE_SIZE, pageCompression=1)
    c.setTitle(f"{project.project_name} - {sheet_numbers}")
    c.setAuthor("AI Architect")
    c.setSubject("Sprint 1 professional 2D drawing set")
    for sheet in sheets:
        c.setPageSize(PAGE_SIZE)
        _draw_title_block(c, project, sheet, scale_label=effective_scale_label(project))
        _set_font(c, 16, bold=True)
        c.drawString(MARGIN, PAGE_SIZE[1] - MARGIN - 4, f"{sheet.number} - {sheet.title}")
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
