from __future__ import annotations

import csv
import io
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from reportlab.lib.pagesizes import A3, landscape
from reportlab.pdfgen import canvas

try:  # pragma: no cover - optional dependency
    import ezdxf
except ImportError:  # pragma: no cover - optional dependency
    ezdxf = None

try:  # pragma: no cover - optional dependency
    from svglib.svglib import svg2rlg
    from reportlab.graphics import renderPDF
except ImportError:  # pragma: no cover - optional dependency
    svg2rlg = None
    renderPDF = None

from app.services.geometry import ensure_geometry_v2, geometry_level_index, geometry_room_index
from app.services.storage import absolute_path, save_binary, save_json, save_text

PAGE_SIZE = landscape(A3)
SHEET_WIDTH = 1200
SHEET_HEIGHT = 850
TITLE_BLOCK_HEIGHT = 78
DRAWING_MARGIN = 52
DRAWING_TOP = 78
DRAWING_BOTTOM = TITLE_BLOCK_HEIGHT + 24
DRAWING_LEFT = DRAWING_MARGIN
DRAWING_RIGHT = DRAWING_MARGIN

DXF_LAYER_MAP = {
    "A-WALL-EXTR": {"color": 7, "lineweight": 50},
    "A-WALL-INTR": {"color": 7, "lineweight": 30},
    "A-WALL-PRTY": {"color": 8, "lineweight": 50},
    "A-DOOR": {"color": 3, "lineweight": 25},
    "A-GLAZ": {"color": 5, "lineweight": 25},
    "A-STRS": {"color": 6, "lineweight": 25},
    "A-FIXT": {"color": 8, "lineweight": 18},
    "A-ANNO-DIMS": {"color": 2, "lineweight": 13},
    "A-ANNO-TEXT": {"color": 7, "lineweight": 13},
    "A-ANNO-ROOM": {"color": 4, "lineweight": 13},
    "A-ANNO-GRID": {"color": 8, "lineweight": 9},
    "A-SITE-BNDY": {"color": 1, "lineweight": 35},
    "A-SITE-BLDG": {"color": 7, "lineweight": 50},
    "A-ELEV-OUTL": {"color": 7, "lineweight": 50},
    "A-ELEV-OPEN": {"color": 5, "lineweight": 25},
    "A-SECT-CUT": {"color": 7, "lineweight": 70},
    "A-SECT-BEYND": {"color": 253, "lineweight": 18},
    "A-ANNO-TTLB": {"color": 7, "lineweight": 35},
}

STUDIO_NAME = "KTC KTS"
EXPORT_PIPELINE_VERSION = "3.0.0-candidate"
ALLOWED_PRESETS = {"technical_neutral", "client_presentation"}
PRESET_STYLES = {
    "technical_neutral": {
        "page_fill": "#f7f3ec",
        "sheet_fill": "#fffdf8",
        "title_fill": "#efe5d7",
        "line": "#1f1e1a",
        "muted": "#6a6f63",
        "accent": "#1f1e1a",
    },
    "client_presentation": {
        "page_fill": "#f7f3ec",
        "sheet_fill": "#fffdfa",
        "title_fill": "#efe1d4",
        "line": "#1f1e1a",
        "muted": "#6a6f63",
        "accent": "#a65a3a",
    },
}
COVER_DISCLAIMER = (
    "DESIGN DEVELOPMENT PACKAGE FOR CLIENT ALIGNMENT, DESIGN COORDINATION, "
    "AND CAD/BIM HANDOFF. NOT FOR PERMIT SUBMISSION, CONSTRUCTION, "
    "FABRICATION, OR SITE EXECUTION WITHOUT PROFESSIONAL VERIFICATION."
)
SHORT_DISCLAIMER = "NOT FOR PERMIT, CONSTRUCTION, OR SITE EXECUTION."
DEGRADED_DISCLAIMER = "DEGRADED PREVIEW. QUALITY GATES NOT PASSED. PREVIEW ONLY. ISSUE BLOCKED."


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _preset_style(deliverable_preset: str, package_status: str) -> dict[str, str]:
    style = dict(PRESET_STYLES.get(deliverable_preset, PRESET_STYLES["technical_neutral"]))
    if package_status == "degraded_preview":
        style["accent"] = "#b4412f"
    return style


def _status_label(package_status: str) -> str:
    return package_status.replace("_", " ").upper()


def _issue_date(issue_date: str | None = None) -> str:
    if issue_date:
        return issue_date
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _svg_root(elements: list[str]) -> str:
    body = "\n".join(elements)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{SHEET_WIDTH}" height="{SHEET_HEIGHT}" '
        f'viewBox="0 0 {SHEET_WIDTH} {SHEET_HEIGHT}">{body}</svg>'
    )


