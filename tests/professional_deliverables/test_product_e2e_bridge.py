from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from app.db import SessionLocal
from app.models import DesignVersion, ProfessionalDeliverableBundle, ProfessionalDeliverableJob
from app.services.geometry import build_geometry_v2
from app.services.professional_deliverables.validators import GateResult
from app.services.professional_deliverables.geometry_adapter import GeometryAdapterError, geometry_to_drawing_project
from tests.test_flows import auth_headers, complete_brief_payload, create_project, register


def test_geometry_adapter_converts_generated_geometry_to_drawing_project():
    brief = complete_brief_payload()
    geometry = build_geometry_v2(brief)

    project = geometry_to_drawing_project(
        project_id="project-1",
        project_name="Nha pho Tan Binh",
        brief_json=brief,
        geometry_json=geometry,
    )

    assert project.project_id == "project-1"
    assert project.storeys == brief["floors"]
    assert project.lot_width_m > 0
    assert project.lot_depth_m > 0
    assert project.rooms
    assert project.walls
    assert project.openings
    assert any(room.name.startswith("Phòng") or room.name in {"Bếp và ăn", "Vệ sinh"} for room in project.rooms)


def test_geometry_adapter_rejects_missing_or_unsupported_geometry():
    try:
        geometry_to_drawing_project(
            project_id="project-1",
            project_name="Demo",
            brief_json={},
            geometry_json=None,
        )
    except GeometryAdapterError as exc:
        assert "geometry_json" in str(exc)
    else:
        raise AssertionError("missing geometry should fail")

    try:
        geometry_to_drawing_project(
            project_id="project-1",
            project_name="Demo",
            brief_json={},
            geometry_json={"$schema": "external-model"},
        )
    except GeometryAdapterError as exc:
        assert "ai-architect-geometry-v2" in str(exc)
    else:
        raise AssertionError("unsupported geometry should fail")


def test_professional_deliverables_api_creates_async_job(client, session_payload, monkeypatch):
    queued: list[str] = []
    monkeypatch.setattr(
        "app.services.professional_deliverables.orchestrator.queue_professional_bundle_job",
        lambda job_id: queued.append(job_id),
    )
    monkeypatch.setattr(
        "app.api.v1.professional_deliverables.queue_professional_bundle_job",
        lambda job_id: queued.append(job_id),
    )

    session = register(client, session_payload)
    token = session["access_token"]
    project = create_project(client, token)
    project_id = project["id"]
    brief = complete_brief_payload()
    geometry = build_geometry_v2(brief)

    with SessionLocal() as db:
        version = DesignVersion(
            project_id=project_id,
            version_number=1,
            status="locked",
            brief_json=brief,
            geometry_json=geometry,
        )
        db.add(version)
        db.commit()
        version_id = version.id

    response = client.post(
        f"/api/v1/versions/{version_id}/professional-deliverables/jobs",
        json={},
        headers=auth_headers(token),
    )

    assert response.status_code == 202, response.text
    payload = response.json()
    assert payload["status"] == "queued"
    assert payload["stage"] == "queued"
    assert payload["progress_percent"] == 0
    assert queued == [payload["job_id"]]

    bundle_response = client.get(
        f"/api/v1/versions/{version_id}/professional-deliverables",
        headers=auth_headers(token),
    )
    assert bundle_response.status_code == 200, bundle_response.text
    assert bundle_response.json()["bundle_id"] == payload["bundle_id"]


def test_professional_deliverables_api_rejects_ineligible_version(client, session_payload):
    session = register(client, session_payload)
    token = session["access_token"]
    project = create_project(client, token)
    brief = complete_brief_payload()

    with SessionLocal() as db:
        version = DesignVersion(
            project_id=project["id"],
            version_number=1,
            status="generated",
            brief_json=brief,
            geometry_json=build_geometry_v2(brief),
        )
        db.add(version)
        db.commit()
        version_id = version.id

    response = client.post(
        f"/api/v1/versions/{version_id}/professional-deliverables/jobs",
        json={},
        headers=auth_headers(token),
    )

    assert response.status_code == 409


