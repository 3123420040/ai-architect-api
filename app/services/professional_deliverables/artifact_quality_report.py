from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.services.professional_deliverables.validators import GateResult, sha256_file


@dataclass(frozen=True)
class ArtifactReadiness:
    artifact_role: str
    path: Path | None
    state: str
    exists: bool
    format_valid: bool
    semantic_valid: bool
    visual_qa: bool
    customer_ready: bool
    gates: tuple[str, ...]
    user_message: str
    technical_detail: str = ""

    def as_dict(self, root: Path) -> dict[str, Any]:
        relative_path = self.path.relative_to(root).as_posix() if self.path and self.path.exists() else None
        return {
            "artifact_role": self.artifact_role,
            "path": relative_path,
            "state": self.state,
            "exists": self.exists,
            "format_valid": self.format_valid,
            "semantic_valid": self.semantic_valid,
            "visual_qa": self.visual_qa,
            "customer_ready": self.customer_ready,
            "byte_size": self.path.stat().st_size if self.path and self.path.exists() else 0,
            "sha256": sha256_file(self.path) if self.path and self.path.exists() else None,
            "gates": list(self.gates),
            "user_message": self.user_message,
            "technical_detail": self.technical_detail,
        }


def _status_by_gate(gates: list[GateResult]) -> dict[str, str]:
    return {gate.name: gate.status for gate in gates}


def build_2d_artifact_readiness(
    *,
    pdf_path: Path,
    dxf_paths: tuple[Path, ...],
    dwg_paths: tuple[Path, ...],
    gate_results: tuple[GateResult, ...],
    dwg_skip_reason: str | None,
) -> tuple[ArtifactReadiness, ...]:
    statuses = _status_by_gate(list(gate_results))
    pdf_gate_names = (
        "PDF_PAGE_COUNT",
        "PDF_DYNAMIC_DIMENSIONS",
        "PDF_SITE_BOUNDARY_MATCH",
        "PDF_FLOOR_COUNT",
        "PDF_ROOM_LABELS_AREAS",
        "PDF_DIMENSION_CHAINS",
        "PDF_NO_TITLE_OVERLAP",
        "PDF_PAGE_RENDER_NONBLANK",
        "PDF_ELEVATION_LAYOUT",
        "PDF_NO_STALE_GOLDEN_LABELS",
    )
    dxf_gate_names = (
        "DXF_OPENABLE",
        "DXF_UNITS_METERS",
        "DXF_REQUIRED_LAYERS",
        "DXF_PROJECT_EXTENTS_MATCH",
        "DXF_DIMENSIONS_MATCH",
        "DXF_ROOM_LABELS_OPENINGS",
        "DXF_NO_STALE_GOLDEN_LABELS",
    )

    pdf_ready = pdf_path.exists() and all(statuses.get(name) == "pass" for name in pdf_gate_names if name in statuses)
    dxf_ready = bool(dxf_paths) and all(path.exists() for path in dxf_paths) and all(
        statuses.get(name) == "pass" for name in dxf_gate_names if name in statuses
    )
    dwg_ready = bool(dwg_paths) and all(path.exists() for path in dwg_paths)
    dwg_skipped = not dwg_paths and bool(dwg_skip_reason)

    return (
        ArtifactReadiness(
            artifact_role="pdf",
            path=pdf_path,
            state="ready" if pdf_ready else "failed",
            exists=pdf_path.exists(),
            format_valid=statuses.get("PDF_PAGE_COUNT") == "pass",
            semantic_valid=all(statuses.get(name) == "pass" for name in ("PDF_DYNAMIC_DIMENSIONS", "PDF_SITE_BOUNDARY_MATCH", "PDF_ROOM_LABELS_AREAS", "PDF_DIMENSION_CHAINS", "PDF_NO_STALE_GOLDEN_LABELS") if name in statuses),
            visual_qa=all(statuses.get(name) == "pass" for name in ("PDF_NO_TITLE_OVERLAP", "PDF_PAGE_RENDER_NONBLANK", "PDF_ELEVATION_LAYOUT") if name in statuses),
            customer_ready=pdf_ready,
            gates=pdf_gate_names,
            user_message="PDF drawing bundle is ready for concept review." if pdf_ready else "PDF drawing bundle failed one or more quality gates.",
        ),
        ArtifactReadiness(
            artifact_role="dxf",
            path=dxf_paths[0] if dxf_paths else None,
            state="ready" if dxf_ready else "failed",
            exists=bool(dxf_paths) and all(path.exists() for path in dxf_paths),
            format_valid=statuses.get("DXF_OPENABLE") == "pass" and statuses.get("DXF_UNITS_METERS") == "pass",
            semantic_valid=all(statuses.get(name) == "pass" for name in ("DXF_PROJECT_EXTENTS_MATCH", "DXF_DIMENSIONS_MATCH", "DXF_ROOM_LABELS_OPENINGS", "DXF_NO_STALE_GOLDEN_LABELS") if name in statuses),
            visual_qa=dxf_ready,
            customer_ready=dxf_ready,
            gates=dxf_gate_names,
            user_message="DXF sheets are ready for CAD review." if dxf_ready else "DXF sheets failed one or more quality gates.",
            technical_detail=f"{len(dxf_paths)} DXF sheet(s)",
        ),
        ArtifactReadiness(
            artifact_role="dwg",
            path=dwg_paths[0] if dwg_paths else None,
            state="ready" if dwg_ready else "skipped" if dwg_skipped else "failed",
            exists=dwg_ready,
            format_valid=dwg_ready,
            semantic_valid=dwg_ready,
            visual_qa=dwg_ready,
            customer_ready=dwg_ready,
            gates=("DWG clean-open",),
            user_message="DWG conversion is ready." if dwg_ready else dwg_skip_reason or "DWG conversion failed.",
            technical_detail=dwg_skip_reason or "",
        ),
    )


def write_artifact_quality_report(
    *,
    output_dir: Path,
    project_id: str,
    version_id: str | None,
    bundle_id: str | None,
    readiness: tuple[ArtifactReadiness, ...],
    root: Path,
) -> tuple[Path, Path]:
    json_path = output_dir / "artifact_quality_report.json"
    md_path = output_dir / "artifact_quality_report.md"
    payload = {
        "project_id": project_id,
        "version_id": version_id,
        "bundle_id": bundle_id,
        "artifacts": [item.as_dict(root) for item in readiness],
    }
    json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    lines = [
        "# Artifact Quality Report",
        "",
        f"- Project: `{project_id}`",
        f"- Version: `{version_id or 'unknown'}`",
        "",
        "| Artifact | State | Customer ready | Message |",
        "|---|---|---:|---|",
    ]
    for item in readiness:
        lines.append(f"| {item.artifact_role} | {item.state} | {str(item.customer_ready).lower()} | {item.user_message.replace('|', '/')} |")
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return json_path, md_path

