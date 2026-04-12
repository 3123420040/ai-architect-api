from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError

from app.core.config import settings


class UploadsNotConfiguredError(RuntimeError):
    pass


def uploads_enabled() -> bool:
    return bool(
        settings.s3_endpoint_url
        and settings.s3_access_key
        and settings.s3_secret_key
        and settings.s3_bucket
    )


@lru_cache
def create_s3_client():
    if not uploads_enabled():
        raise UploadsNotConfiguredError("S3/MinIO uploads are not configured")

    return boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint_url,
        aws_access_key_id=settings.s3_access_key,
        aws_secret_access_key=settings.s3_secret_key,
        region_name=settings.s3_region,
        use_ssl=settings.s3_secure,
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )


def ensure_bucket_exists() -> None:
    client = create_s3_client()
    bucket_name = settings.s3_bucket
    assert bucket_name is not None

    try:
        client.head_bucket(Bucket=bucket_name)
    except ClientError as exc:
        error_code = exc.response.get("Error", {}).get("Code", "")
        if error_code not in {"404", "NoSuchBucket", "NotFound"}:
            raise
        client.create_bucket(Bucket=bucket_name)


def build_object_key(folder: str, filename: str) -> str:
    safe_name = Path(filename).name or "upload.bin"
    return f"{folder.strip('/')}/{uuid4()}-{safe_name}"


def _rewrite_for_public_access(url: str) -> str:
    if not settings.s3_public_endpoint_url:
        return url

    source = urlsplit(url)
    target = urlsplit(settings.s3_public_endpoint_url)
    return urlunsplit((target.scheme, target.netloc, source.path, source.query, source.fragment))


def create_presigned_upload(*, folder: str, filename: str, content_type: str, expires_in: int) -> dict[str, str | int]:
    ensure_bucket_exists()
    client = create_s3_client()
    bucket_name = settings.s3_bucket
    assert bucket_name is not None

    object_key = build_object_key(folder, filename)
    upload_url = client.generate_presigned_url(
        "put_object",
        Params={"Bucket": bucket_name, "Key": object_key, "ContentType": content_type},
        ExpiresIn=expires_in,
    )
    download_url = client.generate_presigned_url(
        "get_object",
        Params={"Bucket": bucket_name, "Key": object_key},
        ExpiresIn=expires_in,
    )
    return {
        "object_key": object_key,
        "upload_url": _rewrite_for_public_access(upload_url),
        "download_url": _rewrite_for_public_access(download_url),
        "expires_in": expires_in,
    }
