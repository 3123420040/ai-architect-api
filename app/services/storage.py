from __future__ import annotations

import base64
import hashlib
import hmac
import json
import mimetypes
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

import boto3
from fastapi import HTTPException
from starlette.responses import StreamingResponse

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


def _sign_asset_key(key: str) -> str:
    payload = base64.urlsafe_b64encode(json.dumps({"key": key}, separators=(",", ":")).encode("utf-8")).decode("ascii").rstrip("=")
    secret = (settings.jwt_secret or settings.app_secret_key).encode("utf-8")
    signature = hmac.new(secret, payload.encode("ascii"), hashlib.sha256).hexdigest()
    return f"{payload}.{signature}"


def _verify_asset_token(token: str) -> str:
    try:
        payload, signature = token.rsplit(".", 1)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Asset not found") from exc
    secret = (settings.jwt_secret or settings.app_secret_key).encode("utf-8")
    expected = hmac.new(secret, payload.encode("ascii"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        raise HTTPException(status_code=404, detail="Asset not found")
    padded = payload + "=" * (-len(payload) % 4)
    try:
        decoded = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8"))
    except (ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=404, detail="Asset not found") from exc
    key = str(decoded.get("key") or "").lstrip("/")
    if not key or ".." in Path(key).parts:
        raise HTTPException(status_code=404, detail="Asset not found")
    return key


def resolve_asset_key(stored_url_or_key: str | None) -> str | None:
    if not stored_url_or_key:
        return None
    value = stored_url_or_key.strip()
    if not value:
        return None
    if value.startswith("/media/"):
        return value.removeprefix("/media/").lstrip("/")
    if value.startswith("s3://"):
        parsed = urlparse(value)
        return parsed.path.lstrip("/")
    if storage_uses_s3():
        bucket = settings.s3_bucket or ""
        parsed = urlparse(value)
        if parsed.scheme in {"http", "https"}:
            path = parsed.path.lstrip("/")
            bucket_prefix = f"{bucket}/"
            if path.startswith(bucket_prefix):
                return path.removeprefix(bucket_prefix)
            return path
    if value.startswith("http://") or value.startswith("https://"):
        return None
    return value.lstrip("/")


def resolve_browser_asset_url(stored_url_or_key: str | None) -> str | None:
    if not stored_url_or_key:
        return None
    value = stored_url_or_key.strip()
    if not value:
        return None
    if value.startswith("/api/v1/assets/") or value.startswith("/media/"):
        return value
    if storage_uses_s3():
        key = resolve_asset_key(value)
        if key:
            return f"/api/v1/assets/{_sign_asset_key(key)}"
    return value


def asset_stream_response(token: str) -> StreamingResponse:
    key = _verify_asset_token(token)
    content_type = mimetypes.guess_type(key)[0] or "application/octet-stream"
    if storage_uses_s3():
        try:
            response = _get_s3_client().get_object(Bucket=settings.s3_bucket, Key=key)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=404, detail="Asset not found") from exc
        content_type = response.get("ContentType") or content_type
        return StreamingResponse(response["Body"], media_type=content_type)

    path = _local_target(key)
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="Asset not found")
    return StreamingResponse(path.open("rb"), media_type=content_type)


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
