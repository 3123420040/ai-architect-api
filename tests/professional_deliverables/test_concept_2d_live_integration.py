from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import fitz
import ezdxf
import pytest
from sqlalchemy import select

from app.db import SessionLocal
from app.models import DesignVersion, ProfessionalDeliverableBundle, ProfessionalDeliverableJob, Project, User
from app.services.design_intelligence.product_concept_adapter import (
    ProductConceptAdapterBlocker,
    ProductConceptAdapterResult,
    adapt_live_design_version_to_concept_source,
)
from app.services.geometry import build_geometry_v2
from app.services.professional_deliverables.orchestrator import serialize_bundle
from app.services.professional_deliverables.validators import GateResult
from tests.test_flows import complete_brief_payload, register


LOCAL_LIVE_PROJECT_ID = "56e4c77f-5f46-4506-af8c-df88362aad34"
LOCAL_LIVE_VERSION_ID = "5e6b84dd-5e4c-419d-a00a-b4f9b54918ee"
STALE_GOLDEN_DIMENSION_LABEL = "Ranh đất 5 m x 15 m"
REQUIRED_CONCEPT_SHEET_NUMBERS = {"A-000", "A-601", "A-602", "A-901"}
REQUIRED_CONCEPT_SHEET_KINDS = {
    "cover_index",
    "room_area_schedule",
    "door_window_schedule",
    "assumptions_style_notes",
}


def _pdf_text(path: Path) -> str:
    with fitz.open(path) as doc:
        return "\n".join(page.get_text("text") for page in doc)


def _touch(path: Path, content: bytes = b"artifact") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def _live_5x20_four_floor_brief() -> dict:
    brief = complete_brief_payload()
    brief["lot"] = {"width_m": 5, "depth_m": 20, "orientation": "south"}
    brief["floors"] = 4
    brief["rooms"] = {"bedrooms": 4, "bathrooms": 4}
    brief["style"] = "minimal_warm"
    brief["summary"] = "Local live regression case 56e4: 5x20m, 4 floors, rooms/walls/openings."
    return brief


@pytest.mark.parametrize(
    ("width", "depth", "floors"),
    [
        (4, 16, 3),
        (5, 20, 4),
        (5, 30, 4),
        (6, 22, 4),
        (7, 25, 3),
        (8, 20, 2),
        (10, 12, 2),
    ],
)
def test_generated_live_geometry_avoids_unreviewable_room_area_outliers(width, depth, floors):
    brief = complete_brief_payload()
    brief["lot"] = {"width_m": width, "depth_m": depth, "orientation": "south"}
    brief["floors"] = floors
    brief["rooms"] = {"bedrooms": 4, "bathrooms": 4}
    brief["style"] = "modern_minimalist"

    geometry = build_geometry_v2(brief)
    room_areas = [(room["name"], room["area_m2"]) for room in geometry["rooms"]]

    assert room_areas
    assert all(area < 38 for _name, area in room_areas)
    assert all(area >= 2 for _name, area in room_areas)


def _make_live_case_job(client, session_payload) -> tuple[str, str]:
    session = register(client, session_payload)
    brief = _live_5x20_four_floor_brief()
    geometry = build_geometry_v2(brief)
    assert geometry["site"]["boundary"]
    assert len([level for level in geometry["levels"] if level["type"] == "floor"]) == 4
    assert geometry["rooms"]
    assert geometry["walls"]
    assert geometry["openings"]

    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == session["user"]["email"]))
        assert user is not None
        project = Project(
            id=LOCAL_LIVE_PROJECT_ID,
            organization_id=user.organization_id,
            name="C2DL4 Local Live Regression 5x20",
            client_name="Local Live Case 56e4",
            status="review",
            brief_json=brief,
            brief_status="complete",
        )
        db.add(project)
        version = DesignVersion(
            id=LOCAL_LIVE_VERSION_ID,
            project_id=project.id,
            version_number=1,
            status="locked",
            brief_json=brief,
            geometry_json=geometry,
            resolved_style_params={
                "style_id": "minimal_warm",
                "style_name": "Minimal Warm",
                "facade_intent": "Quiet warm frontage from selected live version metadata.",
                "drawing_notes": ["Local live fixture note for concept 2D evidence."],
            },
            generation_metadata={
                "decision_metadata": {
                    "fit_reasons": ["Selected geometry preserves the 5x20 lot and four-floor program."],
                    "caveats": ["Concept-only package; not for construction or permit use."],
                }
            },
        )
        db.add(version)
        db.flush()
        bundle = ProfessionalDeliverableBundle(project_id=project.id, version_id=version.id, status="queued", quality_status="pending")
        db.add(bundle)
        db.flush()
        job = ProfessionalDeliverableJob(bundle_id=bundle.id, status="queued", stage="queued", progress_percent=0)
        db.add(job)
        db.commit()
        return bundle.id, job.id


