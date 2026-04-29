from __future__ import annotations

import argparse
import json
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.services.professional_deliverables.artifact_quality_report import (
    build_2d_artifact_readiness,
    write_artifact_quality_report,
)
from app.services.professional_deliverables.drawing_quality_gates import (
    validate_dxf_dimensions_match,
    validate_dxf_no_stale_golden_labels,
    validate_dxf_no_raw_internal_strings,
    validate_dxf_openable,
    validate_dxf_project_extents_match,
    validate_dxf_required_layers,
    validate_dxf_room_dimensions,
    validate_dxf_room_labels_openings,
    validate_dxf_units_meters,
    validate_pdf_dimension_chains,
    validate_pdf_dynamic_dimensions,
    validate_pdf_elevation_layout,
    validate_pdf_elevation_visual_density,
    validate_pdf_floor_count,
    validate_pdf_no_raw_internal_strings,
    validate_pdf_no_stale_golden_labels,
    validate_pdf_no_title_overlap,
    validate_pdf_page_count,
    validate_pdf_page_render_nonblank,
    validate_pdf_room_dimension_labels,
    validate_pdf_room_labels_areas,
    validate_pdf_section_height_labels,
    validate_pdf_site_boundary_match,
    validate_pdf_style_material_notes,
)
from app.services.professional_deliverables.drawing_contract import DrawingProject
from app.services.professional_deliverables.dwg_converter import ODAConverterError, convert_dxf_directory_to_dwg
from app.services.professional_deliverables.dxf_exporter import write_dxf_sheets
from app.services.professional_deliverables.golden_fixture import build_golden_townhouse
from app.services.professional_deliverables.pdf_generator import write_pdf_bundle
from app.services.professional_deliverables.sheet_assembler import assemble_sheet_set
from app.services.professional_deliverables.validators import (
    GateResult,
    build_file_inventory,
    validate_all_dxf_layers,
    validate_dwg_clean_open,
    validate_pdf_diacritics,
    validate_pdf_font_embedding,
    validate_pdf_scale,
    validate_pdf_size,
    write_gate_outputs,
)


@dataclass(frozen=True)
class Sprint1BundleResult:
    project_dir: Path
    two_d_dir: Path
    dxf_paths: tuple[Path, ...]
    dwg_paths: tuple[Path, ...]
    pdf_path: Path
    gate_results: tuple[GateResult, ...]
    gate_summary_json: Path
    gate_summary_md: Path
    artifact_quality_report_json: Path | None = None
    artifact_quality_report_md: Path | None = None

    @property
    def passed(self) -> bool:
        return all(result.status in {"pass", "skipped"} for result in self.gate_results)

    def as_dict(self) -> dict[str, Any]:
        return {
            "project_dir": str(self.project_dir),
            "two_d_dir": str(self.two_d_dir),
            "dxf_paths": [str(path) for path in self.dxf_paths],
            "dwg_paths": [str(path) for path in self.dwg_paths],
            "pdf_path": str(self.pdf_path),
            "passed": self.passed,
            "gates": [result.as_dict() for result in self.gate_results],
            "gate_summary_json": str(self.gate_summary_json),
            "gate_summary_md": str(self.gate_summary_md),
            "artifact_quality_report_json": str(self.artifact_quality_report_json) if self.artifact_quality_report_json else None,
            "artifact_quality_report_md": str(self.artifact_quality_report_md) if self.artifact_quality_report_md else None,
        }


def _copy_dwg_outputs(temp_dir: Path, two_d_dir: Path, stems: set[str]) -> tuple[Path, ...]:
    copied: list[Path] = []
    for source in sorted(temp_dir.glob("*.dwg")) + sorted(temp_dir.glob("*.DWG")):
        stem = source.stem
        if stem not in stems:
            continue
        target = two_d_dir / f"{stem}.dwg"
        shutil.copy2(source, target)
        copied.append(target)
    return tuple(copied)


