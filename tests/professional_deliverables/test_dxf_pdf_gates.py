from __future__ import annotations

import json

from app.services.professional_deliverables.demo import generate_golden_bundle
from app.services.professional_deliverables.validators import (
    validate_all_dxf_layers,
    validate_pdf_diacritics,
    validate_pdf_font_embedding,
    validate_pdf_scale,
    validate_pdf_size,
)


def test_golden_bundle_writes_canonical_2d_layout_and_passes_local_gates(tmp_path):
    result = generate_golden_bundle(tmp_path, require_dwg=False)

    assert result.two_d_dir == tmp_path / "project-golden-townhouse" / "2d"
    assert [path.name for path in result.dxf_paths] == [
        "A-100-site.dxf",
        "A-101-F1-floorplan.dxf",
        "A-101-F2-floorplan.dxf",
        "A-201-elevations.dxf",
        "A-301-sections.dxf",
    ]
    assert result.pdf_path.name == "bundle.pdf"
    assert result.pdf_path.read_bytes().startswith(b"%PDF")
    assert result.gate_summary_json.exists()
    assert result.gate_summary_md.exists()

    payload = json.loads(result.gate_summary_json.read_text(encoding="utf-8"))
    assert payload["status"] in {"pass", "partial"}
    assert any(item["path"] == "2d/bundle.pdf" for item in payload["file_inventory"])


def test_dxf_pdf_acceptance_gates_are_independently_valid(tmp_path):
    result = generate_golden_bundle(tmp_path, require_dwg=False)

    gates = [
        validate_all_dxf_layers(list(result.dxf_paths)),
        validate_pdf_diacritics(result.pdf_path),
        validate_pdf_font_embedding(result.pdf_path),
        validate_pdf_scale(result.pdf_path),
        validate_pdf_size(result.pdf_path),
    ]

    assert all(gate.status == "pass" for gate in gates), [gate.as_dict() for gate in gates]
