from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user, require_roles
from app.models import DesignVersion, ExportPackage, HandoffBundle, Project, User
from app.schemas import ExportPackageIssueRequest, ExportPackageRequest, ExportResponse
from app.services.audit import create_notification, log_action
from app.services.exporter import export_phase2_package, validate_package_bundle
from app.services.state_machine import transition_version
from app.services.storage import absolute_path


router = APIRouter(
    tags=["exports"],
    dependencies=[Depends(require_roles("architect", "admin"))],
)


def _get_version_project(db: Session, version_id: str, current_user: User) -> tuple[Project, DesignVersion]:
    version = db.get(DesignVersion, version_id)
    if not version:
        raise HTTPException(status_code=404, detail="Version not found")
    project = db.get(Project, version.project_id)
    if not project or project.organization_id != current_user.organization_id:
        raise HTTPException(status_code=404, detail="Project not found")
    return project, version


def _get_project(db: Session, project_id: str, current_user: User) -> Project:
    project = db.get(Project, project_id)
    if not project or project.organization_id != current_user.organization_id:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


def _revision_label_from_index(index: int) -> str:
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    label = ""
    current = index
    while True:
        label = alphabet[current % len(alphabet)] + label
        current = current // len(alphabet) - 1
        if current < 0:
            return label


def _next_revision_label(db: Session, version_id: str) -> str:
    count = db.scalar(select(func.count()).select_from(ExportPackage).where(ExportPackage.version_id == version_id)) or 0
    return _revision_label_from_index(int(count))


def _serialize_package(package: ExportPackage, version: DesignVersion) -> dict:
    return {
        "id": package.id,
        "version_id": package.version_id,
        "revision_label": package.revision_label,
        "status": package.status,
        "deliverable_preset": package.deliverable_preset,
        "quality_status": package.quality_status,
        "quality_report_json": package.quality_report_json or {},
        "manifest_url": package.manifest_url,
        "export_urls": package.export_urls or {},
        "files_manifest": package.files_manifest or [],
        "issue_date": package.issue_date,
        "issued_at": package.issued_at,
        "issued_by": package.issued_by,
        "created_by": package.created_by,
        "is_current": package.is_current,
        "created_at": package.created_at,
        "updated_at": package.updated_at,
    }


def _assert_issue_permission(project: Project, current_user: User) -> None:
    if current_user.role == "admin":
        return
    if project.kts_user_id and project.kts_user_id == current_user.id:
        return
    raise HTTPException(status_code=403, detail="Only the assigned KTS approver can issue a package")


def _set_current_package(db: Session, project_id: str, package_id: str) -> None:
    current_packages = db.scalars(
        select(ExportPackage).where(
            ExportPackage.project_id == project_id,
            ExportPackage.is_current.is_(True),
        )
    ).all()
    for item in current_packages:
        item.is_current = item.id == package_id


def _build_handoff_files(version: DesignVersion, *, package: ExportPackage | None = None) -> list[dict]:
    files_manifest = list(package.files_manifest or []) if package else []
    if not files_manifest:
        for export_type, url in (version.export_urls or {}).items():
            if export_type == "manifest":
                continue
            files_manifest.append({"name": f"{export_type}", "url": url, "type": export_type.split("_")[-1]})
        manifest_url = version.export_urls.get("manifest") if version.export_urls else None
        if manifest_url:
            manifest_path = absolute_path(manifest_url)
            if manifest_path.exists():
                manifest_payload = json.loads(manifest_path.read_text(encoding="utf-8"))
                for sheet in manifest_payload.get("sheets", []):
                    files_manifest.append(
                        {
                            "name": f"{sheet['number']}.svg",
                            "url": sheet["files"]["svg"],
                            "type": "svg",
                        }
                    )
    if version.model_url and not any(item["type"] == "gltf" for item in files_manifest):
        files_manifest.append({"name": "design.gltf", "url": version.model_url, "type": "gltf"})
    return files_manifest


def _create_handoff_bundle(
    db: Session,
    *,
    project: Project,
    version: DesignVersion,
    current_user: User,
    package: ExportPackage | None = None,
    readiness_label: str = "handoff_ready",
) -> HandoffBundle:
    previous_bundles = db.scalars(
        select(HandoffBundle).where(
            HandoffBundle.project_id == project.id,
            HandoffBundle.is_current.is_(True),
        )
    ).all()
    for previous in previous_bundles:
        previous.is_current = False

    bundle = HandoffBundle(
        project_id=project.id,
        version_id=version.id,
        files_manifest=_build_handoff_files(version, package=package),
        readiness_label=readiness_label,
        created_by=current_user.id,
    )
    db.add(bundle)
    return bundle