def generate_project_2d_bundle(
    project: DrawingProject,
    output_root: Path,
    *,
    require_dwg: bool | None = None,
    project_dir: Path | None = None,
    sheets: tuple | None = None,
    concept_package_metadata: dict[str, Any] | None = None,
    concept_fallback_reason: str | None = None,
) -> Sprint1BundleResult:
    if require_dwg is None:
        require_dwg = bool(os.environ.get("CI"))
    sheets = sheets or assemble_sheet_set(project)
    project_dir = project_dir or (output_root / f"project-{project.project_id}")
    two_d_dir = project_dir / "2d"
    if two_d_dir.exists():
        shutil.rmtree(two_d_dir)
    two_d_dir.mkdir(parents=True, exist_ok=True)

    dxf_paths = tuple(write_dxf_sheets(project, sheets, two_d_dir))
    expected_stems = {sheet.filename_stem for sheet in sheets}

    dwg_paths: tuple[Path, ...] = ()
    dwg_gate_override: GateResult | None = None
    with tempfile.TemporaryDirectory(prefix="oda-dxf-") as temp_input_name, tempfile.TemporaryDirectory(prefix="oda-dwg-") as temp_name:
        temp_input_dir = Path(temp_input_name)
        for path in dxf_paths:
            shutil.copy2(path, temp_input_dir / f"{path.stem}.DXF")
        temp_dir = Path(temp_name)
        try:
            conversion = convert_dxf_directory_to_dwg(temp_input_dir, temp_dir, require_binary=require_dwg)
        except ODAConverterError as exc:
            if require_dwg:
                detail = " | ".join(line for line in str(exc).splitlines() if line.strip())
                dwg_gate_override = GateResult("DWG clean-open", "fail", detail[:700])
            conversion = None
        if conversion:
            dwg_paths = _copy_dwg_outputs(temp_dir, two_d_dir, expected_stems)

    pdf_path = write_pdf_bundle(project, sheets, two_d_dir / "bundle.pdf")

    audit_dir = two_d_dir / ".audit-dxf"
    dwg_gate = dwg_gate_override or validate_dwg_clean_open(two_d_dir, audit_dir, require_dwg=require_dwg)
    site_dxf_path = next((path for path in dxf_paths if path.name.startswith("A-100")), dxf_paths[0])
    gate_results = [
        dwg_gate,
        validate_all_dxf_layers(list(dxf_paths)),
        validate_pdf_diacritics(pdf_path),
        validate_pdf_font_embedding(pdf_path),
        validate_pdf_scale(pdf_path),
        validate_pdf_size(pdf_path),
        validate_pdf_page_count(pdf_path, len(sheets)),
        validate_pdf_dynamic_dimensions(pdf_path, project),
        validate_pdf_no_stale_golden_labels(pdf_path, project),
        validate_pdf_site_boundary_match(project),
        validate_pdf_floor_count(pdf_path, project),
        validate_pdf_room_labels_areas(pdf_path, project),
        validate_pdf_dimension_chains(pdf_path, project),
        validate_pdf_no_title_overlap(project),
        validate_pdf_page_render_nonblank(pdf_path),
        validate_pdf_elevation_layout(project),
        validate_dxf_openable(site_dxf_path),
        validate_dxf_units_meters(site_dxf_path),
        validate_dxf_required_layers(site_dxf_path),
        validate_dxf_project_extents_match(site_dxf_path, project),
        validate_dxf_dimensions_match(site_dxf_path, project),
        validate_dxf_room_labels_openings(dxf_paths, project),
        validate_dxf_no_stale_golden_labels(dxf_paths, project),
    ]
    if concept_package_metadata is not None:
        gate_results.extend(
            [
                validate_pdf_room_dimension_labels(pdf_path, project),
                validate_pdf_no_raw_internal_strings(pdf_path),
                validate_pdf_section_height_labels(pdf_path),
                validate_pdf_style_material_notes(pdf_path),
                validate_pdf_elevation_visual_density(pdf_path),
                validate_dxf_room_dimensions(dxf_paths, project),
                validate_dxf_no_raw_internal_strings(dxf_paths),
            ]
        )
    if audit_dir.exists():
        shutil.rmtree(audit_dir)
    readiness = build_2d_artifact_readiness(
        pdf_path=pdf_path,
        dxf_paths=dxf_paths,
        dwg_paths=dwg_paths,
        gate_results=tuple(gate_results),
        dwg_skip_reason=dwg_gate.detail if dwg_gate.status == "skipped" else None,
    )
    artifact_quality_report_json, artifact_quality_report_md = write_artifact_quality_report(
        output_dir=two_d_dir,
        project_id=project.project_id,
        version_id=project.version_id,
        bundle_id=None,
        readiness=readiness,
        root=project_dir,
        concept_package=concept_package_metadata,
        fallback_reason=concept_fallback_reason,
    )
    inventory = build_file_inventory([*dxf_paths, *dwg_paths, pdf_path, artifact_quality_report_json, artifact_quality_report_md], project_dir)
    summary_json, summary_md = write_gate_outputs(two_d_dir, gate_results, inventory)
    if concept_package_metadata is not None or concept_fallback_reason:
        _annotate_gate_summary(
            summary_json,
            summary_md,
            concept_package_metadata=concept_package_metadata,
            concept_fallback_reason=concept_fallback_reason,
        )
    return Sprint1BundleResult(
        project_dir=project_dir,
        two_d_dir=two_d_dir,
        dxf_paths=dxf_paths,
        dwg_paths=dwg_paths,
        pdf_path=pdf_path,
        gate_results=tuple(gate_results),
        gate_summary_json=summary_json,
        gate_summary_md=summary_md,
        artifact_quality_report_json=artifact_quality_report_json,
        artifact_quality_report_md=artifact_quality_report_md,
    )


