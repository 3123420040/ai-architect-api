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
    assert payload["job_id"] != job_id
    assert queued == [payload["job_id"]]


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


def _patch_task_generators(
    monkeypatch,
    root: Path,
    *,
    calls: list[str] | None = None,
    missing_mp4: bool = False,
    sprint3_skipped: bool = False,
    sprint3_failed_gate: bool = False,
    dwg_skipped: bool = False,
    glb_content: bytes = b"artifact",
):
    calls = calls if calls is not None else []

    def two_d(*_args, **_kwargs):
        calls.append("2d")
        pdf = _touch(root / "2d" / "bundle.pdf")
        dxf = _touch(root / "2d" / "sheet-a100.dxf")
        s1_json = _touch(root / "2d" / "gate_summary.json")
        s1_md = _touch(root / "2d" / "gate_summary.md")
        gates = [GateResult("PDF", "pass", "ok")]
        if dwg_skipped:
            gates.append(GateResult("DWG clean-open", "skipped", "ODA converter unavailable"))
        return SimpleNamespace(pdf_path=pdf, dxf_paths=[dxf], dwg_paths=[], gate_summary_json=s1_json, gate_summary_md=s1_md, gate_results=tuple(gates))

    def three_d(*_args, **_kwargs):
        calls.append("3d")
        glb = root / "3d" / "model.glb"
        glb.parent.mkdir(parents=True, exist_ok=True)
        glb.write_bytes(glb_content)
        _touch(root / "3d" / "model.fbx")
        textures_dir = root / "textures"
        textures_dir.mkdir(parents=True, exist_ok=True)
        _touch(textures_dir / "material.ktx2")
        return SimpleNamespace(
            project_dir=root,
            three_d_dir=root / "3d",
            textures_dir=textures_dir,
            glb_path=glb,
            fbx_path=root / "3d" / "model.fbx",
            gate_results=(GateResult("3D", "pass", "ok"),),
        )

    def usdz_stage(*, glb_path: Path, **_kwargs):
        calls.append("usdz")
        assert glb_path.read_bytes() == glb_content
        usdz = _touch(root / "3d" / "model.usdz")
        return SimpleNamespace(
            project_dir=root,
            three_d_dir=root / "3d",
            usdz_path=usdz,
            gate_results=(GateResult("USDZ size budget", "pass", "ok"),),
            inventory_paths=(usdz,),
        )

    def video_stage(*, glb_path: Path, video_dir: Path, **_kwargs):
        calls.append("video")
        assert glb_path.read_bytes() == glb_content
        camera_path_json = _touch(video_dir / "camera_path.json")
        master_video = video_dir / "master_4k.mp4"
        if not missing_mp4:
            _touch(master_video)
        status = "skipped" if sprint3_skipped else "pass"
        gates = [
            GateResult("Master video format", status, "ok"),
            GateResult("Master video integrity", status, "ok"),
        ]
        if sprint3_failed_gate:
            gates.append(GateResult("Camera collision sanity", "fail", "Bep va an at 28.0s intersects wall-f1-07"))
        return SimpleNamespace(
            project_dir=root,
            video_dir=video_dir,
            master_video_path=master_video,
            camera_path_json=camera_path_json,
            gate_results=tuple(gates),
            inventory_paths=(master_video, camera_path_json),
        )

    def sprint3_summary(*, usdz_result, video_result, **_kwargs):
        calls.append("summary")
        s3_json = _touch(root / "sprint3_gate_summary.json")
        s3_md = _touch(root / "sprint3_gate_summary.md")
        gates = tuple(usdz_result.gate_results + video_result.gate_results)
        return SimpleNamespace(
            project_dir=root,
            three_d_dir=root / "3d",
            video_dir=video_result.video_dir,
            usdz_path=usdz_result.usdz_path,
            master_video_path=video_result.master_video_path,
            gate_summary_json=s3_json,
            gate_summary_md=s3_md,
            gate_results=gates,
        )

    monkeypatch.setattr("app.tasks.professional_deliverables.output_root_for", lambda _project_id, _version_id: root)
    monkeypatch.setattr("app.tasks.professional_deliverables.generate_project_2d_bundle", two_d)
    monkeypatch.setattr("app.tasks.professional_deliverables.generate_project_3d_bundle", three_d)
    monkeypatch.setattr("app.tasks.professional_deliverables.export_project_usdz_stage", usdz_stage)
    monkeypatch.setattr("app.tasks.professional_deliverables.render_project_video_stage", video_stage)
    monkeypatch.setattr("app.tasks.professional_deliverables.write_project_sprint3_summary", sprint3_summary)


def test_product_task_generates_sprint2_once_and_uses_split_sprint3_stages(client, session_payload, monkeypatch, tmp_path):
    from app.tasks.professional_deliverables import run_professional_deliverable_bundle_task

    _bundle_id, job_id = _make_task_job(client, session_payload)
    calls: list[str] = []
    _patch_task_generators(monkeypatch, tmp_path, calls=calls)

    run_professional_deliverable_bundle_task(job_id)

    assert calls == ["2d", "3d", "usdz", "video", "summary"]
    assert calls.count("3d") == 1


