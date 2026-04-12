from __future__ import annotations

import base64
import json
from pathlib import Path
from uuid import uuid4

from app.core.config import settings


def _write(relative_path: str, content: str, binary: bool = False) -> str:
    target = settings.storage_dir / relative_path
    target.parent.mkdir(parents=True, exist_ok=True)
    if binary:
        target.write_bytes(content if isinstance(content, bytes) else content.encode("utf-8"))
    else:
        target.write_text(content, encoding="utf-8")
    return f"/media/{relative_path}"


def save_svg(prefix: str, svg_content: str) -> str:
    return _write(f"{prefix}/{uuid4()}.svg", svg_content)


def save_json(prefix: str, data: dict) -> str:
    return _write(f"{prefix}/{uuid4()}.json", json.dumps(data, indent=2))


def save_text(prefix: str, suffix: str, content: str) -> str:
    return _write(f"{prefix}/{uuid4()}.{suffix}", content)


def save_binary(prefix: str, suffix: str, content: bytes) -> str:
    return _write(f"{prefix}/{uuid4()}.{suffix}", content, binary=True)


def save_base64_binary(prefix: str, suffix: str, content: str) -> str:
    return save_binary(prefix, suffix, base64.b64decode(content))


def absolute_path(url_path: str) -> Path:
    relative = url_path.removeprefix("/media/")
    return settings.storage_dir / relative
