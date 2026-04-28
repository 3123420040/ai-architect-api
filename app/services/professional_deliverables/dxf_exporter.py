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


def _add_polyline(msp, points, *, layer: str, closed: bool = False) -> None:
    msp.add_lwpolyline(points, close=closed, dxfattribs={"layer": layer})


def _draw_title_note(msp, project: DrawingProject, sheet: SheetSpec) -> None:
    title_width = max(project.lot_width_m, 7.8)
    _add_polyline(msp, [(-1.4, -2.0), (-1.4 + title_width, -2.0), (-1.4 + title_width, -0.8), (-1.4, -0.8)], layer="A-ANNO-TTLB", closed=True)
    _add_text(msp, project.project_name, (-1.2, -1.2), height=0.18, layer="A-ANNO-TTLB")
    _add_text(msp, f"{sheet.number} - {sheet.title}", (-1.2, -1.55), height=0.16, layer="A-ANNO-TTLB")
    _add_text(msp, f"Tỷ lệ {sheet.scale} | Ngày {project.issue_date.isoformat()} | {project.concept_note}", (2.4, -1.55), height=0.14, layer="A-ANNO-TTLB")


def _draw_dimensions(msp, project: DrawingProject, *, x_offset: float = 0.0, y_offset: float = 0.0) -> None:
    width = project.lot_width_m
    depth = project.lot_depth_m
    _add_polyline(msp, [(x_offset, y_offset - 0.45), (x_offset + width, y_offset - 0.45)], layer="A-ANNO-DIMS")
    _add_text(msp, format_dimension_m(width), (x_offset + width / 2 - 0.35, y_offset - 0.75), height=0.18, layer="A-ANNO-DIMS")
    _add_polyline(msp, [(x_offset - 0.45, y_offset), (x_offset - 0.45, y_offset + depth)], layer="A-ANNO-DIMS")
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
    _add_polyline(msp, project.site_polygon, layer="A-WALL", closed=True)
    for wall in project.walls_for_floor(floor):
        _add_polyline(msp, [wall.start, wall.end], layer=wall.layer)
    for room in project.rooms_for_floor(floor):
        _add_polyline(msp, room.polygon, layer="A-AREA", closed=True)
        _add_text(msp, room.name, room.center, height=0.18, layer="A-AREA-IDEN")
        _add_text(msp, f"{room.display_area_m2:.1f} m²", (room.center[0], room.center[1] - 0.28), height=0.14, layer="A-AREA-IDEN")
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
    _draw_dimensions(msp, project)
    _draw_north_arrow(msp, (project.lot_width_m + 0.85, max(project.lot_depth_m - 1.5, 0.8)), project.north_angle_degrees)


def _draw_site(msp, project: DrawingProject) -> None:
    _add_polyline(msp, project.site_polygon, layer="L-SITE", closed=True)
    _add_polyline(msp, project.roof_outline, layer="A-ROOF", closed=True)
    _add_polyline(msp, project.site_polygon, layer="A-WALL", closed=True)
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
    _add_text(msp, "Muc luc: A-100 site, A-101 floor plans, A-201 elevation, A-301 section, A-601/A-602 schedules, A-603 assumptions/style notes", (0.0, 7.85), height=0.14, layer="A-ANNO-TEXT")
    _add_text(msp, "Pham vi: concept/schematic only, not for construction or permit use.", (0.0, 7.45), height=0.14, layer="A-ANNO-TEXT")
    _add_polyline(msp, [(0, 7.15), (10.0, 7.15), (10.0, 10.0), (0, 10.0)], layer="A-ANNO-TTLB", closed=True)


def _draw_elevations(msp, project: DrawingProject) -> None:
    height = project.storeys * 3.3 + 0.8
    specs = (
        ("Bắc", 0.0, 0.0, project.lot_width_m),
        ("Nam", 8.0, 0.0, project.lot_width_m),
        ("Đông", 0.0, 5.8, project.lot_depth_m),
        ("Tây", 8.0, 5.8, project.lot_depth_m),
    )
    for label, ox, oy, width in specs:
        _add_polyline(msp, [(ox, oy), (ox + width, oy), (ox + width, oy + height), (ox, oy + height)], layer="A-ELEV-OTLN", closed=True)
        for level in range(1, project.storeys + 1):
            _add_polyline(msp, [(ox, oy + level * 3.3), (ox + width, oy + level * 3.3)], layer="S-BEAM")
        _add_polyline(msp, [(ox - 0.15, oy - 0.25), (ox + width + 0.15, oy - 0.25)], layer="S-FNDN")
        _add_polyline(msp, [(ox + width * 0.2, oy + 1.0), (ox + width * 0.4, oy + 1.0), (ox + width * 0.4, oy + 2.3), (ox + width * 0.2, oy + 2.3)], layer="A-GLAZ", closed=True)
        _add_polyline(msp, [(ox + width * 0.62, oy + 4.2), (ox + width * 0.82, oy + 4.2), (ox + width * 0.82, oy + 5.5), (ox + width * 0.62, oy + 5.5)], layer="A-GLAZ", closed=True)
        _add_text(msp, f"Mặt đứng {label}", (ox, oy + height + 0.28), height=0.18, layer="A-ANNO-TEXT")


