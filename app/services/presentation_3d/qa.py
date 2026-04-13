from __future__ import annotations

from typing import Any

from app.models import Presentation3DAsset, Presentation3DBundle
from app.services.storage import object_exists


def _asset_map(assets: list[Presentation3DAsset]) -> dict[str, list[Presentation3DAsset]]:
    groups: dict[str, list[Presentation3DAsset]] = {}
    for asset in assets:
        groups.setdefault(asset.asset_type, []).append(asset)
    return groups


def build_qa_report(bundle: Presentation3DBundle, assets: list[Presentation3DAsset], scene_spec: dict[str, Any]) -> dict[str, Any]:
    groups = _asset_map(assets)
    required_stills = {str(item["shot_id"]) for item in scene_spec.get("still_shots", [])}
    actual_stills = {
        str((asset.metadata_json or {}).get("shot_id"))
        for asset in groups.get("render", [])
        if (asset.metadata_json or {}).get("shot_id")
    }
    video_asset = next((asset for asset in groups.get("video", []) if asset.asset_role == "walkthrough_video"), None)
    scene_asset = next((asset for asset in groups.get("scene", []) if asset.asset_role == "scene_glb"), None)
    checks: list[dict[str, Any]] = []

    def add_check(check_id: str, passed: bool, *, severity: str, message: str) -> None:
        checks.append(
            {
                "check_id": check_id,
                "status": "pass" if passed else "fail",
                "severity": severity,
                "message": message,
            }
        )

    add_check("scene_glb_present", bool(scene_asset and object_exists(scene_asset.public_url)), severity="blocking", message="Scene GLB exists and is readable.")
    add_check("required_stills_present", required_stills.issubset(actual_stills), severity="blocking", message="Required still shot set is present.")
    add_check(
        "walkthrough_video_present",
        bool(video_asset and object_exists(video_asset.public_url) and (video_asset.duration_seconds or 0) >= 45 and (video_asset.duration_seconds or 0) <= 90),
        severity="blocking",
        message="Walkthrough video exists and its duration is within the allowed range.",
    )
    blocking_failures = [item for item in checks if item["severity"] == "blocking" and item["status"] == "fail"]
    warning_checks = [item for item in checks if item["status"] == "fail" and item["severity"] != "blocking"]

    status = "fail" if blocking_failures else ("warning" if warning_checks else "pass")
    degraded_reasons = [item["check_id"] for item in blocking_failures]

    return {
        "bundle_id": bundle.id,
        "status": status,
        "blocking_issues": degraded_reasons,
        "checks": checks,
        "required_shot_ids": sorted(required_stills),
        "actual_shot_ids": sorted(actual_stills),
    }
