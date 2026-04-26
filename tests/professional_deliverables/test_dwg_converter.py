from __future__ import annotations

from pathlib import Path

import pytest

from app.services.professional_deliverables.dwg_converter import build_oda_command, find_oda_binary
from app.services.professional_deliverables.demo import generate_golden_bundle
from app.services.professional_deliverables.validators import validate_dwg_clean_open


def test_oda_command_contract_uses_github_runner_headless_shape():
    command = build_oda_command(
        source_dir=Path("/in"),
        target_dir=Path("/out"),
        binary="/usr/bin/ODAFileConverter",
        use_xvfb=True,
        input_filter="*.DXF",
    )
    assert command == (
        "xvfb-run",
        "-a",
        "/usr/bin/ODAFileConverter",
        "/in",
        "/out",
        "ACAD2018",
        "DWG",
        "0",
        "1",
        "*.DXF",
    )


def test_dwg_gate_skips_locally_when_oda_is_unavailable(tmp_path, monkeypatch):
    monkeypatch.delenv("ODA_FILE_CONVERTER_BIN", raising=False)
    monkeypatch.delenv("CI", raising=False)
    if find_oda_binary():
        pytest.skip("ODA is installed locally; skip missing-binary behavior test")

    result = generate_golden_bundle(tmp_path, require_dwg=False)
    gate = validate_dwg_clean_open(result.two_d_dir, result.two_d_dir / ".audit", require_dwg=False)

    assert gate.status == "skipped"

