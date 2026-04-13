from __future__ import annotations

from typing import Any

from app.models import DesignVersion, ExportPackage, Project
from app.services.geometry import ensure_geometry_v2, geometry_level_index, geometry_room_index, summarize_geometry
from app.services.presentation_3d.material_mapping import build_material_mapping
from app.services.presentation_3d.shot_planner import build_shot_plan


def build_presentation_scene_spec(
    *,
    project: Project,
    version: DesignVersion,
    issued_package: ExportPackage | None,
    presentation_mode: str = "client_presentation",
) -> dict[str, Any]:
    geometry = ensure_geometry_v2(version.geometry_json, version.brief_json or project.brief_json)
    geometry_summary = summarize_geometry(geometry)
    room_index = geometry_room_index(geometry)
    level_index = geometry_level_index(geometry)
    material_mapping = build_material_mapping(version.brief_json or project.brief_json or {}, geometry)
    shot_plan = build_shot_plan(geometry)

    return {
        "scene_spec_version": "v1",
        "presentation_mode": presentation_mode,
        "project_ref": {
            "project_id": project.id,
            "project_name": project.name,
        },
        "source_version": {
            "version_id": version.id,
            "version_number": version.version_number,
            "status": version.status,
            "approval_status": version.approval_status,
            "issued_package_id": issued_package.id if issued_package else None,
            "issue_revision": issued_package.revision_label if issued_package else None,
        },
        "geometry_summary": geometry_summary,
        "building_scene": {
            "levels": geometry.get("levels", []),
            "rooms": geometry.get("rooms", []),
            "walls": geometry.get("walls", []),
            "openings": geometry.get("openings", []),
            "stairs": geometry.get("stairs", []),
            "site": geometry.get("site", {}),
            "facade_logic": geometry.get("facade_logic", {}),
        },
        "geometry_refs": {
            "level_ids": list(level_index.keys()),
            "room_ids": list(room_index.keys()),
        },
        "material_mapping": material_mapping,
        "staging_rules": {
            "presentation_tier": "client_presentation",
            "people": "off",
            "vehicles": "minimal",
            "decor_density": "moderate",
        },
        "still_shots": shot_plan["still_shots"],
        "walkthrough_video": shot_plan["walkthrough_video"],
        "output_targets": {
            "scene_glb": {"resolution_hint": "web", "format": "glb"},
            "stills": {"format": "png", "width": 1600, "height": 900},
            "video": {"format": "mp4", "width": 1920, "height": 1080, "fps": 30},
        },
    }
