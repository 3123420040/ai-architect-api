from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import SessionLocal, get_db
from app.deps import get_current_user, get_user_from_access_token, require_roles
from app.models import DesignVersion, Project, User
from app.schemas import GenerateRequest, SelectOptionRequest
from app.services.audit import create_notification, log_action
from app.services.briefing import build_clarification_state
from app.services.brief_contract import derive_brief_contract_state
from app.services.decision_metadata import build_decision_metadata
from app.services.exporter import build_sheet_bundle
from app.services.geometry import ensure_geometry_v2, summarize_geometry
from app.services.gpu_client import generate_floorplans
from app.services.option_strategy_profiles import build_program_synthesis, resolve_option_strategy_profiles
from app.services.state_machine import transition_version
from app.services.storage import save_svg


router = APIRouter(tags=["generation"])


def _next_version_number(db: Session, project_id: str) -> int:
    current = db.scalar(select(func.max(DesignVersion.version_number)).where(DesignVersion.project_id == project_id)) or 0
    return current + 1


def _get_project_for_user(db: Session, project_id: str, current_user: User) -> Project:
    project = db.get(Project, project_id)
    if not project or project.organization_id != current_user.organization_id:
        raise HTTPException(status_code=404, detail="Project not found")
    if not project.brief_json:
        raise HTTPException(status_code=400, detail="Project brief is empty")
    return project


def _assert_brief_locked(project: Project) -> None:
    clarification_state = build_clarification_state(project.brief_json or {})
    if derive_brief_contract_state(project.brief_status, clarification_state) != "locked":
        raise HTTPException(status_code=409, detail="Brief must be locked before generation")


def _generation_source(options: list[dict]) -> str:
    pipelines = [str(option.get("pipeline") or "") for option in options]
    if any(pipeline.startswith("svg-fallback") for pipeline in pipelines):
        return "fallback"
    return "remote_gpu"


def _serialize_versions(created_versions: list[DesignVersion]) -> list[dict]:
    serialized: list[dict] = []
    for version in created_versions:
        metadata = version.generation_metadata or {}
        strategy = metadata.get("option_strategy_profile") or {}
        decision = metadata.get("decision_metadata") or {}
        serialized.append(
            {
                "id": version.id,
                "version_number": version.version_number,
                "status": version.status,
                "option_label": version.option_label,
                "option_description": version.option_description,
                "option_title_vi": decision.get("option_title_vi") or version.option_label,
                "option_summary_vi": decision.get("option_summary_vi") or version.option_description,
                "option_strategy_key": strategy.get("strategy_key"),
                "option_strategy_label_vi": strategy.get("title_vi"),
                "fit_reasons": decision.get("fit_reasons") or [],
                "strengths": decision.get("strengths") or [],
                "caveats": decision.get("caveats") or [],
                "metrics": decision.get("metrics") or {},
                "compare_axes": decision.get("compare_axes") or strategy.get("compare_axes") or [],
                "decision_metadata_degraded": bool(decision.get("degraded")),
                "decision_metadata_degraded_reasons": decision.get("degraded_reasons") or [],
                "generation_source": metadata.get("generation_source"),
                "thumbnail_url": version.floor_plan_urls[0] if version.floor_plan_urls else None,
            }
        )
    return serialized


def _persist_generated_versions(
    db: Session,
    *,
    project: Project,
    current_user: User,
    options: list[dict],
) -> list[DesignVersion]:
    created_versions: list[DesignVersion] = []
    version_number = _next_version_number(db, project.id)
    generation_source = _generation_source(options)
    program_synthesis = build_program_synthesis(project.brief_json or {})
    strategy_profiles = resolve_option_strategy_profiles(
        project.brief_json or {},
        program_synthesis,
        num_options=len(options),
    )

    for index, option in enumerate(options):
        version_value = version_number + index
        strategy_profile = strategy_profiles[index] if index < len(strategy_profiles) else strategy_profiles[-1]
        geometry = ensure_geometry_v2(
            option.get("geometry_json") if isinstance(option, dict) else None,
            project.brief_json,
            index,
            strategy_profile=strategy_profile,
        )
        preview_bundle = build_sheet_bundle(project.name, version_value, geometry)
        preview_sheet = next(
            (sheet for sheet in preview_bundle["sheets"] if str(sheet["type"]).startswith("floor_plan_")),
            preview_bundle["sheets"][0],
        )
        floor_url = save_svg(f"projects/{project.id}/versions", preview_sheet["svg"])
        source_svg_url = save_svg(f"projects/{project.id}/versions/source", str(option.get("svg") or preview_sheet["svg"]))
        geometry_summary = summarize_geometry(geometry)
        decision_metadata = build_decision_metadata(project.brief_json or {}, geometry_summary, strategy_profile)
        option_title = str(
            decision_metadata.get("option_title_vi")
            or option.get("label")
            or f"Phương án {index + 1}"
        )
        option_summary = str(
            decision_metadata.get("option_summary_vi")
            or option.get("description")
            or f"Phương án dựng theo chiến lược {strategy_profile.get('title_vi') or 'rule-based'}."
        )

        version = DesignVersion(
            project_id=project.id,
            version_number=version_value,
            status="generated",
            option_label=option_title[:100],
            option_description=option_summary[:500],
            brief_json=project.brief_json,
            geometry_json=geometry,
            floor_plan_urls=[floor_url],
            generation_metadata={
                "seed": option.get("seed"),
                "duration_ms": option.get("duration_ms"),
                "generated_at": option.get("generated_at"),
                "pipeline": option.get("pipeline"),
                "mime_type": option.get("mime_type"),
                "source_svg_url": source_svg_url,
                "generation_source": generation_source,
                "geometry_schema": geometry.get("$schema"),
                "geometry_summary": geometry_summary,
                "program_synthesis": program_synthesis,
                "option_strategy_profile": strategy_profile,
                "decision_metadata": decision_metadata,
            },
        )
        db.add(version)
        created_versions.append(version)
        db.flush()

    project.status = "options_generated"
    log_action(
        db,
        "generation.complete",
        user_id=current_user.id,
        project_id=project.id,
        details={
            "count": len(created_versions),
            "source": generation_source,
            "strategies": [item.get("strategy_key") for item in strategy_profiles],
        },
    )
    create_notification(
        db,
        user_id=current_user.id,
        notification_type="generation_complete",
        message=f"Da tao {len(created_versions)} phuong an cho {project.name}",
        project_id=project.id,
    )
    db.commit()
    return created_versions