def _patch_non_2d_product_stages(monkeypatch, root: Path) -> None:
    def three_d(*_args, **_kwargs):
        glb = _touch(root / "3d" / "model.glb")
        fbx = _touch(root / "3d" / "model.fbx")
        textures_dir = root / "textures"
        textures_dir.mkdir(parents=True, exist_ok=True)
        return SimpleNamespace(
            three_d_dir=root / "3d",
            textures_dir=textures_dir,
            glb_path=glb,
            fbx_path=fbx,
            gate_results=(GateResult("3D", "pass", "ok"),),
        )

    def usdz_stage(**_kwargs):
        usdz = _touch(root / "3d" / "model.usdz")
        return SimpleNamespace(usdz_path=usdz, gate_results=(GateResult("USDZ size budget", "pass", "ok"),), inventory_paths=(usdz,))

    def video_stage(*, video_dir: Path, **_kwargs):
        master = _touch(video_dir / "master_4k.mp4")
        return SimpleNamespace(
            video_dir=video_dir,
            master_video_path=master,
            gate_results=(GateResult("Master video format", "pass", "ok"), GateResult("Master video integrity", "pass", "ok")),
        )

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


def _bundle_artifact_paths(bundle_id: str) -> tuple[Path, Path]:
    with SessionLocal() as db:
        bundle = db.get(ProfessionalDeliverableBundle, bundle_id)
        assert bundle is not None
        pdf_asset = next(asset for asset in bundle.assets if asset.asset_role == "pdf")
        quality_asset = next(asset for asset in bundle.assets if asset.asset_role == "artifact_quality_report_json")
        return Path(pdf_asset.storage_key), Path(quality_asset.storage_key)


