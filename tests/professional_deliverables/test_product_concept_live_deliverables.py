from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from app.db import SessionLocal
from app.models import DesignVersion, ProfessionalDeliverableBundle, ProfessionalDeliverableJob
from app.services.design_intelligence.product_concept_adapter import ProductConceptAdapterBlocker, ProductConceptAdapterResult
from app.services.geometry import build_geometry_v2
from app.services.professional_deliverables.validators import GateResult
from tests.test_flows import complete_brief_payload, create_project, register


def _touch(path: Path, content: bytes = b"artifact") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def _make_task_job(client, session_payload, *, geometry: dict | None = None) -> tuple[str, str]:
    session = register(client, {**session_payload, "email": f"concept-live-{uuid4().hex}@test.com"})
    project = create_project(client, session["access_token"])
    brief = complete_brief_payload()
    brief["lot"] = {"width_m": 5, "depth_m": 20, "orientation": "south"}
    brief["floors"] = 3
    with SessionLocal() as db:
        version = DesignVersion(
            project_id=project["id"],
            version_number=1,
            status="locked",
            brief_json=brief,
            geometry_json=geometry or build_geometry_v2(brief),
            resolved_style_params={"style_id": "minimal_warm", "drawing_notes": ["Live concept route note."]},
        )
        db.add(version)
        db.flush()
        bundle = ProfessionalDeliverableBundle(project_id=project["id"], version_id=version.id, status="queued", quality_status="pending")
        db.add(bundle)
        db.flush()
        job = ProfessionalDeliverableJob(bundle_id=bundle.id, status="queued", stage="queued", progress_percent=0)
        db.add(job)
        db.commit()
        return bundle.id, job.id


def _patch_later_stages(monkeypatch, root: Path) -> None:
    def three_d(*_args, **_kwargs):
        glb = _touch(root / "3d" / "model.glb")
        fbx = _touch(root / "3d" / "model.fbx")
        textures_dir = root / "textures"
        textures_dir.mkdir(parents=True, exist_ok=True)
        return SimpleNamespace(three_d_dir=root / "3d", textures_dir=textures_dir, glb_path=glb, fbx_path=fbx, gate_results=(GateResult("3D", "pass", "ok"),))

    def usdz_stage(**_kwargs):
        usdz = _touch(root / "3d" / "model.usdz")
        return SimpleNamespace(usdz_path=usdz, gate_results=(GateResult("USDZ size budget", "pass", "ok"),), inventory_paths=(usdz,))

    def video_stage(*, video_dir: Path, **_kwargs):
        master = _touch(video_dir / "master_4k.mp4")
        return SimpleNamespace(video_dir=video_dir, master_video_path=master, gate_results=(GateResult("Master video format", "pass", "ok"), GateResult("Master video integrity", "pass", "ok")))

    def sprint3_summary(*, usdz_result, video_result, **_kwargs):
        return SimpleNamespace(
            gate_summary_json=_touch(root / "sprint3_gate_summary.json"),
            gate_summary_md=_touch(root / "sprint3_gate_summary.md"),
            gate_results=tuple(usdz_result.gate_results + video_result.gate_results),
        )

    monkeypatch.setattr("app.tasks.professional_deliverables.output_root_for", lambda _project_id, _version_id: root)
    monkeypatch.setattr("app.tasks.professional_deliverables.generate_project_3d_bundle", three_d)
    monkeypatch.setattr("app.tasks.professional_deliverables.export_project_usdz_stage", usdz_stage)
    monkeypatch.setattr("app.tasks.professional_deliverables.render_project_video_stage", video_stage)
    monkeypatch.setattr("app.tasks.professional_deliverables.write_project_sprint3_summary", sprint3_summary)