def _svg_text(x: float, y: float, value: str, size: int = 16, weight: str = "400", anchor: str = "start", fill: str = "#1b1a18") -> str:
    text = (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
    return (
        f'<text x="{x:.2f}" y="{y:.2f}" fill="{fill}" font-size="{size}" '
        f'font-family="Arial, Helvetica, sans-serif" font-weight="{weight}" text-anchor="{anchor}">{text}</text>'
    )


def _sheet_frame(
    project_name: str,
    sheet_number: str,
    sheet_title: str,
    scale: str | None,
    revision_label: str,
    *,
    deliverable_preset: str = "technical_neutral",
    package_status: str = "review",
    issue_date: str | None = None,
) -> list[str]:
    style = _preset_style(deliverable_preset, package_status)
    resolved_issue_date = _issue_date(issue_date)
    elements = [
        f'<rect width="1200" height="850" fill="{style["page_fill"]}"/>',
        f'<rect x="22" y="22" width="1156" height="806" fill="{style["sheet_fill"]}" stroke="{style["line"]}" stroke-width="3"/>',
        f'<rect x="22" y="{SHEET_HEIGHT - TITLE_BLOCK_HEIGHT - 22}" width="1156" height="{TITLE_BLOCK_HEIGHT}" fill="{style["title_fill"]}" stroke="{style["line"]}" stroke-width="2"/>',
        f'<line x1="720" y1="{SHEET_HEIGHT - TITLE_BLOCK_HEIGHT - 22}" x2="720" y2="{SHEET_HEIGHT - 22}" stroke="{style["line"]}" stroke-width="2"/>',
        f'<line x1="920" y1="{SHEET_HEIGHT - TITLE_BLOCK_HEIGHT - 22}" x2="920" y2="{SHEET_HEIGHT - 22}" stroke="{style["line"]}" stroke-width="2"/>',
        f'<line x1="1060" y1="{SHEET_HEIGHT - TITLE_BLOCK_HEIGHT - 22}" x2="1060" y2="{SHEET_HEIGHT - 22}" stroke="{style["line"]}" stroke-width="2"/>',
        _svg_text(46, SHEET_HEIGHT - 64, STUDIO_NAME, size=22, weight="700", fill=style["accent"]),
        _svg_text(46, SHEET_HEIGHT - 42, "DESIGN DEVELOPMENT PACKAGE", size=12, weight="700", fill=style["muted"]),
        _svg_text(250, SHEET_HEIGHT - 64, project_name, size=20, weight="700", fill=style["line"]),
        _svg_text(250, SHEET_HEIGHT - 38, sheet_title, size=15, fill=style["line"]),
        _svg_text(738, SHEET_HEIGHT - 56, f"NO {sheet_number}", size=16, weight="700", fill=style["line"]),
        _svg_text(738, SHEET_HEIGHT - 32, f"DATE {resolved_issue_date}", size=11, fill=style["muted"]),
        _svg_text(938, SHEET_HEIGHT - 56, f"SCALE {scale or 'NTS'}", size=13, weight="700", fill=style["line"]),
        _svg_text(938, SHEET_HEIGHT - 32, f"PRESET {deliverable_preset.replace('_', ' ').title()}", size=10, fill=style["muted"]),
        _svg_text(1074, SHEET_HEIGHT - 56, f"REV {revision_label}", size=14, weight="700", fill=style["line"]),
        _svg_text(1074, SHEET_HEIGHT - 32, _status_label(package_status), size=10, weight="700", fill=style["accent"]),
    ]
    return elements


def _bounds_from_points(points: list[tuple[float, float]]) -> tuple[float, float, float, float]:
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return min(xs), min(ys), max(xs), max(ys)


def _plan_transform(geometry: dict[str, Any]) -> tuple[callable, float]:
    boundary = geometry.get("site", {}).get("boundary") or [[0, 0], [5, 0], [5, 20], [0, 20]]
    points = [(float(x), float(y)) for x, y in boundary]
    min_x, min_y, max_x, max_y = _bounds_from_points(points)
    width = max(max_x - min_x, 1.0)
    height = max(max_y - min_y, 1.0)
    viewport_width = SHEET_WIDTH - DRAWING_LEFT - DRAWING_RIGHT
    viewport_height = SHEET_HEIGHT - DRAWING_TOP - DRAWING_BOTTOM
    scale = min(viewport_width / width, viewport_height / height)
    offset_x = DRAWING_LEFT + ((viewport_width - width * scale) / 2) - (min_x * scale)
    offset_y = DRAWING_TOP + ((viewport_height - height * scale) / 2) - (min_y * scale)

    def transform(x: float, y: float) -> tuple[float, float]:
        px = offset_x + (x * scale)
        py = offset_y + ((max_y - y + min_y) * scale)
        return round(px, 2), round(py, 2)

    return transform, scale


def _elevation_transform(geometry: dict[str, Any]) -> tuple[callable, float]:
    site = geometry.get("site", {})
    width = float(site.get("boundary", [[0, 0], [5, 0]])[1][0])
    levels = geometry.get("levels", [])
    max_height = max(float(level.get("elevation_m", 0)) for level in levels) + 4
    viewport_width = SHEET_WIDTH - DRAWING_LEFT - DRAWING_RIGHT
    viewport_height = SHEET_HEIGHT - DRAWING_TOP - DRAWING_BOTTOM
    scale = min(viewport_width / max(width, 1.0), viewport_height / max(max_height, 1.0))
    base_x = DRAWING_LEFT + (viewport_width - width * scale) / 2
    base_y = DRAWING_TOP + viewport_height - 24

    def transform(x: float, z: float) -> tuple[float, float]:
        return round(base_x + x * scale, 2), round(base_y - z * scale, 2)

    return transform, scale


def _rooms_at_level(geometry: dict[str, Any], level_id: str) -> list[dict[str, Any]]:
    return [room for room in geometry.get("rooms", []) if room.get("level") == level_id]


def _walls_at_level(geometry: dict[str, Any], level_id: str) -> list[dict[str, Any]]:
    return [wall for wall in geometry.get("walls", []) if wall.get("level") == level_id]


def _openings_at_level(geometry: dict[str, Any], level_id: str) -> list[dict[str, Any]]:
    return [opening for opening in geometry.get("openings", []) if opening.get("level") == level_id]


def _grid_y_absolute(geometry: dict[str, Any], position: float) -> float:
    return float(geometry.get("site", {}).get("setbacks", {}).get("front_m", 0.0)) + float(position)


def _room_center(polygon: list[list[float]]) -> tuple[float, float]:
    xs = [point[0] for point in polygon]
    ys = [point[1] for point in polygon]
    return sum(xs) / len(xs), sum(ys) / len(ys)


def _build_plan_svg(
    project_name: str,
    version_number: int,
    geometry: dict[str, Any],
    level: dict[str, Any],
    revision_label: str,
    *,
    sheet_title: str | None = None,
    deliverable_preset: str = "technical_neutral",
    package_status: str = "review",
    issue_date: str | None = None,
) -> str:
    transform, scale = _plan_transform(geometry)
    elements = _sheet_frame(
        project_name,
        f"A{version_number}",
        sheet_title or f"Floor Plan - {level['name']}",
        "1:100",
        revision_label,
        deliverable_preset=deliverable_preset,
        package_status=package_status,
        issue_date=issue_date,
    )
    elements.extend(
        [
            f'<rect x="{DRAWING_LEFT}" y="{DRAWING_TOP}" width="{SHEET_WIDTH - DRAWING_LEFT - DRAWING_RIGHT}" height="{SHEET_HEIGHT - DRAWING_TOP - DRAWING_BOTTOM}" fill="#fffdf8" stroke="#8a8172" stroke-width="1"/>',
            _svg_text(DRAWING_LEFT + 4, DRAWING_TOP - 12, f"{level['name']} / canonical geometry view", size=14, weight="700"),
        ]
    )

    site_boundary = geometry.get("site", {}).get("boundary") or []
    if site_boundary:
        points = " ".join(
            f"{transform(float(point[0]), float(point[1]))[0]},{transform(float(point[0]), float(point[1]))[1]}"
            for point in site_boundary
        )
        elements.append(f'<polygon points="{points}" fill="none" stroke="#9e9482" stroke-width="2" stroke-dasharray="8 6"/>')

    grids = geometry.get("grids", {})
    site = geometry.get("site", {})
    depth = float(site.get("boundary", [[0, 0], [0, 20], [0, 20], [0, 20]])[2][1]) if site.get("boundary") else 20.0
    width = float(site.get("boundary", [[0, 0], [5, 0]])[1][0]) if site.get("boundary") else 5.0
    for axis in grids.get("axes_x", []):
        x = float(axis["position"])
        start = transform(x, 0)
        end = transform(x, depth)
        elements.append(f'<line x1="{start[0]}" y1="{start[1]}" x2="{end[0]}" y2="{end[1]}" stroke="#c4baa9" stroke-width="1.4" stroke-dasharray="4 4"/>')
        elements.append(f'<circle cx="{start[0]}" cy="{start[1] - 14}" r="10" fill="#fffdf8" stroke="#1b1a18" stroke-width="1.5"/>')
        elements.append(_svg_text(start[0], start[1] - 10, str(axis["id"]), size=12, weight="700", anchor="middle"))
    for axis in grids.get("axes_y", []):
        y = _grid_y_absolute(geometry, float(axis["position"]))
        start = transform(0, y)
        end = transform(width, y)
        elements.append(f'<line x1="{start[0]}" y1="{start[1]}" x2="{end[0]}" y2="{end[1]}" stroke="#c4baa9" stroke-width="1.4" stroke-dasharray="4 4"/>')
        elements.append(f'<circle cx="{start[0] - 14}" cy="{start[1]}" r="10" fill="#fffdf8" stroke="#1b1a18" stroke-width="1.5"/>')
        elements.append(_svg_text(start[0] - 14, start[1] + 4, str(axis["id"]), size=12, weight="700", anchor="middle"))

    for wall in _walls_at_level(geometry, str(level["id"])):
        start = wall["start"]
        end = wall["end"]
        start_px = transform(float(start[0]), float(start[1]))
        end_px = transform(float(end[0]), float(end[1]))
        thickness = max(float(wall.get("assembly", {}).get("total_thickness_m", 0.1)), 0.08) * scale
        if abs(float(start[0]) - float(end[0])) < 0.01:
            x = min(start_px[0], end_px[0]) - thickness / 2
            y = min(start_px[1], end_px[1])
            height = abs(start_px[1] - end_px[1])
            elements.append(f'<rect x="{x:.2f}" y="{y:.2f}" width="{thickness:.2f}" height="{height:.2f}" fill="#2a2722"/>')
        else:
            x = min(start_px[0], end_px[0])
            y = min(start_px[1], end_px[1]) - thickness / 2
            width_px = abs(start_px[0] - end_px[0])
            elements.append(f'<rect x="{x:.2f}" y="{y:.2f}" width="{width_px:.2f}" height="{thickness:.2f}" fill="#2a2722"/>')

    room_index = geometry_room_index(geometry)
    for room in _rooms_at_level(geometry, str(level["id"])):
        polygon = room["polygon"]
        points = " ".join(
            f"{transform(float(point[0]), float(point[1]))[0]},{transform(float(point[0]), float(point[1]))[1]}"
            for point in polygon
        )
        elements.append(f'<polygon points="{points}" fill="#f5efe3" stroke="#ded2bc" stroke-width="1.2"/>')
        cx, cy = _room_center(polygon)
        px, py = transform(cx, cy)
        elements.append(_svg_text(px, py, str(room["name"]), size=15, weight="700", anchor="middle"))
        elements.append(_svg_text(px, py + 18, f"{room['area_m2']:.1f} m2", size=12, anchor="middle", fill="#5c564d"))
        notes = room.get("notes")
        if notes:
            elements.append(_svg_text(px, py + 34, str(notes), size=10, anchor="middle", fill="#867d6f"))

    wall_index = {wall["id"]: wall for wall in _walls_at_level(geometry, str(level["id"]))}
    for opening in _openings_at_level(geometry, str(level["id"])):
        wall = wall_index.get(opening["wall_id"])
        if not wall:
            continue
        start = wall["start"]
        end = wall["end"]
        wall_length = max(abs(float(end[0]) - float(start[0])), abs(float(end[1]) - float(start[1])), 0.1)
        position = float(opening["position_along_wall_m"])
        size = float(opening["width_m"])
        if abs(float(start[0]) - float(end[0])) < 0.01:
            y1 = min(float(start[1]), float(end[1])) + position
            y2 = min(y1 + size, max(float(start[1]), float(end[1])))
            p1 = transform(float(start[0]), y1)
            p2 = transform(float(start[0]), y2)
            x = p1[0] - 8
            y = min(p1[1], p2[1])
            height = abs(p1[1] - p2[1])
            color = "#2e79a7" if opening["type"] == "window" else "#fffdf8"
            elements.append(f'<rect x="{x:.2f}" y="{y:.2f}" width="16" height="{height:.2f}" fill="{color}" stroke="#2e79a7" stroke-width="2"/>')
            label_x, label_y = x + 22, y + (height / 2)
        else:
            x1 = min(float(start[0]), float(end[0])) + position
            x2 = min(x1 + size, max(float(start[0]), float(end[0])))
            p1 = transform(x1, float(start[1]))
            p2 = transform(x2, float(start[1]))
            x = min(p1[0], p2[0])
            y = p1[1] - 8
            width_px = abs(p1[0] - p2[0])
            color = "#2e79a7" if opening["type"] == "window" else "#fffdf8"
            elements.append(f'<rect x="{x:.2f}" y="{y:.2f}" width="{width_px:.2f}" height="16" fill="{color}" stroke="#2e79a7" stroke-width="2"/>')
            label_x, label_y = x + (width_px / 2), y - 8
        elements.append(_svg_text(label_x, label_y, str(opening["schedule_mark"]), size=10, weight="700", anchor="middle" if opening["type"] == "window" else "start"))

    for fixture in [item for item in geometry.get("fixtures", []) if item.get("level") == level["id"]]:
        if fixture.get("polygon"):
            points = " ".join(
                f"{transform(float(point[0]), float(point[1]))[0]},{transform(float(point[0]), float(point[1]))[1]}"
                for point in fixture["polygon"]
            )
            elements.append(f'<polygon points="{points}" fill="#d7d0c2" stroke="#8a8172" stroke-width="1.2"/>')
        elif fixture.get("position"):
            px, py = transform(float(fixture["position"][0]), float(fixture["position"][1]))
            elements.append(f'<circle cx="{px}" cy="{py}" r="8" fill="#d7d0c2" stroke="#8a8172" stroke-width="1.2"/>')

    for stair in [item for item in geometry.get("stairs", []) if item.get("from_level") == level["id"]]:
        polygon = stair["position"]
        points = " ".join(
            f"{transform(float(point[0]), float(point[1]))[0]},{transform(float(point[0]), float(point[1]))[1]}"
            for point in polygon
        )
        elements.append(f'<polygon points="{points}" fill="none" stroke="#6f5b2e" stroke-width="2" stroke-dasharray="8 6"/>')
        cx, cy = _room_center(polygon)
        px, py = transform(cx, cy)
        elements.append(_svg_text(px, py, "UP", size=14, weight="700", anchor="middle", fill="#6f5b2e"))

    min_x = min(float(point[0]) for point in site_boundary) if site_boundary else 0
    max_x = max(float(point[0]) for point in site_boundary) if site_boundary else width
    min_y = min(float(point[1]) for point in site_boundary) if site_boundary else 0
    max_y = max(float(point[1]) for point in site_boundary) if site_boundary else depth
    bottom_left = transform(min_x, min_y)
    bottom_right = transform(max_x, min_y)
    top_left = transform(min_x, max_y)
    elements.append(f'<line x1="{bottom_left[0]}" y1="{bottom_left[1] + 28}" x2="{bottom_right[0]}" y2="{bottom_right[1] + 28}" stroke="#1b1a18" stroke-width="1.6"/>')
    elements.append(_svg_text((bottom_left[0] + bottom_right[0]) / 2, bottom_left[1] + 22, f"{max_x - min_x:.2f} m", size=12, weight="700", anchor="middle"))
    elements.append(f'<line x1="{top_left[0] - 28}" y1="{top_left[1]}" x2="{bottom_left[0] - 28}" y2="{bottom_left[1]}" stroke="#1b1a18" stroke-width="1.6"/>')
    elements.append(_svg_text(top_left[0] - 38, (top_left[1] + bottom_left[1]) / 2, f"{max_y - min_y:.2f} m", size=12, weight="700", anchor="middle"))
    elements.append(_svg_text(SHEET_WIDTH - 118, DRAWING_TOP + 18, "N", size=20, weight="700", anchor="middle"))
    elements.append(f'<path d="M {SHEET_WIDTH - 118} {DRAWING_TOP + 32} L {SHEET_WIDTH - 128} {DRAWING_TOP + 56} L {SHEET_WIDTH - 108} {DRAWING_TOP + 56} Z" fill="#1b1a18"/>')

    return _svg_root(elements)


def _openings_for_face(geometry: dict[str, Any], face: str) -> list[dict[str, Any]]:
    return [opening for opening in geometry.get("openings", []) if opening.get("face") == face]


def _build_elevation_svg(
    project_name: str,
    sheet_number: str,
    face: str,
    geometry: dict[str, Any],
    revision_label: str,
    *,
    deliverable_preset: str = "technical_neutral",
    package_status: str = "review",
    issue_date: str | None = None,
) -> str:
    transform, _ = _elevation_transform(geometry)
    title = f"{face.title()} Elevation"
    elements = _sheet_frame(
        project_name,
        sheet_number,
        title,
        "1:100",
        revision_label,
        deliverable_preset=deliverable_preset,
        package_status=package_status,
        issue_date=issue_date,
    )
    site = geometry.get("site", {})
    levels = geometry.get("levels", [])
    width = float(site.get("boundary", [[0, 0], [5, 0]])[1][0]) if site.get("boundary") else 5.0
    roof_top = float(geometry.get("roof", {}).get("elevation_top_m", levels[-1].get("elevation_m", 0) if levels else 14.0)) + float(geometry.get("roof", {}).get("parapet_height_m", 0.6))
    ground_left = transform(0.0, 0.0)
    ground_right = transform(width, 0.0)
    top_left = transform(0.0, roof_top)
    elements.append(f'<line x1="{ground_left[0]}" y1="{ground_left[1]}" x2="{ground_right[0]}" y2="{ground_right[1]}" stroke="#1b1a18" stroke-width="3"/>')
    elements.append(f'<rect x="{top_left[0]}" y="{top_left[1]}" width="{ground_right[0] - ground_left[0]}" height="{ground_left[1] - top_left[1]}" fill="#f4efe6" stroke="#1b1a18" stroke-width="2.4"/>')

    level_index = geometry_level_index(geometry)
    for axis in geometry.get("grids", {}).get("axes_x", []):
        x = float(axis["position"])
        start = transform(x, 0.0)
        end = transform(x, roof_top)
        elements.append(f'<line x1="{start[0]}" y1="{start[1]}" x2="{end[0]}" y2="{end[1]}" stroke="#d1c5b1" stroke-width="1.2" stroke-dasharray="4 4"/>')
        elements.append(f'<circle cx="{start[0]}" cy="{ground_left[1] + 18}" r="10" fill="#fffdf8" stroke="#1b1a18" stroke-width="1.4"/>')
        elements.append(_svg_text(start[0], ground_left[1] + 22, str(axis["id"]), size=12, weight="700", anchor="middle"))

    for level in [item for item in levels if item.get("type") == "floor"]:
        z = float(level["elevation_m"])
        start = transform(0.0, z)
        end = transform(width, z)
        elements.append(f'<line x1="{start[0]}" y1="{start[1]}" x2="{end[0]}" y2="{end[1]}" stroke="#7d7467" stroke-width="1.5"/>')
        elements.append(_svg_text(end[0] + 16, start[1] + 4, f"{level['name']} +{z:.2f}", size=12, weight="700"))

    for opening in _openings_for_face(geometry, face):
        level = level_index.get(str(opening["level"]))
        base_z = float(level.get("elevation_m", 0)) if level else 0.0
        opening_height = float(opening["height_m"])
        sill = float(opening.get("sill_height_m", 0.0))
        x1 = float(opening["position_along_wall_m"])
        x2 = x1 + float(opening["width_m"])
        p1 = transform(x1, base_z + sill)
        p2 = transform(x2, base_z + sill + opening_height)
        elements.append(
            f'<rect x="{p1[0]}" y="{p2[1]}" width="{p2[0] - p1[0]}" height="{p1[1] - p2[1]}" fill="#d7ebf7" stroke="#205d67" stroke-width="2"/>'
        )
        elements.append(_svg_text((p1[0] + p2[0]) / 2, p2[1] - 8, str(opening["schedule_mark"]), size=10, weight="700", anchor="middle"))

    elements.append(_svg_text(DRAWING_LEFT + 14, DRAWING_TOP + 28, f"Facade finish: {geometry['walls'][0].get('finish_tag', 'painted plaster')}", size=13, weight="700"))
    elements.append(_svg_text(DRAWING_LEFT + 14, DRAWING_TOP + 48, f"Roof finish: {geometry.get('roof', {}).get('layers', [{}])[-1].get('material', 'waterproof membrane')}", size=12))
    total_height_point = transform(width, roof_top)
    elements.append(f'<line x1="{ground_right[0] + 28}" y1="{ground_right[1]}" x2="{total_height_point[0] + 28}" y2="{total_height_point[1]}" stroke="#1b1a18" stroke-width="1.6"/>')
    elements.append(_svg_text(ground_right[0] + 42, (ground_right[1] + total_height_point[1]) / 2, f"{roof_top:.2f} m", size=12, weight="700"))
    return _svg_root(elements)


def _build_section_svg(
    project_name: str,
    sheet_number: str,
    section_id: str,
    geometry: dict[str, Any],
    revision_label: str,
    *,
    deliverable_preset: str = "technical_neutral",
    package_status: str = "review",
    issue_date: str | None = None,
) -> str:
    transform, _ = _elevation_transform(geometry)
    title = next((item["label"] for item in geometry.get("markers", {}).get("sections", []) if item["id"] == section_id), f"Section {section_id}")
    elements = _sheet_frame(
        project_name,
        sheet_number,
        title,
        "1:100",
        revision_label,
        deliverable_preset=deliverable_preset,
        package_status=package_status,
        issue_date=issue_date,
    )
    site = geometry.get("site", {})
    levels = geometry.get("levels", [])
    width = float(site.get("boundary", [[0, 0], [5, 0]])[1][0]) if site.get("boundary") else 5.0
    roof_top = float(geometry.get("roof", {}).get("elevation_top_m", levels[-1].get("elevation_m", 0) if levels else 14.0)) + float(geometry.get("roof", {}).get("parapet_height_m", 0.6))
    outer_left = transform(0.0, 0.0)
    outer_right = transform(width, 0.0)
    top_left = transform(0.0, roof_top)
    elements.append(f'<rect x="{top_left[0]}" y="{top_left[1]}" width="{outer_right[0] - outer_left[0]}" height="{outer_left[1] - top_left[1]}" fill="#fbf8f1" stroke="#1b1a18" stroke-width="2.4"/>')

    for level in [item for item in levels if item.get("type") == "floor"]:
        z = float(level["elevation_m"])
        slab = float(level.get("slab_thickness_m", 0.12))
        start = transform(0.0, z)
        slab_top = transform(0.0, z + slab)
        elements.append(f'<rect x="{outer_left[0]}" y="{slab_top[1]}" width="{outer_right[0] - outer_left[0]}" height="{start[1] - slab_top[1]}" fill="#403b36"/>')
        elements.append(_svg_text(outer_right[0] + 16, start[1] + 4, f"{level['name']} +{z:.2f}", size=12, weight="700"))

    for stair in geometry.get("stairs", []):
        polygon = stair["position"]
        xs = [point[0] for point in polygon]
        min_x = min(xs)
        max_x = max(xs)
        lower = next((item for item in levels if item["id"] == stair["from_level"]), None)
        upper = next((item for item in levels if item["id"] == stair["to_level"]), None)
        if not lower:
            continue
        lower_z = float(lower["elevation_m"])
        upper_z = float(upper["elevation_m"]) if upper else roof_top
        start = transform(min_x, lower_z + 0.15)
        end = transform(max_x, upper_z - 0.15)
        elements.append(f'<line x1="{start[0]}" y1="{start[1]}" x2="{end[0]}" y2="{end[1]}" stroke="#6f5b2e" stroke-width="4"/>')
        elements.append(_svg_text((start[0] + end[0]) / 2, (start[1] + end[1]) / 2 - 8, "STAIR", size=12, weight="700", anchor="middle", fill="#6f5b2e"))

    elements.append(_svg_text(DRAWING_LEFT + 12, DRAWING_TOP + 28, f"{section_id} cuts canonical geometry for coordinated DD package", size=13, weight="700"))
    return _svg_root(elements)


def build_schedule_rows(geometry: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    room_index = geometry_room_index(geometry)
    door_rows: list[dict[str, Any]] = []
    window_rows: list[dict[str, Any]] = []
    room_rows: list[dict[str, Any]] = []

    for opening in geometry.get("openings", []):
        room = room_index.get(str(opening.get("room_id")))
        base = {
            "mark": opening.get("schedule_mark"),
            "room": room.get("name") if room else opening.get("room_id"),
            "type": opening.get("subtype"),
            "size_wxh": f"{int(float(opening.get('width_m', 0)) * 1000)}x{int(float(opening.get('height_m', 0)) * 1000)}",
            "level": opening.get("level"),
        }
        if opening.get("type") == "door":
            door_rows.append(
                {
                    **base,
                    "frame": opening.get("frame", {}).get("material"),
                    "panel": opening.get("panel", {}).get("material"),
                    "hardware": " + ".join(
                        item
                        for item in [
                            opening.get("hardware", {}).get("handle"),
                            opening.get("hardware", {}).get("lock"),
                        ]
                        if item
                    ),
                    "fire": opening.get("fire_rating") or "-",
                    "notes": f"{opening.get('panel', {}).get('leaves', 1)} leaf / {opening.get('panel', {}).get('swing_direction', 'swing')}",
                }
            )
        else:
            window_rows.append(
                {
                    **base,
                    "sill_mm": int(float(opening.get("sill_height_m", 0)) * 1000),
                    "frame": " ".join(
                        item
                        for item in [
                            opening.get("frame", {}).get("material"),
                            opening.get("frame", {}).get("color"),
                            opening.get("frame", {}).get("profile"),
                        ]
                        if item
                    ),
                    "glazing": f"{opening.get('glazing', {}).get('type', '')} {opening.get('glazing', {}).get('thickness_mm', '')}".strip(),
                    "u_value": opening.get("glazing", {}).get("u_value"),
                    "notes": " ".join(
                        item
                        for item in [
                            opening.get("operation", {}).get("type"),
                            opening.get("operation", {}).get("hinge_side"),
                        ]
                        if item
                    ),
                }
            )

    level_totals: dict[str, float] = defaultdict(float)
    for room in geometry.get("rooms", []):
        level_totals[str(room.get("level"))] += float(room.get("area_m2") or 0)
        room_rows.append(
            {
                "row_type": "room",
                "id": room.get("id"),
                "room_name": room.get("name"),
                "level": room.get("level"),
                "area_m2": room.get("area_m2"),
                "height_m": room.get("clear_height_m"),
                "floor_finish": room.get("finishes", {}).get("floor", {}).get("material"),
                "wall_finish": room.get("finishes", {}).get("wall", {}).get("material"),
                "ceiling_finish": room.get("finishes", {}).get("ceiling", {}).get("material"),
                "notes": room.get("notes") or "",
            }
        )
    for level_id, total in level_totals.items():
        room_rows.append({"row_type": "level_total", "level": level_id, "area_m2": round(total, 2)})
    room_rows.append({"row_type": "building_total", "area_m2": round(sum(level_totals.values()), 2)})

    door_rows.sort(key=lambda item: item["mark"])
    window_rows.sort(key=lambda item: item["mark"])
    return {"door": door_rows, "window": window_rows, "room": room_rows}


def _rows_to_csv(rows: list[dict[str, Any]], headers: list[str]) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=headers)
    writer.writeheader()
    for row in rows:
        writer.writerow({key: row.get(key, "") for key in headers})
    return buffer.getvalue()


def build_schedule_csvs(geometry: dict[str, Any]) -> dict[str, str]:
    rows = build_schedule_rows(geometry)
    return {
        "door": _rows_to_csv(rows["door"], ["mark", "room", "type", "size_wxh", "frame", "panel", "hardware", "fire", "notes", "level"]),
        "window": _rows_to_csv(rows["window"], ["mark", "room", "type", "size_wxh", "sill_mm", "frame", "glazing", "u_value", "notes", "level"]),
        "room": _rows_to_csv(rows["room"], ["row_type", "id", "room_name", "level", "area_m2", "height_m", "floor_finish", "wall_finish", "ceiling_finish", "notes"]),
    }


def _render_table(
    project_name: str,
    sheet_number: str,
    title: str,
    columns: list[str],
    rows: list[dict[str, Any]],
    revision_label: str,
    *,
    deliverable_preset: str = "technical_neutral",
    package_status: str = "review",
    issue_date: str | None = None,
) -> str:
    elements = _sheet_frame(
        project_name,
        sheet_number,
        title,
        None,
        revision_label,
        deliverable_preset=deliverable_preset,
        package_status=package_status,
        issue_date=issue_date,
    )
    top = DRAWING_TOP + 18
    left = DRAWING_LEFT
    table_width = SHEET_WIDTH - DRAWING_LEFT - DRAWING_RIGHT
    column_width = table_width / len(columns)
    row_height = 26
    elements.append(f'<rect x="{left}" y="{top}" width="{table_width}" height="{row_height}" fill="#e6decd" stroke="#1b1a18" stroke-width="1.5"/>')
    for index, column in enumerate(columns):
        x = left + index * column_width
        if index:
            elements.append(f'<line x1="{x}" y1="{top}" x2="{x}" y2="{top + row_height + (len(rows) * row_height)}" stroke="#8a8172" stroke-width="1"/>')
        elements.append(_svg_text(x + 8, top + 18, column, size=11, weight="700"))

    for row_index, row in enumerate(rows):
        y = top + row_height + row_index * row_height
        fill = "#fffdf8" if row_index % 2 == 0 else "#f7f2e9"
        elements.append(f'<rect x="{left}" y="{y}" width="{table_width}" height="{row_height}" fill="{fill}" stroke="#d8d0c1" stroke-width="0.6"/>')
        for col_index, column in enumerate(columns):
            x = left + col_index * column_width
            elements.append(_svg_text(x + 8, y + 18, str(row.get(column, ""))[:28], size=10))
    return _svg_root(elements)


def _build_notes_svg(
    project_name: str,
    revision_label: str,
    *,
    deliverable_preset: str = "technical_neutral",
    package_status: str = "review",
    issue_date: str | None = None,
) -> str:
    elements = _sheet_frame(
        project_name,
        "A13",
        "General Notes / Legend",
        None,
        revision_label,
        deliverable_preset=deliverable_preset,
        package_status=package_status,
        issue_date=issue_date,
    )
    notes = [
        "GENERAL NOTES",
        "1. All drawings derive from a single canonical geometry source.",
        "2. Package is for design development alignment and coordination.",
        "3. Verify all dimensions on site before construction.",
        "4. DXF and IFC are issued as interoperability deliverables.",
        SHORT_DISCLAIMER,
    ]
    for index, line in enumerate(notes):
        elements.append(_svg_text(72, 132 + index * 34, line, size=18 if index == 0 else 14, weight="700" if index == 0 else "400"))
    return _svg_root(elements)


def _build_key_detail_svg(
    project_name: str,
    sheet_number: str,
    title: str,
    geometry: dict[str, Any],
    revision_label: str,
    *,
    deliverable_preset: str = "technical_neutral",
    package_status: str = "review",
    issue_date: str | None = None,
    detail_kind: str,
) -> str:
    style = _preset_style(deliverable_preset, package_status)
    elements = _sheet_frame(
        project_name,
        sheet_number,
        title,
        "1:20",
        revision_label,
        deliverable_preset=deliverable_preset,
        package_status=package_status,
        issue_date=issue_date,
    )
    elements.append(f'<rect x="60" y="110" width="1080" height="580" fill="{style["sheet_fill"]}" stroke="{style["line"]}" stroke-width="1.4"/>')

    if detail_kind == "wall_roof":
        wall = next((item for item in geometry.get("walls", []) if item.get("type") == "exterior"), None)
        layers = (wall or {}).get("assembly", {}).get("layers", [])
        x = 140
        for layer in layers or [{"material": "painted_plaster", "thickness_m": 0.015}, {"material": "brick_100", "thickness_m": 0.1}, {"material": "textured_plaster", "thickness_m": 0.015}]:
            width = max(float(layer.get("thickness_m", 0.05)) * 900, 18)
            elements.append(f'<rect x="{x:.1f}" y="250" width="{width:.1f}" height="240" fill="{style["title_fill"]}" stroke="{style["line"]}" stroke-width="1.2"/>')
            elements.append(_svg_text(x + 10, 520, str(layer.get("material", "layer")).replace("_", " "), size=12, fill=style["line"]))
            x += width
        elements.extend(
            [
                _svg_text(140, 190, "Typical exterior wall build-up", size=18, weight="700", fill=style["accent"]),
                _svg_text(140, 220, "Facade finish, wall core, and roof edge relationship.", size=13, fill=style["muted"]),
                f'<line x1="530" y1="190" x2="700" y2="150" stroke="{style["accent"]}" stroke-width="2"/>',
                f'<line x1="700" y1="150" x2="860" y2="150" stroke="{style["accent"]}" stroke-width="2"/>',
                _svg_text(874, 154, "Roof edge / parapet", size=12, fill=style["accent"]),
            ]
        )
    else:
        stair = next(iter(geometry.get("stairs", [])), None)
        rise = float((stair or {}).get("rise_m", 0.165))
        run = float((stair or {}).get("run_m", 0.265))
        riser_count = int((stair or {}).get("riser_count", 18))
        start_x = 160
        start_y = 520
        for index in range(min(riser_count, 8)):
            x1 = start_x + index * 60
            y1 = start_y - index * 30
            elements.append(f'<path d="M {x1} {y1} L {x1 + 60} {y1} L {x1 + 60} {y1 - 30}" fill="none" stroke="{style["line"]}" stroke-width="3"/>')
        elements.extend(
            [
                _svg_text(140, 190, "Typical stair / threshold detail", size=18, weight="700", fill=style["accent"]),
                _svg_text(140, 220, f"Rule-based stair detail | rise {int(rise * 1000)} mm | run {int(run * 1000)} mm", size=13, fill=style["muted"]),
                _svg_text(160, 570, f"Riser count: {riser_count}", size=13, fill=style["line"]),
                _svg_text(160, 596, "Threshold + landing condition coordinated with section geometry.", size=12, fill=style["muted"]),
            ]
        )
    return _svg_root(elements)


def _count_brief_leaves(payload: Any) -> int:
    if isinstance(payload, dict):
        return sum(_count_brief_leaves(value) for value in payload.values())
    if isinstance(payload, list):
        return sum(_count_brief_leaves(value) for value in payload)
    return 1 if payload not in (None, "", []) else 0


def summarize_assumptions(brief_json: dict[str, Any] | None) -> dict[str, int]:
    confirmed = _count_brief_leaves(brief_json or {})
    return {"total": confirmed, "confirmed": confirmed, "inferred": 0, "default": 0}


def validate_package_bundle(bundle: dict[str, Any]) -> dict[str, Any]:
    sheets = bundle.get("sheets", [])
    blocking_issues: list[str] = []
    warnings: list[str] = []
    if bundle.get("deliverable_preset") not in ALLOWED_PRESETS:
        blocking_issues.append("Unsupported deliverable preset.")
    if len(sheets) < 12:
        blocking_issues.append("Package must include at least 12 sheets.")
    detail_sheets = [sheet for sheet in sheets if str(sheet.get("type", "")).startswith("key_detail")]
    if len(detail_sheets) < 2:
        blocking_issues.append("Package must include at least 2 key detail sheets.")
    if not any(str(sheet.get("type", "")).startswith("schedule_") for sheet in sheets):
        warnings.append("Schedule sheets are missing.")
    return {
        "status": "fail" if blocking_issues else "pass",
        "blocking_issues": blocking_issues,
        "warnings": warnings,
        "sheet_count": len(sheets),
        "detail_sheet_count": len(detail_sheets),
    }


def build_sheet_bundle(
    project_name: str,
    version_number: int,
    geometry: dict[str, Any],
    revision_label: str = "A",
    *,
    brief_json: dict[str, Any] | None = None,
    deliverable_preset: str = "technical_neutral",
    package_status: str = "review",
    issue_date: str | None = None,
) -> dict[str, Any]:
    ensured_geometry = ensure_geometry_v2(geometry, {})
    sheets: list[dict[str, Any]] = []
    schedule_rows = build_schedule_rows(ensured_geometry)
    csv_payloads = build_schedule_csvs(ensured_geometry)
    floor_levels = [level for level in ensured_geometry.get("levels", []) if level.get("type") == "floor"]
    resolved_issue_date = _issue_date(issue_date)

    cover_lines = _sheet_frame(
        project_name,
        "A0",
        "Cover / Issue Sheet",
        None,
        revision_label,
        deliverable_preset=deliverable_preset,
        package_status=package_status,
        issue_date=resolved_issue_date,
    )
    cover_lines.extend(
        [
            _svg_text(72, 126, "DESIGN DEVELOPMENT PACKAGE", size=30, weight="700"),
            _svg_text(72, 162, f"Version V{version_number} / {deliverable_preset.replace('_', ' ').title()}", size=16),
            _svg_text(72, 202, f"Lot area: {ensured_geometry['project_info']['lot_area_m2']} m2", size=16),
            _svg_text(72, 228, f"Total floor area: {ensured_geometry['project_info']['total_floor_area_m2']} m2", size=16),
            _svg_text(72, 254, "Package contents:", size=16, weight="700"),
            _svg_text(72, 610, COVER_DISCLAIMER, size=12),
            _svg_text(72, 640, f"Status: {_status_label(package_status)}", size=12, weight="700"),
            _svg_text(72, 664, f"Issue date: {resolved_issue_date}", size=12),
        ]
    )
    sheet_titles = [
        "A1 Site / Plot Plan",
        *[f"A{index + 2} Floor Plan - {level['name']}" for index, level in enumerate(floor_levels)],
        "A6-S South Elevation",
        "A6-N North Elevation",
        "A7-E East Elevation",
        "A7-W West Elevation",
        "A8-A Section A-A",
        "A8-B Section B-B",
        "A9 Door + Window Schedule",
        "A10 Room / Area Schedule",
        "A11 Key Detail - Wall / Roof",
        "A12 Key Detail - Stair / Threshold",
        "A13 General Notes / Legend",
    ]
    for line_index, label in enumerate(sheet_titles, start=0):
        cover_lines.append(_svg_text(88, 288 + line_index * 22, f"• {label}", size=13))
    sheets.append({"number": "A0", "title": "Cover / Issue Sheet", "type": "cover", "scale": None, "svg": _svg_root(cover_lines)})

    site_svg = _build_plan_svg(
        project_name,
        1,
        ensured_geometry,
        floor_levels[0],
        revision_label,
        sheet_title="Site / Plot Plan",
        deliverable_preset=deliverable_preset,
        package_status=package_status,
        issue_date=resolved_issue_date,
    )
    sheets.append({"number": "A1", "title": "Site / Plot Plan", "type": "site", "scale": "1:200", "svg": site_svg})

    for index, level in enumerate(floor_levels, start=2):
        sheets.append(
            {
                "number": f"A{index}",
                "title": f"Floor Plan - {level['name']}",
                "type": f"floor_plan_{level['id'].lower()}",
                "scale": "1:100",
                "level": level["id"],
                "svg": _build_plan_svg(
                    project_name,
                    index,
                    ensured_geometry,
                    level,
                    revision_label,
                    deliverable_preset=deliverable_preset,
                    package_status=package_status,
                    issue_date=resolved_issue_date,
                ),
            }
        )

    elevation_defs = [("A6-S", "south"), ("A6-N", "north"), ("A7-E", "east"), ("A7-W", "west")]
    for sheet_number, face in elevation_defs:
        sheets.append(
            {
                "number": sheet_number,
                "title": f"{face.title()} Elevation",
                "type": f"elevation_{face}",
                "scale": "1:100",
                "svg": _build_elevation_svg(
                    project_name,
                    sheet_number,
                    face,
                    ensured_geometry,
                    revision_label,
                    deliverable_preset=deliverable_preset,
                    package_status=package_status,
                    issue_date=resolved_issue_date,
                ),
            }
        )

    for sheet_number, section_id in [("A8-A", "S1"), ("A8-B", "S2")]:
        sheets.append(
            {
                "number": sheet_number,
                "title": next(
                    (item["label"] for item in ensured_geometry.get("markers", {}).get("sections", []) if item["id"] == section_id),
                    section_id,
                ),
                "type": f"section_{section_id.lower()}",
                "scale": "1:100",
                "svg": _build_section_svg(
                    project_name,
                    sheet_number,
                    section_id,
                    ensured_geometry,
                    revision_label,
                    deliverable_preset=deliverable_preset,
                    package_status=package_status,
                    issue_date=resolved_issue_date,
                ),
            }
        )

    sheets.append(
        {
            "number": "A9",
            "title": "Door + Window Schedule",
            "type": "schedule_openings",
            "scale": None,
            "svg": _render_table(
                project_name,
                "A9",
                "Door + Window Schedule",
                ["mark", "room", "type", "size_wxh", "frame", "notes"],
                schedule_rows["door"] + schedule_rows["window"],
                revision_label,
                deliverable_preset=deliverable_preset,
                package_status=package_status,
                issue_date=resolved_issue_date,
            ),
        }
    )
    sheets.append(
        {
            "number": "A10",
            "title": "Room / Area Schedule",
            "type": "schedule_rooms",
            "scale": None,
            "svg": _render_table(
                project_name,
                "A10",
                "Room / Area Schedule",
                ["row_type", "room_name", "level", "area_m2", "height_m", "floor_finish", "wall_finish"],
                schedule_rows["room"],
                revision_label,
                deliverable_preset=deliverable_preset,
                package_status=package_status,
                issue_date=resolved_issue_date,
            ),
        }
    )
    sheets.append(
        {
            "number": "A11",
            "title": "Key Detail - Wall / Roof",
            "type": "key_detail_wall_roof",
            "scale": "1:20",
            "svg": _build_key_detail_svg(
                project_name,
                "A11",
                "Key Detail - Wall / Roof",
                ensured_geometry,
                revision_label,
                deliverable_preset=deliverable_preset,
                package_status=package_status,
                issue_date=resolved_issue_date,
                detail_kind="wall_roof",
            ),
        }
    )
    sheets.append(
        {
            "number": "A12",
            "title": "Key Detail - Stair / Threshold",
            "type": "key_detail_stair_threshold",
            "scale": "1:20",
            "svg": _build_key_detail_svg(
                project_name,
                "A12",
                "Key Detail - Stair / Threshold",
                ensured_geometry,
                revision_label,
                deliverable_preset=deliverable_preset,
                package_status=package_status,
                issue_date=resolved_issue_date,
                detail_kind="stair_threshold",
            ),
        }
    )
    sheets.append(
        {
            "number": "A13",
            "title": "General Notes / Legend",
            "type": "notes",
            "scale": None,
            "svg": _build_notes_svg(
                project_name,
                revision_label,
                deliverable_preset=deliverable_preset,
                package_status=package_status,
                issue_date=resolved_issue_date,
            ),
        }
    )
    assumptions = summarize_assumptions(brief_json)
    return {
        "manifest_version": "2.0",
        "issue_type": "design-development-package",
        "revision_label": revision_label,
        "generated_at": _utcnow(),
        "status": package_status,
        "issue_date": resolved_issue_date,
        "deliverable_preset": deliverable_preset,
        "export_pipeline_version": EXPORT_PIPELINE_VERSION,
        "assumptions": assumptions,
        "sheets": sheets,
        "csv_payloads": csv_payloads,
        "schedule_rows": schedule_rows,
        "top_level_exports": {
            "pdf": None,
            "svg": None,
            "dxf": None,
            "ifc": None,
            "manifest": None,
            "door_csv": None,
            "window_csv": None,
            "room_csv": None,
        },
    }


def build_dxf_bytes(project_name: str, version_number: int, geometry: dict[str, Any]) -> bytes:
    if ezdxf is None:  # pragma: no cover - optional dependency
        payload = f"999\nFallback DXF for {project_name} V{version_number}\n0\nEOF\n"
        return payload.encode("utf-8")

    doc = ezdxf.new("R2018")
    for layer_name, props in DXF_LAYER_MAP.items():
        if layer_name not in doc.layers:
            doc.layers.add(layer_name, color=props["color"], lineweight=props["lineweight"])
    msp = doc.modelspace()

    site_boundary = geometry.get("site", {}).get("boundary") or []
    if site_boundary:
        msp.add_lwpolyline(site_boundary + [site_boundary[0]], dxfattribs={"layer": "A-SITE-BNDY", "closed": True})

    level_offsets: dict[str, float] = {}
    offset_y = 0.0
    for level in [item for item in geometry.get("levels", []) if item.get("type") == "floor"]:
        level_offsets[level["id"]] = offset_y
        offset_y += 30.0

    for wall in geometry.get("walls", []):
        level_offset = level_offsets.get(str(wall.get("level")), 0.0)
        start = (float(wall["start"][0]), float(wall["start"][1]) + level_offset)
        end = (float(wall["end"][0]), float(wall["end"][1]) + level_offset)
        wall_type = str(wall.get("type"))
        layer = "A-WALL-PRTY" if wall_type == "party_wall" else ("A-WALL-EXTR" if wall_type == "exterior" else "A-WALL-INTR")
        msp.add_line(start, end, dxfattribs={"layer": layer})

    room_index = geometry_room_index(geometry)
    wall_index = {wall["id"]: wall for wall in geometry.get("walls", [])}
    for opening in geometry.get("openings", []):
        wall = wall_index.get(opening["wall_id"])
        if not wall:
            continue
        level_offset = level_offsets.get(str(opening.get("level")), 0.0)
        start = wall["start"]
        end = wall["end"]
        position = float(opening["position_along_wall_m"])
        width_m = float(opening["width_m"])
        if abs(float(start[0]) - float(end[0])) < 0.01:
            y1 = min(float(start[1]), float(end[1])) + position + level_offset
            y2 = y1 + width_m
            x = float(start[0])
            msp.add_line((x, y1), (x, y2), dxfattribs={"layer": "A-GLAZ" if opening["type"] == "window" else "A-DOOR"})
        else:
            x1 = min(float(start[0]), float(end[0])) + position
            x2 = x1 + width_m
            y = float(start[1]) + level_offset
            msp.add_line((x1, y), (x2, y), dxfattribs={"layer": "A-GLAZ" if opening["type"] == "window" else "A-DOOR"})
        room = room_index.get(str(opening.get("room_id")))
        if room:
            center = _room_center(room["polygon"])
            msp.add_text(str(opening["schedule_mark"]), dxfattribs={"layer": "A-ANNO-TEXT", "height": 0.18}).set_placement((center[0], center[1] + level_offset))

    for room in geometry.get("rooms", []):
        level_offset = level_offsets.get(str(room.get("level")), 0.0)
        center = _room_center(room["polygon"])
        msp.add_text(str(room["name"]), dxfattribs={"layer": "A-ANNO-ROOM", "height": 0.22}).set_placement((center[0], center[1] + level_offset))

    faces = ["south", "north", "east", "west"]
    for index, face in enumerate(faces):
        base_x = 20 + index * 10
        msp.add_text(f"{face.title()} Elevation", dxfattribs={"layer": "A-ELEV-OUTL", "height": 0.3}).set_placement((base_x, -5))

    layouts = [
        "A0-COVER",
        "A1-SITE",
        *[f"A{index + 2}-{level['id']}" for index, level in enumerate([item for item in geometry.get("levels", []) if item.get("type") == "floor"])],
        "A6-SOUTH",
        "A6-NORTH",
        "A7-EAST",
        "A7-WEST",
        "A8-SECTIONS",
        "A9-SCHEDULES",
        "A10-ROOMS",
    ]
    for name in layouts:
        if name in doc.layouts:
            continue
        layout = doc.layouts.new(name)
        layout.add_text(f"{project_name} {name}", dxfattribs={"layer": "A-ANNO-TTLB", "height": 10})

    stream = io.StringIO()
    doc.write(stream)
    return stream.getvalue().encode("utf-8")


def build_ifc_bytes(project_name: str, version_number: int, geometry: dict[str, Any]) -> bytes:
    rooms = geometry.get("rooms", [])
    walls = geometry.get("walls", [])
    openings = geometry.get("openings", [])
    levels = [level for level in geometry.get("levels", []) if level.get("type") == "floor"]

    def gid(seed: str) -> str:
        token = (seed.replace("-", "").replace(" ", "").upper() + "0" * 22)[:22]
        return token

    line_no = 1
    lines: list[str] = []

    def add(statement: str) -> int:
        nonlocal line_no
        current = line_no
        lines.append(f"#{current}={statement};")
        line_no += 1
        return current

    owner = add("IFCPERSON($,$,'KTC KTS',$,$,$,$,$)")
    org = add("IFCORGANIZATION($,'KTC KTS',$,$,$)")
    person_org = add(f"IFCPERSONANDORGANIZATION(#{owner},#{org},$)")
    app = add(f"IFCAPPLICATION(#{org},'3.0','KTC KTS','AIARCH')")
    history = add(f"IFCOWNERHISTORY(#{person_org},#{app},$,.ADDED.,$,$,$,0)")
    origin = add("IFCCARTESIANPOINT((0.,0.,0.))")
    axis = add(f"IFCAXIS2PLACEMENT3D(#{origin},$,$)")
    context = add(f"IFCGEOMETRICREPRESENTATIONCONTEXT($,'Model',3,1.E-05,#{axis},$)")
    unit = add("IFCSIUNIT(*,.LENGTHUNIT.,$,.METRE.)")
    units = add(f"IFCUNITASSIGNMENT((#{unit}))")
    project = add(f"IFCPROJECT('{gid(project_name)}',#{history},'{project_name}',$,$,$,$,(#{context}),#{units})")
    placement_site = add(f"IFCLOCALPLACEMENT($,#{axis})")
    site = add(f"IFCSITE('{gid('site')}',#{history},'Site',$,$,#{placement_site},$,$,.ELEMENT.,$,$,$,$,$)")
    placement_building = add(f"IFCLOCALPLACEMENT(#{placement_site},#{axis})")
    building = add(f"IFCBUILDING('{gid('building')}',#{history},'Building',$,$,#{placement_building},$,$,.ELEMENT.,$,$,$)")
    add(f"IFCRELAGGREGATES('{gid('agg-site')}',#{history},$,$,#{project},(#{site}))")
    add(f"IFCRELAGGREGATES('{gid('agg-building')}',#{history},$,$,#{site},(#{building}))")

    storey_refs: list[int] = []
    for level in levels:
        storey_place = add(f"IFCLOCALPLACEMENT(#{placement_building},#{axis})")
        storey = add(
            f"IFCBUILDINGSTOREY('{gid(level['id'])}',#{history},'{level['name']}',$,$,#{storey_place},$,$,.ELEMENT.,{float(level['elevation_m']):.3f})"
        )
        storey_refs.append(storey)
    if storey_refs:
        add(f"IFCRELAGGREGATES('{gid('agg-storeys')}',#{history},$,$,#{building},({','.join(f'#{item}' for item in storey_refs)}))")

    containment: dict[str, list[int]] = defaultdict(list)
    for wall in walls:
        entity = add(
            f"IFCBUILDINGELEMENTPROXY('{gid(wall['id'])}',#{history},'{wall['id']}','{wall.get('type','wall')}',$,$,$,$,.USERDEFINED.)"
        )
        containment[str(wall.get("level"))].append(entity)
    for opening in openings:
        entity = add(
            f"IFCBUILDINGELEMENTPROXY('{gid(opening['id'])}',#{history},'{opening['schedule_mark']}','{opening.get('type','opening')}',$,$,$,$,.USERDEFINED.)"
        )
        containment[str(opening.get("level"))].append(entity)
    for room in rooms:
        entity = add(
            f"IFCSPACE('{gid(room['id'])}',#{history},'{room['name']}',$,$,$,$,$,.INTERNAL.,{float(room.get('area_m2', 0)):.2f})"
        )
        containment[str(room.get("level"))].append(entity)

    for level, storey_ref in zip(levels, storey_refs):
        members = containment.get(str(level["id"]), [])
        if members:
            add(
                f"IFCRELCONTAINEDINSPATIALSTRUCTURE('{gid('contain-' + str(level['id']))}',#{history},$,$,({','.join(f'#{item}' for item in members)}),#{storey_ref})"
            )

    payload = [
        "ISO-10303-21;",
        "HEADER;",
        "FILE_DESCRIPTION(('ViewDefinition [DesignTransferView]'),'2;1');",
        f"FILE_NAME('{project_name}_v{version_number}.ifc','{datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S')}',('Codex'),('OpenAI'),'KTC KTS','Codex','');",
        "FILE_SCHEMA(('IFC4'));",
        "ENDSEC;",
        "DATA;",
        *lines,
        "ENDSEC;",
        "END-ISO-10303-21;",
    ]
    return "\n".join(payload).encode("utf-8")


def _sheet_svg_to_pdf_page(pdf: canvas.Canvas, svg_content: str) -> None:
    if svg2rlg is not None and renderPDF is not None:  # pragma: no cover - visual helper
        drawing = svg2rlg(io.StringIO(svg_content))
        if drawing is not None:
            scale_x = PAGE_SIZE[0] / max(drawing.width, 1)
            scale_y = PAGE_SIZE[1] / max(drawing.height, 1)
            scale = min(scale_x, scale_y)
            drawing.scale(scale, scale)
            renderPDF.draw(drawing, pdf, 0, 0)
            return

    pdf.setFont("Helvetica-Bold", 18)
    pdf.drawString(48, PAGE_SIZE[1] - 48, "KTC KTS")
    pdf.setFont("Helvetica", 11)
    for index, line in enumerate(svg_content.splitlines()[:28], start=1):
        pdf.drawString(48, PAGE_SIZE[1] - 48 - index * 18, line[:110])


def build_pdf_bytes(
    project_name: str,
    version_number: int,
    geometry: dict[str, Any],
    revision_label: str = "A",
    *,
    brief_json: dict[str, Any] | None = None,
    deliverable_preset: str = "technical_neutral",
    package_status: str = "review",
    issue_date: str | None = None,
) -> tuple[bytes, dict[str, Any]]:
    bundle = build_sheet_bundle(
        project_name,
        version_number,
        geometry,
        revision_label=revision_label,
        brief_json=brief_json,
        deliverable_preset=deliverable_preset,
        package_status=package_status,
        issue_date=issue_date,
    )
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=PAGE_SIZE)
    pdf.setTitle(f"{project_name} - V{version_number}")
    for sheet in bundle["sheets"]:
        _sheet_svg_to_pdf_page(pdf, sheet["svg"])
        pdf.showPage()
    pdf.save()
    return buffer.getvalue(), bundle


