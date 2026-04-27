from __future__ import annotations

import argparse
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.core.config import settings
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
) -> Sprint1BundleResult:
    if require_dwg is None:
        require_dwg = bool(os.environ.get("CI"))
    sheets = assemble_sheet_set(project)
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
    gate_results = [
        dwg_gate,
        validate_all_dxf_layers(list(dxf_paths)),
        validate_pdf_diacritics(pdf_path),
        validate_pdf_font_embedding(pdf_path),
        validate_pdf_scale(pdf_path),
        validate_pdf_size(pdf_path),
    ]
    if audit_dir.exists():
        shutil.rmtree(audit_dir)
    inventory = build_file_inventory([*dxf_paths, *dwg_paths, pdf_path], project_dir)
    summary_json, summary_md = write_gate_outputs(two_d_dir, gate_results, inventory)
    return Sprint1BundleResult(
        project_dir=project_dir,
        two_d_dir=two_d_dir,
        dxf_paths=dxf_paths,
        dwg_paths=dwg_paths,
        pdf_path=pdf_path,
        gate_results=tuple(gate_results),
        gate_summary_json=summary_json,
        gate_summary_md=summary_md,
    )


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
