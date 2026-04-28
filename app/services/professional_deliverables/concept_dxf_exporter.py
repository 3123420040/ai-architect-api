from __future__ import annotations

from pathlib import Path

from app.services.design_intelligence.drawing_package_model import compile_drawing_package
from app.services.design_intelligence.concept_model import ArchitecturalConceptModel
from app.services.professional_deliverables.concept_pdf_generator import _concept_sheet_specs, concept_model_to_drawing_project
from app.services.professional_deliverables.dxf_exporter import write_dxf_sheets


def write_concept_dxf_package(concept_model: ArchitecturalConceptModel, output_dir: Path) -> tuple[Path, ...]:
    project = concept_model_to_drawing_project(concept_model)
    sheets = _concept_sheet_specs(compile_drawing_package(concept_model))
    return tuple(write_dxf_sheets(project, sheets, output_dir))