def _render_package_record(
    db: Session,
    *,
    project: Project,
    version: DesignVersion,
    current_user: User,
    deliverable_preset: str,
    requested_status: str,
    package: ExportPackage | None = None,
    issue_date: str | None = None,
) -> tuple[ExportPackage, dict]:
    package_id = package.id if package else str(uuid.uuid4())
    revision_label = package.revision_label if package else _next_revision_label(db, version.id)

    rendered = export_phase2_package(
        project_id=project.id,
        project_name=project.name,
        version_id=version.id,
        version_number=version.version_number,
        brief_json=version.brief_json or project.brief_json or {},
        geometry_json=version.geometry_json,
        revision_label=revision_label,
        package_id=package_id,
        deliverable_preset=deliverable_preset,
        package_status=requested_status,
        issue_date=issue_date,
    )
    quality_report = validate_package_bundle(rendered["bundle"])
    resolved_status = requested_status

    if requested_status == "review" and quality_report["status"] != "pass":
        resolved_status = "degraded_preview"
        rendered = export_phase2_package(
            project_id=project.id,
            project_name=project.name,
            version_id=version.id,
            version_number=version.version_number,
            brief_json=version.brief_json or project.brief_json or {},
            geometry_json=version.geometry_json,
            revision_label=revision_label,
            package_id=package_id,
            deliverable_preset=deliverable_preset,
            package_status=resolved_status,
            issue_date=issue_date,
        )
        quality_report = validate_package_bundle(rendered["bundle"])

    package_record = package or ExportPackage(
        id=package_id,
        project_id=project.id,
        version_id=version.id,
        revision_label=revision_label,
        created_by=current_user.id,
    )
    if package is None:
        db.add(package_record)

    package_record.status = resolved_status
    package_record.deliverable_preset = deliverable_preset
    package_record.quality_status = quality_report["status"]
    package_record.quality_report_json = quality_report
    package_record.manifest_url = rendered["manifest_url"]
    package_record.export_urls = rendered["export_urls"]
    package_record.files_manifest = rendered["files_manifest"]
    package_record.issue_date = issue_date if resolved_status == "issued" else package_record.issue_date
    package_record.issued_at = datetime.now(timezone.utc) if resolved_status == "issued" else package_record.issued_at
    package_record.issued_by = current_user.id if resolved_status == "issued" else package_record.issued_by
    package_record.is_current = resolved_status == "issued"

    version.geometry_json = rendered["geometry"]
    version.export_urls = rendered["export_urls"]

    return package_record, quality_report