def build_pdf(version_number: int, project_name: str, brief_json: dict, floor_plan_url: str | None) -> str:
    geometry = ensure_geometry_v2(None, brief_json, option_index=0)
    pdf_bytes, _ = build_pdf_bytes(project_name, version_number, geometry, brief_json=brief_json)
    return save_binary("exports/pdf", "pdf", pdf_bytes)


def build_svg_copy(floor_plan_url: str) -> str:
    source = absolute_path(floor_plan_url)
    if source.suffix.lower() == ".svg":
        svg_content = source.read_text(encoding="utf-8")
    else:
        svg_content = _svg_root(
            [
                '<rect width="1200" height="850" fill="#fffdf8"/>',
                '<rect x="48" y="48" width="1104" height="754" fill="#f6efe3" stroke="#1b1a18" stroke-width="3"/>',
                _svg_text(72, 86, "Fallback SVG wrapper", size=22, weight="700"),
                f'<image href="{floor_plan_url}" x="76" y="120" width="1048" height="620" preserveAspectRatio="xMidYMid meet"/>',
            ]
        )
    return save_text("exports/svg", "svg", svg_content)


def export_phase2_package(
    *,
    project_id: str,
    project_name: str,
    version_id: str,
    version_number: int,
    brief_json: dict[str, Any] | None,
    geometry_json: dict[str, Any] | None,
    revision_label: str = "A",
    package_id: str | None = None,
    deliverable_preset: str = "technical_neutral",
    package_status: str = "review",
    issue_date: str | None = None,
) -> dict[str, Any]:
    geometry = ensure_geometry_v2(geometry_json, brief_json, option_index=max(version_number - 1, 0))
    resolved_package_id = package_id or version_id
    resolved_issue_date = _issue_date(issue_date)
    pdf_bytes, bundle = build_pdf_bytes(
        project_name,
        version_number,
        geometry,
        revision_label=revision_label,
        brief_json=brief_json,
        deliverable_preset=deliverable_preset,
        package_status=package_status,
        issue_date=resolved_issue_date,
    )
    export_prefix = f"projects/{project_id}/packages/{resolved_package_id}"

    sheet_files: list[dict[str, Any]] = []
    cover_svg_url = ""
    for sheet in bundle["sheets"]:
        sheet_url = save_text(f"{export_prefix}/sheets", "svg", sheet["svg"])
        if not cover_svg_url and sheet["type"].startswith("floor_plan_"):
            cover_svg_url = sheet_url
        sheet_files.append(
            {
                "name": f"{sheet['number']}.svg",
                "url": sheet_url,
                "type": "svg",
                "sheet_number": sheet["number"],
                "sheet_title": sheet["title"],
                "sheet_type": sheet["type"],
            }
        )

    pdf_url = save_binary(f"{export_prefix}/bundle", "pdf", pdf_bytes)
    if not cover_svg_url and sheet_files:
        cover_svg_url = sheet_files[0]["url"]
    dxf_url = save_binary(f"{export_prefix}/bundle", "dxf", build_dxf_bytes(project_name, version_number, geometry))
    ifc_url = save_binary(f"{export_prefix}/bundle", "ifc", build_ifc_bytes(project_name, version_number, geometry))
    csv_urls = {name: save_text(f"{export_prefix}/csv", "csv", content) for name, content in bundle["csv_payloads"].items()}

    manifest = {
        "manifest_version": bundle["manifest_version"],
        "package_id": resolved_package_id,
        "project_id": project_id,
        "version_id": version_id,
        "version_number": version_number,
        "issue_type": bundle["issue_type"],
        "revision_label": bundle["revision_label"],
        "status": bundle["status"],
        "issue_date": bundle["issue_date"],
        "export_timestamp": bundle["generated_at"],
        "geometry_schema_version": geometry.get("$schema"),
        "export_pipeline_version": bundle["export_pipeline_version"],
        "deliverable_preset": bundle["deliverable_preset"],
        "assumptions": bundle["assumptions"],
        "sheets": [
            {
                "number": sheet["number"],
                "title": sheet["title"],
                "type": sheet["type"],
                "scale": sheet["scale"],
                "files": {
                    "pdf_page": index + 1,
                    "svg": next(item["url"] for item in sheet_files if item["sheet_number"] == sheet["number"]),
                    "png_preview": None,
                },
            }
            for index, sheet in enumerate(bundle["sheets"])
        ],
        "total_sheets": len(bundle["sheets"]),
        "exports": {
            "combined_pdf": pdf_url,
            "dxf": dxf_url,
            "ifc": ifc_url,
            "schedules_csv": {
                "door": csv_urls["door"],
                "window": csv_urls["window"],
                "room": csv_urls["room"],
            },
        },
        "source": {
            "brief_version": 1,
            "geometry_version": geometry.get("$schema"),
            "canonical_version_id": version_id,
            "canonical_locked_at": _utcnow(),
        },
        "disclaimer": DEGRADED_DISCLAIMER if package_status == "degraded_preview" else COVER_DISCLAIMER,
    }
    manifest_url = save_json(f"{export_prefix}/bundle", manifest)

    export_urls = {
        "pdf": pdf_url,
        "svg": cover_svg_url,
        "dxf": dxf_url,
        "ifc": ifc_url,
        "manifest": manifest_url,
        "door_csv": csv_urls["door"],
        "window_csv": csv_urls["window"],
        "room_csv": csv_urls["room"],
    }

    files_manifest = [
        {"name": "package.pdf", "url": pdf_url, "type": "pdf"},
        {"name": "preview.svg", "url": cover_svg_url, "type": "svg"},
        {"name": "package.dxf", "url": dxf_url, "type": "dxf"},
        {"name": "package.ifc", "url": ifc_url, "type": "ifc"},
        {"name": "package-manifest.json", "url": manifest_url, "type": "json"},
        {"name": "door-schedule.csv", "url": csv_urls["door"], "type": "csv"},
        {"name": "window-schedule.csv", "url": csv_urls["window"], "type": "csv"},
        {"name": "room-schedule.csv", "url": csv_urls["room"], "type": "csv"},
        *sheet_files,
    ]
    return {
        "geometry": geometry,
        "export_urls": export_urls,
        "files_manifest": files_manifest,
        "manifest_url": manifest_url,
        "bundle": bundle,
    }