def _draw_sections(msp, project: DrawingProject) -> None:
    height = project.storeys * 3.3 + 0.8
    for label, ox, width in (("Mặt cắt ngang", 0.0, project.lot_width_m), ("Mặt cắt dọc", 8.0, project.lot_depth_m)):
        _add_polyline(msp, [(ox, 0), (ox + width, 0), (ox + width, height), (ox, height)], layer="A-SECT-MCUT", closed=True)
        for level in range(1, project.storeys + 1):
            _add_polyline(msp, [(ox, level * 3.3), (ox + width, level * 3.3)], layer="S-BEAM")
        _add_polyline(msp, [(ox + 0.5, 0.2), (ox + 2.2, 3.1), (ox + 0.5, 3.1), (ox + 2.2, 6.4)], layer="A-SECT-OTLN")
        _add_polyline(msp, [(ox - 0.15, -0.25), (ox + width + 0.15, -0.25)], layer="S-FNDN")
        _add_text(msp, label, (ox, height + 0.28), height=0.18, layer="A-ANNO-TEXT")


def _draw_room_area_schedule(msp, project: DrawingProject) -> None:
    _add_text(msp, "Bang phong va dien tich", (0.0, 10.0), height=0.24, layer="A-ANNO-TEXT")
    y = 9.45
    _add_text(msp, "Tang | Phong | Loai | Dien tich", (0.0, y), height=0.16, layer="A-AREA-IDEN")
    y -= 0.38
    for room in project.rooms:
        _add_text(
            msp,
            f"Tang {room.floor} | {room.name} | {room.original_type or room.category or '-'} | {room.display_area_m2:.1f} m2",
            (0.0, y),
            height=0.14,
            layer="A-AREA-IDEN",
        )
        y -= 0.32
    _add_polyline(msp, [(-0.2, y + 0.12), (11.0, y + 0.12), (11.0, 9.75), (-0.2, 9.75)], layer="A-AREA", closed=True)


def _draw_door_window_schedule(msp, project: DrawingProject) -> None:
    _add_text(msp, "Bang cua di va cua so", (0.0, 10.0), height=0.24, layer="A-ANNO-TEXT")
    y = 9.45
    _add_text(msp, "Ma | Tang | Loai | Rong | Cao | Van hanh", (0.0, y), height=0.16, layer="A-DOOR-IDEN")
    y -= 0.38
    for opening in project.openings:
        _add_text(
            msp,
            f"{opening.label} | Tang {opening.floor} | {opening.kind} | {opening.width_m or 0:.2f} m | {opening.height_m or 0:.2f} m | {opening.operation or 'concept'}",
            (0.0, y),
            height=0.14,
            layer="A-DOOR-IDEN" if opening.kind == "door" else "A-ANNO-TEXT",
        )
        y -= 0.32
    _add_polyline(msp, [(-0.2, y + 0.12), (11.0, y + 0.12), (11.0, 9.75), (-0.2, 9.75)], layer="A-DOOR", closed=True)


def _draw_assumptions_style_notes(msp, project: DrawingProject) -> None:
    metadata = project.style_metadata or {}
    _add_text(msp, "Gia dinh va ghi chu style", (0.0, 10.0), height=0.24, layer="A-ANNO-TEXT")
    _add_text(msp, f"Style ID: {metadata.get('style_id') or project.style}", (0.0, 9.45), height=0.16, layer="A-ANNO-TEXT")
    _add_text(msp, str(metadata.get("facade_strategy") or "Facade strategy follows concept style/profile."), (0.0, 9.08), height=0.14, layer="A-ANNO-TEXT")
    y = 8.55
    _add_text(msp, "Gia dinh concept:", (0.0, y), height=0.16, layer="A-ANNO-TEXT")
    y -= 0.38
    assumptions = tuple(metadata.get("assumptions") or ())
    if not assumptions:
        assumptions = ("No additional assumptions beyond the brief.",)
    for index, assumption in enumerate(assumptions, start=1):
        _add_text(msp, f"{index}. {assumption}", (0.0, y), height=0.14, layer="A-ANNO-TEXT")
        y -= 0.34
    _add_polyline(msp, [(-0.2, y + 0.12), (11.0, y + 0.12), (11.0, 10.25), (-0.2, 10.25)], layer="A-ANNO-TTLB", closed=True)


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
