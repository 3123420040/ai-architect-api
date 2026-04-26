from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import ezdxf
import fitz

from app.services.professional_deliverables.aia_layers import (
    AIA_LAYERS,
    REQUIRED_RECOGNITION_LAYERS,
    validate_aia_layer_table,
    validate_entity_layers,
)
from app.services.professional_deliverables.dwg_converter import ODAConverterError, audit_dwg_directory
from app.services.professional_deliverables.pdf_generator import FONT_NAME, SCALE_1_100_PT_PER_M


@dataclass(frozen=True)
class GateResult:
    name: str
    status: str
    detail: str

    def as_dict(self) -> dict[str, str]:
        return {"name": self.name, "status": self.status, "detail": self.detail}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_dxf_layers(path: Path) -> GateResult:
    doc = ezdxf.readfile(path)
    issues = validate_aia_layer_table(doc)
    layer_names = {layer.dxf.name for layer in doc.layers}
    missing_required = REQUIRED_RECOGNITION_LAYERS - layer_names
    if missing_required:
        issues.append(f"missing required recognition layers: {sorted(missing_required)}")
    issues.extend(validate_entity_layers(doc.modelspace()))
    if issues:
        return GateResult("AIA layer dictionary", "fail", f"{path.name}: " + "; ".join(issues[:12]))
    return GateResult("AIA layer dictionary", "pass", f"{path.name}: {len(AIA_LAYERS)} layers validated")


def validate_all_dxf_layers(paths: list[Path]) -> GateResult:
    failures = [result.detail for result in (validate_dxf_layers(path) for path in paths) if result.status != "pass"]
    if failures:
        return GateResult("AIA layer dictionary", "fail", " | ".join(failures))
    return GateResult("AIA layer dictionary", "pass", f"{len(paths)} DXF sheets match Appendix A exactly")


def _pdf_text(path: Path) -> str:
    with fitz.open(path) as doc:
        return "\n".join(page.get_text("text") for page in doc)


def validate_pdf_diacritics(path: Path) -> GateResult:
    text = _pdf_text(path)
    required = {"ô", "ư", "đ", "ấ"}
    missing = sorted(char for char in required if char not in text)
    replacement_markers = ["\ufffd", "\u25a1", "\u25af", "?"]
    found_replacements = [marker for marker in replacement_markers if marker in text]
    if missing or found_replacements:
        return GateResult(
            "PDF Vietnamese diacritics",
            "fail",
            f"missing={missing}, replacement_markers={found_replacements}",
        )
    return GateResult("PDF Vietnamese diacritics", "pass", "Extracted text contains ô, ư, đ, ấ without replacement markers")


def validate_pdf_font_embedding(path: Path) -> GateResult:
    font_names: set[str] = set()
    with fitz.open(path) as doc:
        for page in doc:
            for font in page.get_fonts(full=True):
                font_names.add(" ".join(str(part) for part in font))
    if not any(FONT_NAME in font for font in font_names):
        return GateResult("PDF font embedding", "fail", f"{FONT_NAME} not found in embedded PDF font list")
    return GateResult("PDF font embedding", "pass", f"{FONT_NAME} embedded/subset in PDF")


def validate_pdf_scale(path: Path, *, tolerance_points: float = 0.75) -> GateResult:
    matches: list[tuple[int, float]] = []
    with fitz.open(path) as doc:
        for page_number, page in enumerate(doc, start=1):
            for drawing in page.get_drawings():
                for item in drawing.get("items", []):
                    if not item or item[0] != "l":
                        continue
                    p1, p2 = item[1], item[2]
                    length = ((p2.x - p1.x) ** 2 + (p2.y - p1.y) ** 2) ** 0.5
                    if abs(length - SCALE_1_100_PT_PER_M) <= tolerance_points:
                        matches.append((page_number, length))
    if not matches:
        return GateResult(
            "PDF scale 1:100",
            "fail",
            f"No 1 m calibration segment found at {SCALE_1_100_PT_PER_M:.2f} pt (1 cm)",
        )
    page, length = matches[0]
    return GateResult("PDF scale 1:100", "pass", f"Page {page}: 1 m segment measures {length:.2f} pt = 1 cm at 1:100")


def validate_pdf_size(path: Path, *, max_bytes: int = 10 * 1024 * 1024) -> GateResult:
    size = path.stat().st_size
    if size > max_bytes:
        return GateResult("PDF size", "fail", f"{path.name} is {size} bytes > {max_bytes}")
    return GateResult("PDF size", "pass", f"{path.name} is {size} bytes")


def validate_dwg_clean_open(dwg_dir: Path, audit_dir: Path, *, require_dwg: bool) -> GateResult:
    dwg_paths = sorted(dwg_dir.glob("*.dwg")) + sorted(dwg_dir.glob("*.DWG"))
    if not dwg_paths:
        if require_dwg:
            return GateResult("DWG clean-open", "fail", "No DWG files were produced")
        return GateResult("DWG clean-open", "skipped", "ODA converter unavailable locally; CI runs the required DWG audit")
    try:
        result = audit_dwg_directory(dwg_dir, audit_dir, require_binary=require_dwg)
    except ODAConverterError as exc:
        status = "fail" if require_dwg else "skipped"
        return GateResult("DWG clean-open", status, str(exc))
    if result is None:
        return GateResult("DWG clean-open", "skipped", "ODA converter unavailable locally; CI runs the required DWG audit")
    if not result.produced_files:
        return GateResult("DWG clean-open", "fail", "ODA audit produced no DXF round-trip output")
    return GateResult("DWG clean-open", "pass", f"ODA audit round-tripped {len(dwg_paths)} DWG files")


def build_file_inventory(paths: list[Path], root: Path) -> list[dict[str, Any]]:
    inventory = []
    for path in sorted(paths):
        if not path.exists() or path.is_dir():
            continue
        inventory.append(
            {
                "path": path.relative_to(root).as_posix(),
                "size_bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    return inventory


def write_gate_outputs(output_dir: Path, gate_results: list[GateResult], inventory: list[dict[str, Any]]) -> tuple[Path, Path]:
    json_path = output_dir / "sprint1_gate_summary.json"
    md_path = output_dir / "sprint1_gate_summary.md"
    if any(result.status == "fail" for result in gate_results):
        overall_status = "fail"
    elif any(result.status == "skipped" for result in gate_results):
        overall_status = "partial"
    else:
        overall_status = "pass"
    payload = {
        "status": overall_status,
        "gates": [result.as_dict() for result in gate_results],
        "file_inventory": inventory,
    }
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    lines = ["# Sprint 1 Gate Summary", "", "| Gate | Status | Detail |", "|---|---|---|"]
    for result in gate_results:
        lines.append(f"| {result.name} | {result.status} | {result.detail.replace('|', '/')} |")
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return json_path, md_path