@router.post("/versions/{version_id}/exports", response_model=ExportResponse)
def export_version_assets(
    version_id: str,
    payload: ExportPackageRequest | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ExportResponse:
    project, version = _get_version_project(db, version_id, current_user)
    if version.status not in {"locked", "handoff_ready", "delivered"}:
        raise HTTPException(status_code=403, detail="Version must be locked before export")

    request_payload = payload or ExportPackageRequest()
    package, _ = _render_package_record(
        db,
        project=project,
        version=version,
        current_user=current_user,
        deliverable_preset=request_payload.deliverable_preset,
        requested_status=request_payload.preview_status,
    )
    log_action(
        db,
        "package.preview",
        user_id=current_user.id,
        project_id=project.id,
        version_id=version.id,
        details={
            "package_id": package.id,
            "status": package.status,
            "deliverable_preset": package.deliverable_preset,
        },
    )
    db.commit()
    db.refresh(package)
    return ExportResponse(export_urls=package.export_urls, package=_serialize_package(package, version))


@router.get("/projects/{project_id}/packages")
def list_project_packages(
    project_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    project = _get_project(db, project_id, current_user)
    packages = db.scalars(
        select(ExportPackage)
        .where(ExportPackage.project_id == project.id)
        .order_by(ExportPackage.created_at.desc())
    ).all()
    versions = {version.id: version for version in project.versions}
    return {
        "data": [
            _serialize_package(package, versions[package.version_id])
            for package in packages
            if package.version_id in versions
        ]
    }


@router.post("/packages/{package_id}/issue")
def issue_export_package(
    package_id: str,
    payload: ExportPackageIssueRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    package = db.get(ExportPackage, package_id)
    if not package:
        raise HTTPException(status_code=404, detail="Package not found")

    project = _get_project(db, package.project_id, current_user)
    version = db.get(DesignVersion, package.version_id)
    if not version:
        raise HTTPException(status_code=404, detail="Version not found")
    if version.status not in {"locked", "handoff_ready", "delivered"}:
        raise HTTPException(status_code=403, detail="Version must stay locked before issuing a package")
    if package.status == "degraded_preview" or package.quality_status != "pass":
        raise HTTPException(status_code=409, detail="Package quality gate failed. Issue is blocked.")

    _assert_issue_permission(project, current_user)
    issue_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    issued_package, _ = _render_package_record(
        db,
        project=project,
        version=version,
        current_user=current_user,
        deliverable_preset=package.deliverable_preset,
        requested_status="issued",
        package=package,
        issue_date=issue_date,
    )
    _set_current_package(db, project.id, issued_package.id)

    if version.status == "locked":
        transition_version(version, "handoff_ready")
        project.status = "handoff_ready"

    handoff_bundle = _create_handoff_bundle(
        db,
        project=project,
        version=version,
        current_user=current_user,
        package=issued_package,
        readiness_label="issued",
    )
    log_action(
        db,
        "package.issue",
        user_id=current_user.id,
        project_id=project.id,
        version_id=version.id,
        details={
            "package_id": issued_package.id,
            "note": payload.note,
            "issue_date": issue_date,
        },
    )
    create_notification(
        db,
        user_id=current_user.id,
        notification_type="package_issued",
        message=f"Issued package {issued_package.revision_label} for {project.name}.",
        project_id=project.id,
        version_id=version.id,
    )
    db.commit()
    db.refresh(issued_package)
    return {
        "package": _serialize_package(issued_package, version),
        "version_status": version.status,
        "handoff_bundle_id": handoff_bundle.id,
    }


@router.post("/versions/{version_id}/handoff")
def create_handoff_bundle(
    version_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    project, version = _get_version_project(db, version_id, current_user)
    if version.status not in {"locked", "handoff_ready", "delivered"}:
        raise HTTPException(status_code=403, detail="Version must be locked before handoff")
    if not version.export_urls.get("pdf") or not version.export_urls.get("manifest"):
        raise HTTPException(status_code=403, detail="Missing exports")

    issued_package = db.scalar(
        select(ExportPackage)
        .where(
            ExportPackage.project_id == project.id,
            ExportPackage.version_id == version.id,
            ExportPackage.status == "issued",
        )
        .order_by(ExportPackage.updated_at.desc())
    )

    if version.status == "locked":
        transition_version(version, "handoff_ready")
        project.status = "handoff_ready"

    bundle = _create_handoff_bundle(
        db,
        project=project,
        version=version,
        current_user=current_user,
        package=issued_package,
        readiness_label="issued" if issued_package else "handoff_ready",
    )
    log_action(db, "handoff.create", user_id=current_user.id, project_id=project.id, version_id=version.id)
    create_notification(
        db,
        user_id=current_user.id,
        notification_type="handoff_ready",
        message=f"Handoff bundle cho {project.name} da san sang tai xuong.",
        project_id=project.id,
        version_id=version.id,
    )
    db.commit()
    return {"bundle_id": bundle.id, "status": version.status, "files_manifest": bundle.files_manifest}


@router.get("/projects/{project_id}/handoffs")
def list_handoff_bundles(
    project_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    project = _get_project(db, project_id, current_user)

    bundles = db.scalars(
        select(HandoffBundle)
        .where(HandoffBundle.project_id == project.id)
        .order_by(HandoffBundle.created_at.desc())
    ).all()

    version_by_id = {version.id: version for version in project.versions}
    return {
        "data": [
            {
                "id": bundle.id,
                "version_id": bundle.version_id,
                "version_number": version_by_id.get(bundle.version_id).version_number if version_by_id.get(bundle.version_id) else None,
                "status": version_by_id.get(bundle.version_id).status if version_by_id.get(bundle.version_id) else None,
                "files_manifest": bundle.files_manifest,
                "readiness_label": bundle.readiness_label,
                "is_current": bundle.is_current,
                "created_at": bundle.created_at,
            }
            for bundle in bundles
        ]
    }
