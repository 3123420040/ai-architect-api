from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.services.design_intelligence.concept_model import ArchitecturalConceptModel
from app.services.professional_deliverables.style_knowledge import StyleKnowledgeBase, StyleKnowledgeError


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
    style_notes: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class DrawingPackageModel:
    project_id: str
    concept_status_note: str
    sheets: tuple[DrawingSheetModel, ...]
    line_weight_profile: str
    layer_profile: str
    qa_bounds: dict[str, Any]
    source_model_version: str = "architectural-concept-model-v1"
    style_provenance: dict[str, Any] = field(default_factory=dict)

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
            "width_m": _room_extent(room.polygon.value)[0],
            "depth_m": _room_extent(room.polygon.value)[1],
            "area_m2": room.area_m2.value,
        }
        for room in concept_model.rooms
    )
    opening_rows = tuple(
        {
            "opening_id": opening.id,
            "level_id": opening.level_id,
            "type": opening.opening_type,
            "type_vi": "Cửa sổ" if opening.opening_type == "window" else "Cửa đi",
            "width_m": opening.width_m.value,
            "height_m": opening.height_m.value,
            "wall_id": opening.wall_id,
            "operation": _operation_note(opening.operation.value if opening.operation else None),
        }
        for opening in concept_model.openings
    )
    assumption_notes = tuple(decision.customer_visible_explanation for decision in concept_model.assumptions)
    style_notes = _style_notes(concept_model)
    room_labels = tuple(room.label_vi for room in concept_model.rooms)
    sheets: list[DrawingSheetModel] = [
        DrawingSheetModel(
            number="A-000",
            title="Bìa, mục lục và giả định",
            kind="cover_index",
            labels=("Professional Concept 2D Package", concept_model.concept_status_note),
            assumption_notes=assumption_notes,
            style_notes=style_notes,
        ),
        DrawingSheetModel(
            number="A-100",
            title="Mặt bằng tổng thể",
            kind="site",
            dimensions=site_dimensions,
            labels=("Ranh đất",),
            assumption_notes=assumption_notes,
            style_notes=style_notes,
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
                style_notes=style_notes,
            )
        )
    sheets.extend(
        [
            DrawingSheetModel("A-201", "Mặt đứng concept", "elevations", labels=(str(concept_model.style.value) if concept_model.style else "style_pending",), assumption_notes=assumption_notes, style_notes=style_notes),
            DrawingSheetModel("A-301", "Mặt cắt concept", "sections", labels=tuple(section.label for section in concept_model.section_lines), assumption_notes=assumption_notes, style_notes=style_notes),
            DrawingSheetModel(
                "A-601",
                "Bảng phòng và diện tích",
                "room_area_schedule",
                labels=room_labels,
                schedules=(DrawingSchedule("room_area", room_rows),),
                assumption_notes=assumption_notes,
                style_notes=style_notes,
            ),
            DrawingSheetModel(
                "A-602",
                "Bảng cửa đi và cửa sổ",
                "door_window_schedule",
                labels=tuple(row["opening_id"] for row in opening_rows),
                schedules=(DrawingSchedule("door_window", opening_rows),),
                assumption_notes=assumption_notes,
                style_notes=style_notes,
            ),
            DrawingSheetModel(
                "A-901",
                "Giả định và ghi chú style",
                "assumptions_style_notes",
                labels=(str(concept_model.style.value) if concept_model.style else "style_pending", *style_notes[:3]),
                schedules=(DrawingSchedule("assumptions", tuple({"note": note} for note in assumption_notes)),),
                assumption_notes=assumption_notes,
                style_notes=style_notes,
            ),
        ]
    )
    return DrawingPackageModel(
        project_id=concept_model.project_id,
        concept_status_note=concept_model.concept_status_note,
        sheets=tuple(sheets),
        line_weight_profile="AIA concept subset",
        layer_profile="AIA CAD layer subset",
        qa_bounds={
            "lot_width_m": width,
            "lot_depth_m": depth,
            "floor_count": len(concept_model.levels),
            "sheet_count": len(sheets),
            "room_count": len(concept_model.rooms),
            "opening_count": len(concept_model.openings),
        },
        style_provenance=_style_provenance(concept_model),
    )


