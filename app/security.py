from __future__ import annotations

import base64
import hashlib
import hmac
import os
from datetime import datetime, timedelta, timezone

import jwt

from app.core.config import settings


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 120_000)
    return f"pbkdf2_sha256${base64.b64encode(salt).decode()}${base64.b64encode(digest).decode()}"


def verify_password(password: str, password_hash: str) -> bool:
    try:
        _, salt_b64, digest_b64 = password_hash.split("$", 2)
    except ValueError:
        return False
    salt = base64.b64decode(salt_b64.encode())
    expected = base64.b64decode(digest_b64.encode())
    actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 120_000)
    return hmac.compare_digest(actual, expected)


def _encode_token(subject: str, role: str, ttl: timedelta, token_type: str) -> str:
    now = datetime.now(tz=timezone.utc)
    payload = {
        "sub": subject,
        "role": role,
        "type": token_type,
        "iat": int(now.timestamp()),
        "exp": int((now + ttl).timestamp()),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def create_access_token(subject: str, role: str) -> str:
    return _encode_token(
        subject=subject,
        role=role,
        ttl=timedelta(minutes=settings.jwt_access_token_expire_minutes),
        token_type="access",
    )


def create_refresh_token(subject: str, role: str) -> str:
    return _encode_token(
        subject=subject,
        role=role,
        ttl=timedelta(days=settings.jwt_refresh_token_expire_days),
        token_type="refresh",
    )


def decode_token(token: str, expected_type: str) -> dict:
    payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
    if payload.get("type") != expected_type:
        raise jwt.InvalidTokenError("Invalid token type")
    return payload