def test_live_concept_2d_route_uses_full_sheet_specs_and_registers_metadata(client, session_payload, monkeypatch, tmp_path):
    import app.tasks.professional_deliverables as task_module

    bundle_id, job_id = _make_task_job(client, session_payload)
    captured: dict = {}

    def two_d(project, _output_root, *, project_dir: Path, sheets=None, concept_package_metadata=None, **_kwargs):
        captured["sheets"] = sheets
        captured["concept_package_metadata"] = concept_package_metadata
        two_d_dir = project_dir / "2d"
        pdf = _touch(two_d_dir / "bundle.pdf")
        dxf_paths = tuple(_touch(two_d_dir / f"{sheet.filename_stem}.dxf") for sheet in sheets)
        summary_json = _touch(two_d_dir / "sprint1_gate_summary.json", json.dumps({"concept_package": concept_package_metadata}).encode())
        summary_md = _touch(two_d_dir / "sprint1_gate_summary.md")
        quality_json = _touch(two_d_dir / "artifact_quality_report.json", json.dumps({"concept_package": concept_package_metadata}).encode())
        quality_md = _touch(two_d_dir / "artifact_quality_report.md")
        return SimpleNamespace(
            pdf_path=pdf,
            dxf_paths=dxf_paths,
            dwg_paths=(),
            gate_summary_json=summary_json,
            gate_summary_md=summary_md,
            artifact_quality_report_json=quality_json,
            artifact_quality_report_md=quality_md,
            gate_results=(GateResult("PDF page count", "pass", "ok"),),
        )

    monkeypatch.setattr(task_module, "generate_project_2d_bundle", two_d)
    _patch_later_stages(monkeypatch, tmp_path)

    task_module.run_professional_deliverable_bundle_task(job_id)

    assert captured["concept_package_metadata"]["enabled"] is True
    assert len(captured["sheets"]) == captured["concept_package_metadata"]["sheet_count"]
    assert len(captured["sheets"]) > 7
    assert {"A-000", "A-601", "A-602", "A-901"} <= {sheet.number for sheet in captured["sheets"]}
    assert {"cover_index", "room_area_schedule", "door_window_schedule", "assumptions_style_notes"} <= {sheet.kind for sheet in captured["sheets"]}

    with SessionLocal() as db:
        bundle = db.get(ProfessionalDeliverableBundle, bundle_id)
        assert bundle.status == "ready"
        pdf_asset = next(asset for asset in bundle.assets if asset.asset_role == "pdf")
        assert pdf_asset.metadata_json["concept_package"] is True
        assert pdf_asset.metadata_json["sheet_count"] > 7
        dxf_assets = [asset for asset in bundle.assets if asset.asset_role == "dxf"]
        assert any(asset.metadata_json.get("sheet_number") == "A-601" for asset in dxf_assets)
        assert all({"sheet_number", "sheet_title", "sheet_kind", "readiness", "state", "source_path", "public_url"} <= set(asset.metadata_json) for asset in dxf_assets)


def test_live_concept_2d_fallback_is_explicit_for_adapter_unsupported(client, session_payload, monkeypatch, tmp_path):
    import app.tasks.professional_deliverables as task_module

    bundle_id, job_id = _make_task_job(client, session_payload)
    captured: dict = {}

    unsupported = ProductConceptAdapterResult(
        status="unsupported",
        blocker_reasons=(ProductConceptAdapterBlocker("unsupported_fixture_contract", "fixture contract is not concept-ready"),),
        fallback_required=True,
        fallback_reason="Concept adapter unsupported_fixture_contract",
    )
    monkeypatch.setattr(task_module, "adapt_live_design_version_to_concept_source", lambda **_kwargs: unsupported)

    def two_d(project, _output_root, *, project_dir: Path, sheets=None, concept_fallback_reason=None, **_kwargs):
        captured["sheets"] = sheets
        captured["fallback_reason"] = concept_fallback_reason
        two_d_dir = project_dir / "2d"
        return SimpleNamespace(
            pdf_path=_touch(two_d_dir / "bundle.pdf"),
            dxf_paths=(_touch(two_d_dir / "A-100-site.dxf"),),
            dwg_paths=(),
            gate_summary_json=_touch(two_d_dir / "sprint1_gate_summary.json"),
            gate_summary_md=_touch(two_d_dir / "sprint1_gate_summary.md"),
            artifact_quality_report_json=_touch(two_d_dir / "artifact_quality_report.json"),
            artifact_quality_report_md=_touch(two_d_dir / "artifact_quality_report.md"),
            gate_results=(GateResult("PDF page count", "pass", "ok"),),
        )

    monkeypatch.setattr(task_module, "generate_project_2d_bundle", two_d)
    _patch_later_stages(monkeypatch, tmp_path)

    task_module.run_professional_deliverable_bundle_task(job_id)

    assert captured["sheets"] is None
    assert captured["fallback_reason"] == "Concept adapter unsupported_fixture_contract"
    with SessionLocal() as db:
        bundle = db.get(ProfessionalDeliverableBundle, bundle_id)
        assert bundle.runtime_metadata_json["concept_2d"]["readiness"] == "fallback"
        pdf_asset = next(asset for asset in bundle.assets if asset.asset_role == "pdf")
        assert pdf_asset.metadata_json["concept_package"] is False
        assert pdf_asset.metadata_json["fallback_reason"] == "Concept adapter unsupported_fixture_contract"
