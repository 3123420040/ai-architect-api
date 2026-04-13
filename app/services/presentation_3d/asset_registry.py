from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.models import Presentation3DAsset, Presentation3DBundle
from app.services.storage import (
    file_checksum,
    save_base64_binary_at,
    save_binary_at,
    save_json_at,
)


def _storage_key_for(bundle: Presentation3DBundle, artifact: dict[str, Any]) -> str:
    prefix = f"projects/{bundle.project_id}/versions/{bundle.version_id}/3d/{bundle.id}"
    asset_type = str(artifact.get("asset_type") or "")
    asset_role = str(artifact.get("asset_role") or "")
    filename = str(artifact.get("filename") or "artifact.bin")
    shot_id = str(artifact.get("shot_id") or "")

    if asset_type == "scene_spec":
        return f"{prefix}/scene/scene_spec.json"
    if asset_type == "scene":
        return f"{prefix}/scene/scene.glb"
    if asset_type == "render":
        stem = shot_id or Path(filename).stem or asset_role or "render"
        return f"{prefix}/renders/{stem}.png"
    if asset_type == "video":
        return f"{prefix}/video/walkthrough.mp4"
    if asset_type == "manifest":
        return f"{prefix}/manifest/presentation_manifest.json"
    if asset_type == "qa":
        return f"{prefix}/qa/qa_report.json"
    return f"{prefix}/misc/{filename}"


def register_artifact(
    db: Session,
    *,
    bundle: Presentation3DBundle,
    artifact: dict[str, Any],
) -> Presentation3DAsset:
    storage_key = _storage_key_for(bundle, artifact)
    asset_type = str(artifact["asset_type"])
    content_type = str(artifact.get("content_type") or "application/octet-stream")

    if "json_payload" in artifact:
        payload = artifact["json_payload"]
        public_url = save_json_at(storage_key, payload)
        content_bytes = str(payload).encode("utf-8")
    elif "data_base64" in artifact:
        public_url = save_base64_binary_at(storage_key, artifact["data_base64"], content_type=content_type)
        import base64
        content_bytes = base64.b64decode(artifact["data_base64"])
    else:
        binary = artifact.get("data_bytes") or b""
        if isinstance(binary, str):
            binary = binary.encode("utf-8")
        public_url = save_binary_at(storage_key, binary, content_type=content_type)
        content_bytes = binary

    record = Presentation3DAsset(
        bundle_id=bundle.id,
        asset_type=asset_type,
        asset_role=str(artifact.get("asset_role") or asset_type),
        storage_key=storage_key,
        public_url=public_url,
        content_type=content_type,
        byte_size=len(content_bytes),
        checksum=file_checksum(content_bytes),
        width=artifact.get("width"),
        height=artifact.get("height"),
        duration_seconds=artifact.get("duration_seconds"),
        metadata_json={
            "filename": artifact.get("filename"),
            "shot_id": artifact.get("shot_id"),
            **(artifact.get("metadata") or {}),
        },
    )
    db.add(record)
    db.flush()
    return record
