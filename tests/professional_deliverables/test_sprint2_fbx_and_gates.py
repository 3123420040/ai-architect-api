from __future__ import annotations

import json

from app.services.professional_deliverables.fbx_exporter import FBX_PRESET_TWINMOTION
from app.services.professional_deliverables.validators import GateResult, write_gate_outputs


def test_fbx_twinmotion_preset_is_named_and_cm_z_up() -> None:
    assert FBX_PRESET_TWINMOTION["units"] == "cm"
    assert FBX_PRESET_TWINMOTION["axis_up"] == "Z"
    assert FBX_PRESET_TWINMOTION["source_axis"] == "Y-up"
    assert FBX_PRESET_TWINMOTION["embed_media"] is True
    assert FBX_PRESET_TWINMOTION["smoothing_groups"] is True


def test_gate_writer_supports_sprint2_summary_names(tmp_path) -> None:
    json_path, md_path = write_gate_outputs(
        tmp_path,
        [GateResult("glTF Validator", "pass", "0 errors")],
        [],
        basename="sprint2_gate_summary",
        title="Sprint 2 Gate Summary",
    )

    assert json_path.name == "sprint2_gate_summary.json"
    assert md_path.name == "sprint2_gate_summary.md"
    assert json.loads(json_path.read_text(encoding="utf-8"))["status"] == "pass"
    assert md_path.read_text(encoding="utf-8").startswith("# Sprint 2 Gate Summary")


def test_gate_writer_can_allow_sprint2_expected_skips(tmp_path) -> None:
    json_path, _ = write_gate_outputs(
        tmp_path,
        [GateResult("USDZ size budget", "skipped", "Sprint 3 gate")],
        [],
        basename="sprint2_gate_summary",
        title="Sprint 2 Gate Summary",
        skipped_is_partial=False,
    )

    assert json.loads(json_path.read_text(encoding="utf-8"))["status"] == "pass"
