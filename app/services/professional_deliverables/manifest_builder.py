from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.services.professional_deliverables.validators import sha256_file

MANIFEST_VERSION = "1.0.0"


def _relative(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def _inventory(root: Path) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.name == "manifest.json":
            continue
        relative = _relative(path, root)
        if relative.endswith(".dwg") and path.stat().st_size == 0:
            continue
        items.append({"path": relative, "size_bytes": path.stat().st_size, "sha256": sha256_file(path)})
    return items


def _load_metadata(root: Path) -> dict[str, Any]:
    path = root / "3d" / "sprint2_model_metadata.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def build_manifest(
    bundle_root: Path,
    *,
    project_id: str,
    source_brief: dict[str, Any] | None,
    degraded_reasons: list[str] | None = None,
) -> Path:
    metadata = _load_metadata(bundle_root)
    material_list = metadata.get("material_list") or []
    lod_summary = metadata.get("lod_summary") or {"lod_100": 0, "lod_200": 0, "lod_300": 0}
    payload = {
        "project_id": project_id,
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "version": MANIFEST_VERSION,
        "naming_convention": {
            "pattern": "<Project>-<Originator>-<Type>-<Number>",
            "originator": "AIA",
        },
        "lod_summary": lod_summary,
        "material_list": material_list,
        "file_inventory": _inventory(bundle_root),
        "source_brief": json.dumps(source_brief or {}, ensure_ascii=False, sort_keys=True),
        "agent_provenance": {
            "pipeline": "ai-architect-professional-deliverables",
            "sprints": ["1", "2", "3", "4"],
            "sprint4": {
                "reel": "derived from video/master_4k.mp4 using deterministic center crop",
                "hero_still": "extracted from video/master_4k.mp4",
                "gif_preview": "extracted from video/master_4k.mp4",
            },
            "quality": {
                "degraded_reasons": degraded_reasons or [],
            },
        },
    }
    path = bundle_root / "manifest.json"
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path