def _annotate_gate_summary(
    summary_json: Path,
    summary_md: Path,
    *,
    concept_package_metadata: dict[str, Any] | None,
    concept_fallback_reason: str | None,
) -> None:
    concept_package = concept_package_metadata or {
        "enabled": False,
        "readiness": "fallback",
        "fallback_reason": concept_fallback_reason,
    }
    payload = json.loads(summary_json.read_text(encoding="utf-8"))
    payload["concept_package"] = concept_package
    summary_json.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    lines = summary_md.read_text(encoding="utf-8").rstrip().splitlines()
    lines.extend(
        [
            "",
            "## Concept Package",
            "",
            f"- Enabled: `{str(concept_package.get('enabled', False)).lower()}`",
            f"- Readiness: `{concept_package.get('readiness', 'unknown')}`",
        ]
    )
    if concept_package.get("fallback_reason"):
        lines.append(f"- Fallback reason: `{concept_package['fallback_reason']}`")
    summary_md.write_text("\n".join(lines) + "\n", encoding="utf-8")


def generate_golden_bundle(output_root: Path | None = None, *, require_dwg: bool | None = None) -> Sprint1BundleResult:
    if require_dwg is None:
        require_dwg = bool(os.environ.get("CI"))
    output_root = output_root or (settings.storage_dir / "professional-deliverables")
    project = build_golden_townhouse()
    return generate_project_2d_bundle(project, output_root, require_dwg=require_dwg)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate the Sprint 1 golden 2D deliverable bundle.")
    parser.add_argument("--output-root", type=Path, default=settings.storage_dir / "professional-deliverables")
    parser.add_argument("--require-dwg", action="store_true", help="Fail if ODA cannot produce/audit DWG files.")
    parser.add_argument("--allow-missing-dwg", action="store_true", help="Allow local DXF/PDF generation without ODA.")
    args = parser.parse_args()
    if args.require_dwg and args.allow_missing_dwg:
        parser.error("--require-dwg and --allow-missing-dwg are mutually exclusive")
    require_dwg = True if args.require_dwg else False if args.allow_missing_dwg else None
    result = generate_golden_bundle(args.output_root, require_dwg=require_dwg)
    print(f"Sprint 1 golden bundle: {result.project_dir}")
    print(f"2D output: {result.two_d_dir}")
    for gate in result.gate_results:
        print(f"{gate.status.upper():7} {gate.name}: {gate.detail}")
    if not result.passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
