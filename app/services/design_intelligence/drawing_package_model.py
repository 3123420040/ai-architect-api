from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.services.design_intelligence.concept_model import ArchitecturalConceptModel


@dataclass(frozen=True)
class DrawingDimension:
    label: str
    value_m: float
    source_geometry: str


@dataclass(frozen=True)
class DrawingSchedule:
    schedule_type: str
    rows: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class DrawingSheetModel:
    number: str
    title: str
    kind: str
    scale: str = "1:100"
    dimensions: tuple[DrawingDimension, ...] = field(default_factory=tuple)
    labels: tuple[str, ...] = field(default_factory=tuple)
    schedules: tuple[DrawingSchedule, ...] = field(default_factory=tuple)
    assumption_notes: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class DrawingPackageModel:
    project_id: str
    concept_status_note: str
    sheets: tuple[DrawingSheetModel, ...]
    line_weight_profile: str
    layer_profile: str
    qa_bounds: dict[str, Any]
    source_model_version: str = "architectural-concept-model-v1"

    def sheets_by_kind(self, kind: str) -> tuple[DrawingSheetModel, ...]:
        return tuple(sheet for sheet in self.sheets if sheet.kind == kind)


def compile_drawing_package(concept_model: ArchitecturalConceptModel) -> DrawingPackageModel:
    width = float(concept_model.site.width_m.value)
    depth = float(concept_model.site.depth_m.value)
    site_dimensions = (
        DrawingDimension("lot_width", width, "concept_model.site.width_m"),
        DrawingDimension("lot_depth", depth, "concept_model.site.depth_m"),
    )
    room_rows = tuple(
        {
            "room_id": room.id,
            "level_id": room.level_id,
            "label_vi": room.label_vi,
            "room_type": room.room_type,
            "area_m2": room.area_m2.value,
        }
        for room in concept_model.rooms
    )
    opening_rows = tuple(
        {
            "opening_id": opening.id,
            "level_id": opening.level_id,
            "type": opening.opening_type,
            "width_m": opening.width_m.value,
            "height_m": opening.height_m.value,
            "wall_id": opening.wall_id,
        }
        for opening in concept_model.openings
    )
    assumption_notes = tuple(decision.customer_visible_explanation for decision in concept_model.assumptions)
    room_labels = tuple(room.label_vi for room in concept_model.rooms)
    sheets: list[DrawingSheetModel] = [
        DrawingSheetModel(
            number="A-000",
            title="Bìa, mục lục và giả định",
            kind="cover_index",
            labels=("Professional Concept 2D Package", concept_model.concept_status_note),
            assumption_notes=assumption_notes,
        ),
        DrawingSheetModel(
            number="A-100",
            title="Mặt bằng tổng thể",
            kind="site",
            dimensions=site_dimensions,
            labels=("Ranh đất",),
            assumption_notes=assumption_notes,
        ),
    ]
    for level in concept_model.levels:
        level_rooms = tuple(room for room in concept_model.rooms if room.level_id == level.id)
        sheets.append(
            DrawingSheetModel(
                number=f"A-101-F{level.floor_number}",
                title=f"Mặt bằng tầng {level.floor_number}",
                kind="floorplan",
                dimensions=site_dimensions,
                labels=tuple(room.label_vi for room in level_rooms),
                assumption_notes=assumption_notes,
            )
        )
    sheets.extend(
        [
            DrawingSheetModel("A-201", "Mặt đứng concept", "elevations", labels=(str(concept_model.style.value) if concept_model.style else "style_pending",), assumption_notes=assumption_notes),
            DrawingSheetModel("A-301", "Mặt cắt concept", "sections", labels=tuple(section.label for section in concept_model.section_lines), assumption_notes=assumption_notes),
            DrawingSheetModel(
                "A-601",
                "Bảng phòng và diện tích",
                "room_area_schedule",
                labels=room_labels,
                schedules=(DrawingSchedule("room_area", room_rows),),
                assumption_notes=assumption_notes,
            ),
            DrawingSheetModel(
                "A-602",
                "Bảng cửa đi và cửa sổ",
                "door_window_schedule",
                labels=tuple(row["opening_id"] for row in opening_rows),
                schedules=(DrawingSchedule("door_window", opening_rows),),
                assumption_notes=assumption_notes,
            ),
            DrawingSheetModel(
                "A-603",
                "Giả định và ghi chú style",
                "assumptions_style_notes",
                labels=(str(concept_model.style.value) if concept_model.style else "style_pending",),
                schedules=(),
                assumption_notes=assumption_notes,
            ),
        ]
    )
    return DrawingPackageModel(
        project_id=concept_model.project_id,
        concept_status_note=concept_model.concept_status_note,
        sheets=tuple(sheets),
        line_weight_profile="AIA concept subset",
        layer_profile="AIA CAD layer subset",
        qa_bounds={"lot_width_m": width, "lot_depth_m": depth, "floor_count": len(concept_model.levels)},
    )