def _style_notes(concept_model: ArchitecturalConceptModel) -> tuple[str, ...]:
    live_notes = _live_style_notes(concept_model)
    style_id = str(concept_model.style.value) if concept_model.style else ""
    if not style_id:
        return live_notes
    try:
        profile = StyleKnowledgeBase.load_default().get(style_id)
    except StyleKnowledgeError:
        return live_notes
    metadata_notes = _metadata_style_notes(concept_model)
    facade_notes = tuple(note.customer_visible_explanation for note in concept_model.facade.material_notes) if concept_model.facade else ()
    expression = profile.facade_expression
    expression_notes = (
        f"Nguồn style_profile:{profile.style_id} - nhịp mặt đứng: {expression.get('rhythm')}",
        f"Nguồn style_profile:{profile.style_id} - ngôn ngữ cửa mở: {expression.get('opening_language')}",
    )
    material_notes = tuple(f"Nguồn style_profile:{profile.style_id} - {note}" for note in profile.material_assumptions)
    return tuple(dict.fromkeys((*live_notes, *metadata_notes, *profile.drawing_notes, *facade_notes, *expression_notes, *material_notes)))


def _live_style_notes(concept_model: ArchitecturalConceptModel) -> tuple[str, ...]:
    metadata = concept_model.metadata.get("style_metadata") if isinstance(concept_model.metadata, dict) else None
    if not isinstance(metadata, dict):
        return ()
    notes = metadata.get("style_notes") or metadata.get("drawing_notes") or ()
    if isinstance(notes, str):
        return (notes,) if notes.strip() else ()
    if isinstance(notes, (list, tuple)):
        return tuple(str(note) for note in notes if str(note).strip())
    return ()


def _metadata_style_notes(concept_model: ArchitecturalConceptModel) -> tuple[str, ...]:
    metadata = concept_model.metadata.get("style_metadata") if isinstance(concept_model.metadata, dict) else None
    if not isinstance(metadata, dict):
        return ()
    notes: list[str] = []
    for item in tuple(metadata.get("suppressed_style_features") or ()):
        if isinstance(item, dict):
            note = item.get("drawing_note") or item.get("note")
            if note:
                notes.append(f"Nguồn explicit_dislike - {note}")
    for item in tuple(metadata.get("reference_style_hints") or ()):
        if isinstance(item, dict):
            note = item.get("drawing_note") or item.get("material_note")
            if note:
                notes.append(f"Nguồn reference_image_descriptor - {note}")
    return tuple(notes)


def _style_provenance(concept_model: ArchitecturalConceptModel) -> dict[str, Any]:
    metadata = concept_model.metadata.get("style_metadata") if isinstance(concept_model.metadata, dict) else None
    if isinstance(metadata, dict) and isinstance(metadata.get("style_provenance"), dict):
        return dict(metadata["style_provenance"])
    if concept_model.style:
        return {"style_id": concept_model.style.as_dict()}
    return {}


def _operation_note(value: Any) -> str:
    if value is None:
        return "concept"
    if isinstance(value, dict):
        operation_type = str(value.get("type") or value.get("operation") or value.get("mode") or "").strip()
        hinge_side = str(value.get("hinge_side") or value.get("swing") or "").strip()
        parts: list[str] = []
        if operation_type == "sliding" or value.get("sliding"):
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
    text = str(value).strip()
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


def _room_extent(points: tuple[tuple[float, float], ...]) -> tuple[float, float]:
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return round(max(xs) - min(xs), 2), round(max(ys) - min(ys), 2)
