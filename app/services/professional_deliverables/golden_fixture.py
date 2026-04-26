from __future__ import annotations

from datetime import date

from app.services.professional_deliverables.drawing_contract import (
    DrawingProject,
    Fixture,
    Opening,
    Room,
    WallSegment,
)


def _rect(x1: float, y1: float, x2: float, y2: float) -> tuple[tuple[float, float], ...]:
    return ((x1, y1), (x2, y1), (x2, y2), (x1, y2))


def _floor_walls(floor: int) -> tuple[WallSegment, ...]:
    return (
        WallSegment(floor, (0, 0), (5, 0)),
        WallSegment(floor, (5, 0), (5, 15)),
        WallSegment(floor, (5, 15), (0, 15)),
        WallSegment(floor, (0, 15), (0, 0)),
        WallSegment(floor, (0, 4), (5, 4)),
        WallSegment(floor, (0, 8), (5, 8)),
        WallSegment(floor, (2.2, 8), (2.2, 11)),
        WallSegment(floor, (0, 11), (5, 11)),
    )


def build_golden_townhouse(issue_date: date | None = None) -> DrawingProject:
    rooms = (
        Room("F1-LIVING", 1, "Phòng khách", _rect(0.2, 0.2, 4.8, 3.8)),
        Room("F1-KITCHEN", 1, "Bếp và ăn", _rect(0.2, 4.2, 4.8, 7.8)),
        Room("F1-STAIR", 1, "Cầu thang", _rect(0.2, 8.2, 2.0, 10.8)),
        Room("F1-WC", 1, "Vệ sinh", _rect(2.4, 8.2, 4.8, 10.8)),
        Room("F1-YARD", 1, "Sân sau", _rect(0.2, 11.2, 4.8, 14.8)),
        Room("F2-BED-1", 2, "Phòng ngủ chính", _rect(0.2, 0.2, 4.8, 4.8)),
        Room("F2-BED-2", 2, "Phòng ngủ 2", _rect(0.2, 5.2, 4.8, 8.8)),
        Room("F2-STAIR", 2, "Sảnh thang", _rect(0.2, 9.2, 2.0, 11.2)),
        Room("F2-WC", 2, "Vệ sinh", _rect(2.4, 9.2, 4.8, 11.2)),
        Room("F2-BALCONY", 2, "Ban công", _rect(0.2, 11.6, 4.8, 14.8)),
    )
    openings = (
        Opening(1, "door", (2.0, 0), (3.0, 0), "D01"),
        Opening(1, "door", (1.0, 4), (2.0, 4), "D02"),
        Opening(1, "door", (2.8, 8), (3.7, 8), "D03"),
        Opening(1, "window", (0, 2.0), (0, 3.2), "W01"),
        Opening(1, "window", (5, 5.4), (5, 6.8), "W02"),
        Opening(1, "window", (1.6, 15), (3.4, 15), "W03"),
        Opening(2, "door", (2.0, 0), (3.0, 0), "D11"),
        Opening(2, "door", (1.2, 5.2), (2.2, 5.2), "D12"),
        Opening(2, "door", (2.8, 9.2), (3.7, 9.2), "D13"),
        Opening(2, "window", (0, 2.0), (0, 3.4), "W11"),
        Opening(2, "window", (5, 6.0), (5, 7.6), "W12"),
        Opening(2, "window", (1.2, 15), (3.8, 15), "W13"),
    )
    fixtures = (
        Fixture(1, "furniture", (2.5, 2.0), (1.8, 0.8), "Sofa"),
        Fixture(1, "plumbing", (3.8, 9.4), (0.8, 0.7), "Lavabo"),
        Fixture(1, "light", (2.5, 2.0), (0.35, 0.35), "Đèn"),
        Fixture(1, "plant", (0.6, 13.8), (0.6, 0.6), "Cây"),
        Fixture(2, "furniture", (2.5, 2.3), (2.0, 1.6), "Giường"),
        Fixture(2, "plumbing", (3.8, 10.1), (0.8, 0.7), "Lavabo"),
        Fixture(2, "light", (2.5, 6.8), (0.35, 0.35), "Đèn"),
        Fixture(2, "plant", (4.2, 13.5), (0.6, 0.6), "Cây"),
    )
    return DrawingProject(
        project_id="golden-townhouse",
        project_name="Nhà phố Tropical VN",
        lot_width_m=5.0,
        lot_depth_m=15.0,
        storeys=2,
        style="Tropical VN",
        issue_date=issue_date or date.today(),
        rooms=rooms,
        walls=_floor_walls(1) + _floor_walls(2),
        openings=openings,
        fixtures=fixtures,
        roof_outline=_rect(0, 0, 5, 15),
    )

