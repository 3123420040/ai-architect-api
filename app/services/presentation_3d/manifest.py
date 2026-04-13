from __future__ import annotations

from typing import Any

from app.models import DesignVersion, Presentation3DAsset, Presentation3DBundle, Project


def build_presentation_manifest(
    *,
    project: Project,
    version: DesignVersion,
    bundle: Presentation3DBundle,
    assets: list[Presentation3DAsset],
    qa_report: dict[str, Any],
) -> dict[str, Any]:
    return {
        "manifest_version": "v1",
        "bundle_identity": {
            "bundle_id": bundle.id,
            "scene_spec_revision": bundle.scene_spec_revision,
            "status": bundle.status,
        },
        "source_identity": {
            "project_id": project.id,
            "project_name": project.name,
            "version_id": version.id,
            "version_number": version.version_number,
        },
        "approval": {
            "status": bundle.approval_status,
            "approved_by": bundle.approved_by,
            "approved_at": bundle.approved_at.isoformat() if bundle.approved_at else None,
        },
        "qa_summary": {
            "status": bundle.qa_status,
            "blocking_issues": qa_report.get("blocking_issues", []),
        },
        "delivery_state": {
            "delivery_status": bundle.delivery_status,
            "is_degraded": bundle.is_degraded,
            "degraded_reasons": bundle.degraded_reasons_json or [],
        },
        "assets": [
            {
                "asset_type": asset.asset_type,
                "asset_role": asset.asset_role,
                "url": asset.public_url,
                "checksum": asset.checksum,
                "width": asset.width,
                "height": asset.height,
                "duration_seconds": asset.duration_seconds,
                "metadata": asset.metadata_json or {},
            }
            for asset in assets
        ],
        "branding": {
            "studio_name": "KTC KTS",
            "disclaimer": "Tài liệu 3D trình bày phục vụ duyệt phương án, không thay thế hồ sơ BIM hay hồ sơ thi công.",
        },
        "generation_metadata": bundle.runtime_metadata_json or {},
    }