def test_live_product_geometry_generates_full_concept_package_evidence(client, session_payload, monkeypatch, tmp_path):
    import app.tasks.professional_deliverables as task_module

    root = tmp_path / "professional-deliverables" / "projects" / LOCAL_LIVE_PROJECT_ID / "versions" / LOCAL_LIVE_VERSION_ID
    bundle_id, job_id = _make_live_case_job(client, session_payload)
    _patch_non_2d_product_stages(monkeypatch, root)

    task_module.run_professional_deliverable_bundle_task(job_id)

    pdf_path, quality_report_path = _bundle_artifact_paths(bundle_id)
    with fitz.open(pdf_path) as doc:
        assert doc.page_count > 7
    pdf_text = _pdf_text(pdf_path)
    assert REQUIRED_CONCEPT_SHEET_NUMBERS <= set(pdf_text.split())
    assert "Professional Concept 2D Package" in pdf_text
    assert "Bảng phòng và diện tích" in pdf_text
    assert "Bảng cửa đi và cửa sổ" in pdf_text
    assert "Giả định và ghi chú style" in pdf_text
    assert "Modern Minimalist / Tối giản ấm" in pdf_text
    assert "Vật liệu nền concept" in pdf_text
    assert "Mặt tiền concept" in pdf_text
    assert "Tầng-tầng 3.30 m" in pdf_text
    assert "{'type':" not in pdf_text
    assert '"type":' not in pdf_text
    assert "5.00 m" in pdf_text
    assert "20.00 m" in pdf_text
    assert STALE_GOLDEN_DIMENSION_LABEL not in pdf_text
    assert "không dùng cho thi công" in pdf_text

    quality_report = json.loads(quality_report_path.read_text(encoding="utf-8"))
    concept_package = quality_report["concept_package"]
    assert concept_package["enabled"] is True
    assert concept_package["readiness"] == "ready"
    assert concept_package["technical_ready"] is True
    assert concept_package["concept_review_ready"] is True
    assert concept_package["market_presentation_ready"] is False
    assert concept_package["construction_ready"] is False
    assert concept_package["fallback_reason"] is None
    assert concept_package["qa_bounds"]["lot_width_m"] == 5
    assert concept_package["qa_bounds"]["lot_depth_m"] == 20
    assert concept_package["qa_bounds"]["floor_count"] == 4
    assert concept_package["sheet_count"] > 7
    assert REQUIRED_CONCEPT_SHEET_NUMBERS <= {sheet["sheet_number"] for sheet in concept_package["sheets"]}
    assert REQUIRED_CONCEPT_SHEET_KINDS <= {sheet["sheet_kind"] for sheet in concept_package["sheets"]}

    readiness = {artifact["artifact_role"]: artifact for artifact in quality_report["artifacts"]}
    assert readiness["pdf"]["state"] == "ready"
    assert readiness["pdf"]["customer_ready"] is True
    assert readiness["pdf"]["technical_ready"] is True
    assert readiness["pdf"]["concept_review_ready"] is True
    assert readiness["pdf"]["construction_ready"] is False
    assert readiness["dxf"]["state"] == "ready"
    assert readiness["dxf"]["customer_ready"] is True
    assert readiness["dwg"]["state"] in {"ready", "skipped"}

    expected_dxf_names = {sheet["filename"] for sheet in concept_package["sheets"]}
    actual_dxf_paths = {path.name for path in sorted((root / "2d").glob("*.dxf"))}
    assert actual_dxf_paths == expected_dxf_names
    for dxf_name in expected_dxf_names:
        dxf_doc = ezdxf.readfile(root / "2d" / dxf_name)
        text = "\n".join(entity.dxf.text for entity in dxf_doc.modelspace() if entity.dxftype() == "TEXT")
        sheet_number = next(sheet["sheet_number"] for sheet in concept_package["sheets"] if sheet["filename"] == dxf_name)
        assert sheet_number in text

    with SessionLocal() as db:
        bundle = db.get(ProfessionalDeliverableBundle, bundle_id)
        assert bundle is not None
        assert bundle.status == "ready"
        assert bundle.quality_status in {"pass", "partial"}
        assert bundle.runtime_metadata_json["concept_2d"]["readiness"] == "ready"
        dxf_assets = [asset for asset in bundle.assets if asset.asset_role == "dxf"]
        assert {Path(asset.storage_key).name for asset in dxf_assets} == expected_dxf_names
        assert all(asset.metadata_json["concept_package"] is True for asset in dxf_assets)
        assert any(asset.metadata_json["sheet_number"] == "A-901" for asset in dxf_assets)
        payload = serialize_bundle(bundle)
        assert payload["concept_package"]["enabled"] is True
        assert payload["technical_details"]["concept_package"]["sheet_count"] == len(expected_dxf_names)