def test_professional_deliverables_retry_requires_failed_job(client, session_payload, monkeypatch):
    queued: list[str] = []
    monkeypatch.setattr(
        "app.api.v1.professional_deliverables.queue_professional_bundle_job",
        lambda job_id: queued.append(job_id),
    )
    session = register(client, session_payload)
    token = session["access_token"]
    project = create_project(client, token)
    brief = complete_brief_payload()

    with SessionLocal() as db:
        version = DesignVersion(
            project_id=project["id"],
            version_number=1,
            status="locked",
            brief_json=brief,
            geometry_json=build_geometry_v2(brief),
        )
        db.add(version)
        db.flush()
        bundle = ProfessionalDeliverableBundle(
            project_id=project["id"],
            version_id=version.id,
            status="failed",
            quality_status="fail",
        )
        db.add(bundle)
        db.flush()
        job = ProfessionalDeliverableJob(
            bundle_id=bundle.id,
            status="failed",
            stage="render_video",
            progress_percent=85,
            error_code="runtime_error",
            error_message="boom",
        )
        db.add(job)
        db.commit()
        job_id = job.id

    response = client.post(
        f"/api/v1/professional-deliverables/jobs/{job_id}/retry",
        headers=auth_headers(token),
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["status"] == "queued"
    assert payload["progress_percent"] == 0
    assert queued == [job_id]


def _touch(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"artifact")
    return path


def _make_task_job(client, session_payload):
    payload = {**session_payload, "email": f"architect-{uuid4().hex}@test.com"}
    session = register(client, payload)
    token = session["access_token"]
    project = create_project(client, token)
    brief = complete_brief_payload()
    with SessionLocal() as db:
        version = DesignVersion(
            project_id=project["id"],
            version_number=1,
            status="locked",
            brief_json=brief,
            geometry_json=build_geometry_v2(brief),
        )
        db.add(version)
        db.flush()
        bundle = ProfessionalDeliverableBundle(
            project_id=project["id"],
            version_id=version.id,
            status="queued",
            quality_status="pending",
        )
        db.add(bundle)
        db.flush()
        job = ProfessionalDeliverableJob(bundle_id=bundle.id, status="queued", stage="queued", progress_percent=0)
        db.add(job)
        db.commit()
        return bundle.id, job.id


def _patch_task_generators(monkeypatch, root: Path, *, missing_mp4: bool = False, sprint3_skipped: bool = False, dwg_skipped: bool = False):
    def two_d(*_args, **_kwargs):
        pdf = _touch(root / "2d" / "bundle.pdf")
        dxf = _touch(root / "2d" / "sheet-a100.dxf")
        s1_json = _touch(root / "2d" / "gate_summary.json")
        s1_md = _touch(root / "2d" / "gate_summary.md")
        gates = [GateResult("PDF", "pass", "ok")]
        if dwg_skipped:
            gates.append(GateResult("DWG clean-open", "skipped", "ODA converter unavailable"))
        return SimpleNamespace(pdf_path=pdf, dxf_paths=[dxf], dwg_paths=[], gate_summary_json=s1_json, gate_summary_md=s1_md, gate_results=tuple(gates))

    def three_d(*_args, **_kwargs):
        _touch(root / "3d" / "model.glb")
        _touch(root / "3d" / "model.fbx")
        return SimpleNamespace(gate_results=(GateResult("3D", "pass", "ok"),))

    def ar_video(*_args, **_kwargs):
        _touch(root / "3d" / "model.usdz")
        if not missing_mp4:
            _touch(root / "video" / "master_4k.mp4")
        s3_json = _touch(root / "sprint3_gate_summary.json")
        s3_md = _touch(root / "sprint3_gate_summary.md")
        status = "skipped" if sprint3_skipped else "pass"
        return SimpleNamespace(gate_summary_json=s3_json, gate_summary_md=s3_md, gate_results=(GateResult("Video", status, "ok"),))

    def sprint4_derivatives(bundle_root):
        if not (bundle_root / "video" / "master_4k.mp4").exists():
            raise RuntimeError("Missing required master video: video/master_4k.mp4")
        return {
            "reel": _touch(bundle_root / "video" / "reel_9x16_1080p.mp4"),
            "hero_still": _touch(bundle_root / "derivatives" / "hero_still_4k.png"),
            "gif_preview": _touch(bundle_root / "derivatives" / "preview.gif"),
        }

    def sprint4_manifest(bundle_root, **_kwargs):
        return _touch(bundle_root / "manifest.json")

    def sprint4_gates(bundle_root):
        return [GateResult("Sprint 4", "pass", "ok")], _touch(bundle_root / "sprint4_gate_summary.json"), _touch(bundle_root / "sprint4_gate_summary.md")

    monkeypatch.setattr("app.tasks.professional_deliverables.output_root_for", lambda _project_id, _version_id: root)
    monkeypatch.setattr("app.tasks.professional_deliverables.generate_project_2d_bundle", two_d)
    monkeypatch.setattr("app.tasks.professional_deliverables.generate_project_3d_bundle", three_d)
    monkeypatch.setattr("app.tasks.professional_deliverables.generate_project_ar_video_bundle", ar_video)
    monkeypatch.setattr("app.tasks.professional_deliverables.derive_sprint4_video_outputs", sprint4_derivatives)
    monkeypatch.setattr("app.tasks.professional_deliverables.build_manifest", sprint4_manifest)
    monkeypatch.setattr("app.tasks.professional_deliverables.run_sprint4_gates", sprint4_gates)


def test_product_task_succeeds_with_required_artifacts_and_assets(client, session_payload, monkeypatch, tmp_path):
    from app.tasks.professional_deliverables import run_professional_deliverable_bundle_task

    bundle_id, job_id = _make_task_job(client, session_payload)
    _patch_task_generators(monkeypatch, tmp_path)

    result = run_professional_deliverable_bundle_task(job_id)

    assert result["status"] == "completed"
    with SessionLocal() as db:
        bundle = db.get(ProfessionalDeliverableBundle, bundle_id)
        assert bundle.status == "ready"
        assert bundle.quality_status == "pass"
        roles = {asset.asset_role for asset in bundle.assets}
        assert {"pdf", "dxf", "glb", "fbx", "usdz", "mp4", "gate_summary_json", "gate_summary_md"} <= roles


def test_product_task_fails_for_missing_mp4_or_skipped_sprint3_gate(client, session_payload, monkeypatch, tmp_path):
    from app.tasks.professional_deliverables import run_professional_deliverable_bundle_task

    bundle_id, job_id = _make_task_job(client, session_payload)
    _patch_task_generators(monkeypatch, tmp_path / "missing", missing_mp4=True)

    try:
        run_professional_deliverable_bundle_task(job_id)
    except RuntimeError as exc:
        assert "master_4k.mp4" in str(exc)
    else:
        raise AssertionError("missing MP4 should fail")

    with SessionLocal() as db:
        bundle = db.get(ProfessionalDeliverableBundle, bundle_id)
        assert bundle.status == "failed"

    bundle_id, job_id = _make_task_job(client, session_payload)
    _patch_task_generators(monkeypatch, tmp_path / "skipped", sprint3_skipped=True)

    try:
        run_professional_deliverable_bundle_task(job_id)
    except RuntimeError as exc:
        assert "Sprint 3 gate skipped" in str(exc)
    else:
        raise AssertionError("skipped Sprint 3 gate should fail")

    with SessionLocal() as db:
        bundle = db.get(ProfessionalDeliverableBundle, bundle_id)
        assert bundle.status == "failed"


def test_product_task_allows_only_dwg_oda_skip_as_partial(client, session_payload, monkeypatch, tmp_path):
    from app.tasks.professional_deliverables import run_professional_deliverable_bundle_task

    bundle_id, job_id = _make_task_job(client, session_payload)
    _patch_task_generators(monkeypatch, tmp_path, dwg_skipped=True)

    run_professional_deliverable_bundle_task(job_id)

    with SessionLocal() as db:
        bundle = db.get(ProfessionalDeliverableBundle, bundle_id)
        assert bundle.status == "ready"
        assert bundle.quality_status == "partial"
        assert bundle.is_degraded is True
        assert "ODA" in bundle.degraded_reasons_json[0]
