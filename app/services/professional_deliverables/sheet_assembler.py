from __future__ import annotations

from app.services.professional_deliverables.drawing_contract import DrawingProject, SheetSpec, validate_project_contract


def assemble_sheet_set(project: DrawingProject) -> tuple[SheetSpec, ...]:
    validate_project_contract(project)
    sheets: list[SheetSpec] = [
        SheetSpec("A-100", "Mặt bằng tổng thể", "A-100-site", "site"),
    ]
    for floor in range(1, project.storeys + 1):
        sheets.append(
            SheetSpec(
                f"A-101-F{floor}",
                f"Mặt bằng tầng {floor}",
                f"A-101-F{floor}-floorplan",
                "floorplan",
                floor=floor,
            )
        )
    sheets.extend(
        [
            SheetSpec("A-201", "Mặt đứng Bắc / Nam / Đông / Tây", "A-201-elevations", "elevations"),
            SheetSpec("A-301", "Mặt cắt ngang và dọc", "A-301-sections", "sections"),
        ]
    )
    return tuple(sheets)