def test_product_task_stage_order_is_stage_aligned(client, session_payload, monkeypatch, tmp_path):
    from app.services.professional_deliverables.orchestrator import mark_job_stage as real_mark_job_stage
    import app.tasks.professional_deliverables as task_module

    _bundle_id, job_id = _make_task_job(client, session_payload)
    _patch_task_generators(monkeypatch, tmp_path)
    stages: list[str] = []
    progresses: list[int] = []

    def recording_mark_job_stage(db, job, *, stage: str, progress: int | None = None, bundle=None):
        stages.append(stage)
        progresses.append(progress if progress is not None else -1)
        return real_mark_job_stage(db, job, stage=stage, progress=progress, bundle=bundle)

    monkeypatch.setattr(task_module, "mark_job_stage", recording_mark_job_stage)

    run_professional_deliverable_bundle_task = task_module.run_professional_deliverable_bundle_task
    run_professional_deliverable_bundle_task(job_id)

    assert stages == ["adapter", "export_2d", "export_3d", "export_usdz", "render_video", "validate"]
    assert progresses == [10, 25, 50, 65, 85, 95]


def test_product_task_does_not_overwrite_glb_after_export_3d(client, session_payload, monkeypatch, tmp_path):
    from app.tasks.professional_deliverables import run_professional_deliverable_bundle_task

    _bundle_id, job_id = _make_task_job(client, session_payload)
    glb_content = b"stable-product-glb"
    _patch_task_generators(monkeypatch, tmp_path, glb_content=glb_content)

    run_professional_deliverable_bundle_task(job_id)

    assert (tmp_path / "3d" / "model.glb").read_bytes() == glb_content


def test_product_task_does_not_call_sprint3_compatibility_wrapper(client, session_payload, monkeypatch, tmp_path):
    from app.services.professional_deliverables import sprint3_demo
    import app.tasks.professional_deliverables as task_module

    assert not hasattr(task_module, "generate_project_ar_video_bundle")

    def forbidden_wrapper(*_args, **_kwargs):
        raise AssertionError("product task must use split Sprint 3 helpers")

    monkeypatch.setattr(sprint3_demo, "generate_project_ar_video_bundle", forbidden_wrapper)
    _bundle_id, job_id = _make_task_job(client, session_payload)
    _patch_task_generators(monkeypatch, tmp_path)

    task_module.run_professional_deliverable_bundle_task(job_id)


def test_product_task_succeeds_with_required_artifacts_and_assets(client, session_payload, monkeypatch, tmp_path):
    from app.tasks.professional_deliverables import run_professional_deliverable_bundle_task

    bundle_id, job_id = _make_task_job(client, session_payload)
    stale_outputs = [
        _touch(tmp_path / "manifest.json"),
        _touch(tmp_path / "sprint4_gate_summary.json"),
        _touch(tmp_path / "sprint4_gate_summary.md"),
        _touch(tmp_path / "derivatives" / "hero_still_4k.png"),
        _touch(tmp_path / "derivatives" / "preview.gif"),
    ]
    _patch_task_generators(monkeypatch, tmp_path)

    result = run_professional_deliverable_bundle_task(job_id)

    assert result["status"] == "completed"
    assert all(not output.exists() for output in stale_outputs)
    with SessionLocal() as db:
        bundle = db.get(ProfessionalDeliverableBundle, bundle_id)
        assert bundle.status == "ready"
        assert bundle.quality_status == "pass"
        roles = {asset.asset_role for asset in bundle.assets}
        assert {"pdf", "dxf", "glb", "fbx", "usdz", "mp4", "gate_summary_json", "gate_summary_md"} <= roles
        assert all(asset.asset_role not in {"marketing_reel", "hero_still", "gif_preview", "manifest", "sprint4_gate_summary_json"} for asset in bundle.assets)


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
        roles = {asset.asset_role for asset in bundle.assets}
        assert "mp4" not in roles

    bundle_id, job_id = _make_task_job(client, session_payload)
    _patch_task_generators(monkeypatch, tmp_path / "skipped", sprint3_skipped=True)

    try:
        run_professional_deliverable_bundle_task(job_id)
    except RuntimeError as exc:
        assert "Sprint 3 skipped" in str(exc)
    else:
        raise AssertionError("skipped Sprint 3 gate should fail")

    with SessionLocal() as db:
        bundle = db.get(ProfessionalDeliverableBundle, bundle_id)
        assert bundle.status == "failed"


def test_product_task_keeps_partial_assets_when_final_validation_fails(client, session_payload, monkeypatch, tmp_path):
    from app.tasks.professional_deliverables import run_professional_deliverable_bundle_task

    bundle_id, job_id = _make_task_job(client, session_payload)
    _patch_task_generators(monkeypatch, tmp_path, sprint3_failed_gate=True)

    try:
        run_professional_deliverable_bundle_task(job_id)
    except RuntimeError as exc:
        assert "Camera collision sanity" in str(exc)
    else:
        raise AssertionError("failed camera gate should fail final validation")

    with SessionLocal() as db:
        bundle = db.get(ProfessionalDeliverableBundle, bundle_id)
        assert bundle.status == "failed"
        assert bundle.quality_status == "partial"
        roles = {asset.asset_role for asset in bundle.assets}
        assert {"pdf", "dxf", "glb", "fbx", "usdz", "mp4", "gate_summary_json", "gate_summary_md"} <= roles
        assert {asset.status for asset in bundle.assets if asset.asset_role != "dwg"} == {"partial"}


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