@router.post("/projects/{project_id}/generate", status_code=status.HTTP_201_CREATED)
def generate_options(
    project_id: str,
    payload: GenerateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("architect", "admin")),
) -> dict:
    project = _get_project_for_user(db, project_id, current_user)
    _assert_brief_locked(project)

    project.status = "options_generating"
    db.commit()
    db.refresh(project)
    options = generate_floorplans(project.id, project.brief_json, payload.num_options)
    created_versions = _persist_generated_versions(
        db,
        project=project,
        current_user=current_user,
        options=options,
    )

    return {
        "status": "completed",
        "project_id": project.id,
        "source": _generation_source(options),
        "versions": _serialize_versions(created_versions),
    }


@router.post("/versions/{version_id}/select")
def select_option(
    version_id: str,
    payload: SelectOptionRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("architect", "admin")),
) -> dict:
    version = db.get(DesignVersion, version_id)
    if not version:
        raise HTTPException(status_code=404, detail="Version not found")
    project = db.get(Project, version.project_id)
    if not project or project.organization_id != current_user.organization_id:
        raise HTTPException(status_code=404, detail="Project not found")

    transition_version(version, "under_review")
    project.status = "under_review"
    for candidate in project.versions:
        if candidate.id != version.id and candidate.status == "generated":
            candidate.status = "superseded"
    log_action(
        db,
        "version.select",
        user_id=current_user.id,
        project_id=project.id,
        version_id=version.id,
        details={"comment": payload.comment, "project_status": project.status},
    )
    db.commit()
    db.refresh(version)
    return {"id": version.id, "status": version.status, "project_status": project.status}


@router.websocket("/projects/{project_id}/generate/stream")
async def websocket_generate_stream(websocket: WebSocket, project_id: str) -> None:
    await websocket.accept()
    token = websocket.query_params.get("token")
    if not token:
        await websocket.send_json({"event": "generation:error", "detail": "Missing token"})
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    db = SessionLocal()
    try:
        try:
            current_user = get_user_from_access_token(token, db)
            _get_project_for_user(db, project_id, current_user)
        except HTTPException as exc:
            await websocket.send_json({"event": "generation:error", "detail": exc.detail})
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return

        await websocket.send_json({"event": "generation:ready", "project_id": project_id})

        while True:
            payload = await websocket.receive_json()
            num_options = int(payload.get("num_options", 3))
            if num_options < 1 or num_options > 5:
                await websocket.send_json({"event": "generation:error", "detail": "num_options must be between 1 and 5"})
                continue

            project = _get_project_for_user(db, project_id, current_user)
            _assert_brief_locked(project)
            project.status = "options_generating"
            db.commit()

            await websocket.send_json(
                {
                    "event": "generation:progress",
                    "stage": "queued",
                    "progress": 5,
                    "detail": "Da xep generation vao lane xu ly.",
                }
            )
            await websocket.send_json(
                {
                    "event": "generation:progress",
                    "stage": "contacting_gpu",
                    "progress": 20,
                    "detail": "Dang goi boundary GPU de tao floor plan.",
                }
            )

            options = generate_floorplans(project.id, project.brief_json, num_options)
            generation_source = _generation_source(options)
            await websocket.send_json(
                {
                    "event": "generation:progress",
                    "stage": "received_options",
                    "progress": 55,
                    "detail": f"Da nhan {len(options)} option tu lane {generation_source}.",
                    "source": generation_source,
                }
            )

            created_versions = _persist_generated_versions(
                db,
                project=project,
                current_user=current_user,
                options=options,
            )

            total_versions = len(created_versions) or 1
            for index, version in enumerate(created_versions, start=1):
                progress = 55 + round((index / total_versions) * 40)
                await websocket.send_json(
                    {
                        "event": "generation:progress",
                        "stage": "saved_option",
                        "progress": min(progress, 98),
                        "detail": f"Da luu {version.option_label or f'Version {version.version_number}'}",
                        "version_id": version.id,
                    }
                )

            await websocket.send_json(
                {
                    "event": "generation:done",
                    "status": "completed",
                    "project_id": project.id,
                    "source": generation_source,
                    "versions": _serialize_versions(created_versions),
                }
            )
    except WebSocketDisconnect:
        return
    finally:
        db.close()
