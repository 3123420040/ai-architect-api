from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
from uuid import uuid4

import boto3

from app.core.config import settings


_s3_client = None


def _normalized_key(relative_path: str) -> str:
    return relative_path.lstrip("/")


def _local_target(relative_path: str) -> Path:
    return settings.storage_dir / _normalized_key(relative_path)


def storage_uses_s3() -> bool:
    return bool(settings.s3_bucket and settings.s3_endpoint_url and settings.s3_access_key and settings.s3_secret_key)


def _get_s3_client():
    global _s3_client
    if _s3_client is None:
        _s3_client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint_url,
            aws_access_key_id=settings.s3_access_key,
            aws_secret_access_key=settings.s3_secret_key,
            region_name=settings.s3_region,
        )
    return _s3_client


def storage_url(relative_path: str) -> str:
    key = _normalized_key(relative_path)
    if storage_uses_s3():
        if settings.s3_public_endpoint_url:
            return f"{settings.s3_public_endpoint_url.rstrip('/')}/{settings.s3_bucket}/{key}"
        endpoint = (settings.s3_endpoint_url or "").rstrip("/")
        return f"{endpoint}/{settings.s3_bucket}/{key}"
    return f"/media/{key}"


def _write(relative_path: str, content: str | bytes, binary: bool = False, content_type: str | None = None) -> str:
    key = _normalized_key(relative_path)
    payload = content if isinstance(content, bytes) else content.encode("utf-8")
    if storage_uses_s3():
        extra: dict[str, str] = {}
        if content_type:
            extra["ContentType"] = content_type
        _get_s3_client().put_object(
            Bucket=settings.s3_bucket,
            Key=key,
            Body=payload,
            **extra,
        )
        return storage_url(key)

    target = _local_target(key)
    target.parent.mkdir(parents=True, exist_ok=True)
    if binary:
        target.write_bytes(payload)
    else:
        target.write_text(payload.decode("utf-8"), encoding="utf-8")
    return storage_url(key)


def save_svg(prefix: str, svg_content: str) -> str:
    return _write(f"{prefix}/{uuid4()}.svg", svg_content, content_type="image/svg+xml")


def save_json(prefix: str, data: dict) -> str:
    return _write(f"{prefix}/{uuid4()}.json", json.dumps(data, indent=2), content_type="application/json")


def save_text(prefix: str, suffix: str, content: str) -> str:
    return _write(f"{prefix}/{uuid4()}.{suffix}", content, content_type="text/plain")


def save_binary(prefix: str, suffix: str, content: bytes) -> str:
    return _write(f"{prefix}/{uuid4()}.{suffix}", content, binary=True)


def save_base64_binary(prefix: str, suffix: str, content: str) -> str:
    return save_binary(prefix, suffix, base64.b64decode(content))


def save_json_at(relative_path: str, data: dict) -> str:
    return _write(relative_path, json.dumps(data, indent=2), content_type="application/json")


def save_text_at(relative_path: str, content: str, *, content_type: str = "text/plain") -> str:
    return _write(relative_path, content, content_type=content_type)


def save_binary_at(relative_path: str, content: bytes, *, content_type: str | None = None) -> str:
    return _write(relative_path, content, binary=True, content_type=content_type)


def save_base64_binary_at(relative_path: str, content: str, *, content_type: str | None = None) -> str:
    return save_binary_at(relative_path, base64.b64decode(content), content_type=content_type)


def absolute_path(url_path: str) -> Path:
    relative = url_path.removeprefix("/media/")
    return settings.storage_dir / relative


def object_exists(url_path: str) -> bool:
    if url_path.startswith("/media/"):
        return absolute_path(url_path).exists()
    if storage_uses_s3():
        key = url_path.split(f"/{settings.s3_bucket}/", 1)[-1]
        try:
            _get_s3_client().head_object(Bucket=settings.s3_bucket, Key=key)
            return True
        except Exception:  # noqa: BLE001
            return False
    return False


def read_bytes(url_path: str) -> bytes:
    if url_path.startswith("/media/"):
        return absolute_path(url_path).read_bytes()
    if storage_uses_s3():
        key = url_path.split(f"/{settings.s3_bucket}/", 1)[-1]
        response = _get_s3_client().get_object(Bucket=settings.s3_bucket, Key=key)
        return response["Body"].read()
    raise FileNotFoundError(url_path)


def read_json(url_path: str) -> dict:
    return json.loads(read_bytes(url_path).decode("utf-8"))


def file_checksum(content: bytes) -> str:
    return f"sha256:{hashlib.sha256(content).hexdigest()}"