def test_legacy_2d_fallback_remains_machine_readable_when_concept_adapter_is_unsupported(
    client,
    session_payload,
    monkeypatch,
    tmp_path,
):
    import app.tasks.professional_deliverables as task_module

    root = tmp_path / "fallback" / "projects" / LOCAL_LIVE_PROJECT_ID / "versions" / LOCAL_LIVE_VERSION_ID
    bundle_id, job_id = _make_live_case_job(client, session_payload)
    _patch_non_2d_product_stages(monkeypatch, root)
    unsupported = ProductConceptAdapterResult(
        status="unsupported",
        blocker_reasons=(
            ProductConceptAdapterBlocker(
                code="unsupported_fixture_contract",
                message="Fixture contract is not concept-package ready.",
                field="geometry_json.fixtures",
            ),
        ),
        fallback_required=True,
        fallback_reason="Concept adapter unsupported_fixture_contract",
    )
    monkeypatch.setattr(task_module, "adapt_live_design_version_to_concept_source", lambda **_kwargs: unsupported)

    task_module.run_professional_deliverable_bundle_task(job_id)

    pdf_path, quality_report_path = _bundle_artifact_paths(bundle_id)
    pdf_text = _pdf_text(pdf_path)
    assert "A-601" not in pdf_text
    assert "A-602" not in pdf_text
    assert "A-901" not in pdf_text
    assert "5.00 m" in pdf_text
    assert "20.00 m" in pdf_text
    assert STALE_GOLDEN_DIMENSION_LABEL not in pdf_text
    assert len(tuple((root / "2d").glob("*.dxf"))) == 7

    quality_report = json.loads(quality_report_path.read_text(encoding="utf-8"))
    assert quality_report["concept_package"] == {
        "enabled": False,
        "readiness": "fallback",
        "fallback_reason": "Concept adapter unsupported_fixture_contract",
    }

    with SessionLocal() as db:
        bundle = db.get(ProfessionalDeliverableBundle, bundle_id)
        assert bundle is not None
        assert bundle.status == "ready"
        concept_2d = bundle.runtime_metadata_json["concept_2d"]
        assert concept_2d["enabled"] is False
        assert concept_2d["readiness"] == "fallback"
        assert concept_2d["adapter_status"] == "unsupported"
        assert concept_2d["fallback_reason"] == "Concept adapter unsupported_fixture_contract"
        assert concept_2d["blockers"][0]["code"] == "unsupported_fixture_contract"
        pdf_asset = next(asset for asset in bundle.assets if asset.asset_role == "pdf")
        assert pdf_asset.metadata_json["concept_package"] is False
        assert pdf_asset.metadata_json["fallback_reason"] == "Concept adapter unsupported_fixture_contract"
        payload = serialize_bundle(bundle)
        assert payload["concept_package"]["readiness"] == "fallback"
        assert payload["technical_details"]["concept_package"]["blockers"][0]["field"] == "geometry_json.fixtures"


def test_adapter_reports_missing_and_unsupported_geometry_as_machine_readable_fallbacks():
    blocked = adapt_live_design_version_to_concept_source(
        project_id=LOCAL_LIVE_PROJECT_ID,
        project_name="Missing Geometry",
        brief_json=_live_5x20_four_floor_brief(),
        geometry_json=None,
        version_id=LOCAL_LIVE_VERSION_ID,
    )
    unsupported = adapt_live_design_version_to_concept_source(
        project_id=LOCAL_LIVE_PROJECT_ID,
        project_name="Unsupported Geometry",
        brief_json=_live_5x20_four_floor_brief(),
        geometry_json={"$schema": "external-model"},
        version_id=LOCAL_LIVE_VERSION_ID,
    )

    assert blocked.status == "blocked"
    assert blocked.source is None
    assert blocked.fallback_required is True
    assert blocked.fallback_reason
    assert blocked.blocker_reasons[0].as_dict() == {
        "code": "missing_geometry",
        "message": "DesignVersion.geometry_json is required for Concept 2D package adaptation.",
        "field": "geometry_json",
        "technical_detail": None,
    }
    assert unsupported.status == "unsupported"
    assert unsupported.source is None
    assert unsupported.fallback_required is True
    assert unsupported.blocker_reasons[0].as_dict()["code"] == "unsupported_geometry_schema"
    assert unsupported.blocker_reasons[0].as_dict()["field"] == "geometry_json.$schema"
